import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import torch
from sklearn.metrics import f1_score
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset

from ml.model import ForgeryUNet, image_logit, tensor_image

ROOT = Path(__file__).resolve().parents[1]


def rows_for(folder, split):
    return [row for line in (folder / "manifest.jsonl").read_text().splitlines()
            if (row := json.loads(line))["split"] == split]


class Pages(Dataset):
    def __init__(self, folder, rows, augment=False, rgb=False):
        self.folder, self.rows, self.augment, self.rgb = folder, rows, augment, rgb

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        with np.load(self.folder / row["data"], allow_pickle=False) as file:
            image, mask = file["image"], file["mask"]
        if self.augment:
            if random.random() < .5:
                size = image.shape[0]
                warp = cv2.getRotationMatrix2D((size / 2, size / 2), random.uniform(-3, 3), 1)
                image = cv2.warpAffine(image, warp, (size, size), borderMode=cv2.BORDER_REPLICATE)
                mask = cv2.warpAffine(mask, warp, (size, size), flags=cv2.INTER_NEAREST)
            if random.random() < .6:
                image = np.clip(image.astype(np.float32) * random.uniform(.9, 1.1) +
                                random.uniform(-9, 9), 0, 255).astype(np.uint8)
            if random.random() < .16:
                image = cv2.GaussianBlur(image, (3, 3), .55)
            if random.random() < .16:
                ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, random.randrange(55, 92)])
                if ok:
                    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if self.rgb:
            pixels = torch.from_numpy(cv2.cvtColor(image, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)).float() / 255
            pixels = (pixels - torch.tensor([.485, .456, .406])[:, None, None]) / torch.tensor([.229, .224, .225])[:, None, None]
        else:
            pixels = tensor_image(image)
        return pixels, torch.from_numpy((mask > 0).astype(np.float32))[None], torch.tensor(row["label"]).float()


def loss_for(logits, target, label):
    probabilities = logits.sigmoid()
    overlap = (probabilities * target).sum()
    dice_loss = 1 - (2 * overlap + 1) / (probabilities.sum() + target.sum() + 1)
    weight = torch.tensor(12., device=logits.device)
    return (F.binary_cross_entropy_with_logits(logits, target, pos_weight=weight) +
            .6 * dice_loss + .55 * F.binary_cross_entropy_with_logits(image_logit(logits), label))


def validation(model, loader, device):
    model.eval()
    truth, scores, losses = [], [], []
    thresholds = np.linspace(.15, .85, 29)
    mask_thresholds = [.25, .35, .45, .55, .65]
    pixels = np.zeros((len(mask_thresholds), 3), dtype=np.int64)
    with torch.inference_mode():
        for image, mask, label in loader:
            logits = model(image.to(device))
            losses.append(loss_for(logits, mask.to(device), label.to(device)).item())
            truth.extend(label.tolist())
            scores.extend(image_logit(logits).sigmoid().cpu().tolist())
            probabilities = logits.sigmoid().cpu().numpy()
            actual = mask.numpy().astype(bool)
            for index, threshold in enumerate(mask_thresholds):
                predicted = probabilities >= threshold
                pixels[index] += [(predicted & actual).sum(), predicted.sum(), actual.sum()]
    f1, threshold = max((f1_score(truth, np.array(scores) >= t), float(t)) for t in thresholds)
    dice = 2 * pixels[:, 0] / np.maximum(1, pixels[:, 1] + pixels[:, 2])
    best = int(np.argmax(dice))
    return float(np.mean(losses)), float(f1), threshold, mask_thresholds[best], float(dice[best])


def options(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--data", type=Path, default=ROOT / "datasets/processed")
    parser.add_argument("--out", type=Path, default=ROOT / "models")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch", type=int, default=24)
    parser.add_argument("--lr", type=float, default=.002)
    parser.add_argument("--threads", type=int, default=5)
    parser.add_argument("--seed", type=int, default=427)
    parser.add_argument("--patience", type=int, default=5)
    return parser


def setup(args):
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    cv2.setNumThreads(1)
    torch.use_deterministic_algorithms(True, warn_only=True)
    args.out.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Training on {device}", flush=True)
    return device


def train(args):
    device = setup(args)
    train_rows, val_rows = (rows_for(args.data, part) for part in ("train", "validation"))
    train = DataLoader(Pages(args.data, train_rows, augment=True), batch_size=args.batch, shuffle=True)
    val = DataLoader(Pages(args.data, val_rows), batch_size=args.batch)
    model = ForgeryUNet().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    dataset = json.loads((args.data / "summary.json").read_text())
    best, stale, history = -1., 0, []
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for image, mask, label in train:
            optimizer.zero_grad()
            loss = loss_for(model(image.to(device)), mask.to(device), label.to(device))
            loss.backward()
            optimizer.step()
            losses.append(loss.item())
        schedule.step()
        val_loss, f1, threshold, mask_threshold, dice = validation(model, val, device)
        history.append({"epoch": epoch, "training_loss": float(np.mean(losses)), "validation_loss": val_loss, "validation_f1": f1, "validation_dice": dice})
        print(history[-1], flush=True)
        combined = .6 * f1 + .4 * dice
        if combined > best:
            best, stale = combined, 0
            torch.save(model.cpu().state_dict(), args.out / "best_model.pth")
            model.to(device)
            config = {
                "name": "VERIFEX Compact U-Net", "version": "synthetic-unet-v1",
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "epoch": epoch, "seed": args.seed, "device": str(device), "learning_rate": args.lr,
                "batch_size": args.batch, "size": dataset["image_size"], "dataset": dataset,
                "classification_threshold": threshold, "mask_threshold": mask_threshold,
                "classes": ["no_visual_tamper_signal", "visual_tamper_signal"],
                "preprocessing": "Letterbox BGR, normalized grayscale, Gaussian residual; inverse crop for masks",
                "limitations": "Trained on fictional certificates. Scores are uncalibrated visual signals. Scans, uncommon layouts and subtle edits can produce missed or spurious regions.",
            }
            (args.out / "config.json").write_text(json.dumps(config, indent=2))
        else:
            stale += 1
            if stale >= args.patience:
                break
        (args.out / "history.json").write_text(json.dumps(history, indent=2))


if __name__ == "__main__":
    train(options("Train the compact forgery U-Net").parse_args())
