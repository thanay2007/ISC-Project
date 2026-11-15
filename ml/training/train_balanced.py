"""Train a page classifier and pixel mask model on balanced document batches."""

import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import roc_auc_score
from torch.nn import functional as F
from torch.utils.data import DataLoader

from ml.model import BalancedForgeryUNet
from ml.training.common import Pages, options, rows_for, setup


PAIRED_SOURCES = ("aiforge-v2", "verifex-synthetic")
CLASSIFICATION_SOURCES = (*PAIRED_SOURCES, "tamperflow")
MASK_SOURCES = (*PAIRED_SOURCES, "doctamper")
MASK_THRESHOLDS = np.array([.20, .30, .40, .50, .60, .70, .80])


class BalancedBatches:
    def __init__(self, rows, batch_size, steps, seed):
        self.steps = steps
        self.per_class = batch_size // 8
        self.rng = random.Random(seed)
        grouped, by_label = defaultdict(dict), defaultdict(list)
        for index, row in enumerate(rows):
            grouped[row["source"], row["group"], row.get("view", "page")][row["label"]] = index
            by_label[row["source"], row["label"]].append(index)
        self.pairs = {source: [] for source in PAIRED_SOURCES}
        for (source, _, _), group in grouped.items():
            if source in self.pairs and group.keys() == {0, 1}:
                self.pairs[source].append((group[0], group[1]))
        self.pools = [by_label["tamperflow", 0], by_label["tamperflow", 1], by_label["doctamper", 1]]
        if (any(len(pool) < self.per_class for pool in (*self.pairs.values(), *self.pools[:2])) or
                len(self.pools[2]) < 2 * self.per_class):
            raise ValueError("The mixed dataset needs clean/edited pairs, both TamperFlow classes, and DocTamper masks.")

    def __len__(self):
        return self.steps

    def __iter__(self):
        for _ in range(self.steps):
            batch = []
            for pairs in self.pairs.values():
                for genuine, edited in self.rng.sample(pairs, self.per_class):
                    seed = self.rng.getrandbits(32)
                    batch.extend(((genuine, seed), (edited, seed)))
            for pool in self.pools[:2]:
                batch.extend(self.rng.sample(pool, self.per_class))
            batch.extend(self.rng.sample(self.pools[2], 2 * self.per_class))
            yield batch


def losses_for(mask_logits, page_logits, target, label, pair_count):
    # The first half of a training batch contains aligned genuine and edited pages.
    paired_pages = page_logits[:2 * pair_count].float().reshape(-1, 2)
    page_ranking = F.softplus(paired_pages[:, 0] - paired_pages[:, 1]).mean()
    paired_masks = mask_logits[:2 * pair_count].float().reshape(pair_count, 2, -1)
    edited_regions = target[1:2 * pair_count:2].flatten(1)
    differences = paired_masks[:, 0] - paired_masks[:, 1]
    edited_sizes = edited_regions.sum(dim=1).clamp_min(1)
    pixel_ranking = ((F.softplus(differences) * edited_regions).sum(dim=1) / edited_sizes).mean()
    classified = label >= 0
    page_loss = F.binary_cross_entropy_with_logits(page_logits[classified].float(), label[classified])
    valid = target[:, 0, 0, 0] >= 0
    logits, truth = mask_logits[valid].float().flatten(1), target[valid].flatten(1)
    mask_loss = F.binary_cross_entropy_with_logits(logits, truth, pos_weight=logits.new_tensor(8.))
    positive = truth.sum(dim=1) > 0
    scores, masks = logits[positive].sigmoid(), truth[positive]
    dice = (2 * (scores * masks).sum(dim=1) + 1) / (scores.sum(dim=1) + masks.sum(dim=1) + 1)
    return page_loss + .45 * page_ranking + mask_loss + .65 * (1 - dice.mean()) + .25 * pixel_ranking


def select_threshold(labels, scores, sources):
    cuts = np.unique(np.quantile(scores, np.linspace(0, 1, 301), method="nearest"))
    cuts = np.append(cuts, np.nextafter(scores.max(), np.inf))
    predicted = scores[:, None] >= cuts
    metrics, utilities, false_alarms = {}, [], []
    for source in CLASSIFICATION_SOURCES:
        positive = (sources == source) & (labels == 1)
        negative = (sources == source) & (labels == 0)
        recall = predicted[positive].mean(axis=0)
        fpr = predicted[negative].mean(axis=0)
        quality = (1 + recall - fpr) / 2
        utilities.append(.75 * quality + .25 * np.sqrt(recall * (1 - fpr)))
        false_alarms.append(fpr)
        metrics[source] = (quality, recall, fpr, roc_auc_score(labels[positive | negative], scores[positive | negative]))
    per_source = np.stack(utilities)
    balanced_quality = .6 * per_source.min(axis=0) + .4 * per_source.mean(axis=0)
    doc_recall = predicted[(sources == "doctamper") & (labels == 1)].mean(axis=0)
    # Altered-only DocTamper recall breaks near ties without outweighing genuine-page errors.
    utility = balanced_quality + .025 * doc_recall - .005 * np.mean(false_alarms, axis=0)
    best = int(np.argmax(utility))
    result = {source: {"balanced_accuracy": float(quality[best]), "recall": float(recall[best]),
                       "false_positive_rate": float(fpr[best]), "roc_auc": float(auc)}
              for source, (quality, recall, fpr, auc) in metrics.items()}
    result["doctamper"] = {"recall": float(doc_recall[best])}
    return float(cuts[best]), float(balanced_quality[best]), result


def validate(model, loader, rows, device):
    model.eval()
    sources = np.array([row["source"] for row in rows])
    labels = np.array([row["label"] for row in rows])
    scores = []
    pixels = {source: np.zeros((len(MASK_THRESHOLDS), 3), dtype=np.int64) for source in MASK_SOURCES}
    with torch.inference_mode():
        for image, mask, _ in loader:
            batch_sources = sources[len(scores):len(scores) + len(mask)]
            logits, classification = model(image.to(device, memory_format=torch.channels_last))
            scores.extend(classification.sigmoid().cpu().tolist())
            probabilities = logits.sigmoid().cpu().numpy()
            actual = mask.numpy() > 0
            for source, counts in pixels.items():
                selection = batch_sources == source
                if not selection.any():
                    continue
                truth, maps = actual[selection], probabilities[selection]
                for index, threshold in enumerate(MASK_THRESHOLDS):
                    predicted = maps >= threshold
                    counts[index] += ((predicted & truth).sum(), predicted.sum(), truth.sum())
    threshold, quality, metrics = select_threshold(labels, np.array(scores), sources)
    dice = np.stack([2 * counts[:, 0] / np.maximum(1, counts[:, 1] + counts[:, 2]) for counts in pixels.values()])
    mask_quality = dice.mean(axis=0)
    mask_index = int(np.argmax(mask_quality))
    for source, values in zip(pixels, dice):
        metrics[source]["dice"] = float(values[mask_index])
    return threshold, float(MASK_THRESHOLDS[mask_index]), quality, float(mask_quality[mask_index]), metrics


def train(args):
    device = setup(args)
    dataset = json.loads((args.data / "summary.json").read_text(encoding="utf-8"))
    train_rows, val_rows = (rows_for(args.data, split) for split in ("train", "validation"))
    if args.paired_crops:
        training_groups = {(row["source"], row["group"]) for row in train_rows}
        crop_rows = rows_for(args.paired_crops, "train")
        if not crop_rows or any((row["source"], row["group"]) not in training_groups or
                                row["source"] not in PAIRED_SOURCES or row.get("view") != "native-crop" or
                                row.get("view_size") != dataset["image_size"]
                                for row in crop_rows):
            raise ValueError("Crop views must come from paired training groups at the configured size.")
        train_rows.extend({**row, "data": str((args.paired_crops / row["data"]).resolve())} for row in crop_rows)
    val_groups = {(row["source"], row["label"]) for row in val_rows}
    required = {(source, label) for source in CLASSIFICATION_SOURCES for label in (0, 1)} | {("doctamper", 1)}
    if not required <= val_groups:
        raise ValueError("Validation requires both classes for each classification source and edited DocTamper pages.")
    sampler = BalancedBatches(train_rows, args.batch, args.steps, args.seed)
    loader = DataLoader(Pages(args.data, train_rows, augment=True, classification_sources=CLASSIFICATION_SOURCES),
                        batch_sampler=sampler, num_workers=args.workers,
                        persistent_workers=args.workers > 0, pin_memory=device.type == "cuda")
    validation = DataLoader(Pages(args.data, val_rows), batch_size=args.batch)
    model = BalancedForgeryUNet().to(device, memory_format=torch.channels_last)
    initial_digest = None
    if args.init:
        model.load_state_dict(torch.load(args.init, map_location=device, weights_only=True))
        initial_digest = hashlib.sha256(args.init.read_bytes()).hexdigest()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    amp = args.amp and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    best, stale, history = -1., 0, []
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for image, mask, label in loader:
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, enabled=amp):
                image = image.to(device, non_blocking=True, memory_format=torch.channels_last)
                loss = losses_for(*model(image), mask.to(device, non_blocking=True),
                                  label.to(device, non_blocking=True), 2 * sampler.per_class)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            losses.append(loss.item())
        schedule.step()
        threshold, mask_threshold, quality, dice, sources = validate(model, validation, val_rows, device)
        combined = .7 * quality + .25 * dice + .05 * sources["doctamper"]["recall"]
        history.append({"epoch": epoch, "training_loss": float(np.mean(losses)),
                        "validation_quality": quality, "validation_dice": dice,
                        "selection_score": combined, "sources": sources})
        print(json.dumps(history[-1]), flush=True)
        if combined > best:
            best, stale = combined, 0
            pending = args.out / "best_model.pth.tmp"
            torch.save({key: value.detach().cpu() for key, value in model.state_dict().items()}, pending)
            pending.replace(args.out / "best_model.pth")
            config = {
                "name": "VERIFEX Balanced U-Net", "architecture": "balanced-unet", "version": "mixed-unet-v3",
                "epoch": epoch, "trained_at": datetime.now(timezone.utc).isoformat(), "seed": args.seed,
                "device": str(device), "mixed_precision": amp, "learning_rate": args.lr,
                "batch_size": args.batch, "steps_per_epoch": args.steps, "size": dataset["image_size"],
                "initial_checkpoint_sha256": initial_digest,
                "paired_crop_examples": len(crop_rows) if args.paired_crops else 0,
                "dataset": dataset, "classification_threshold": threshold, "mask_threshold": mask_threshold,
                "classes": ["no_visual_tamper_signal", "visual_tamper_signal"],
                "preprocessing": "Letterboxed RGB and grayscale residual",
                "classification_sources": list(CLASSIFICATION_SOURCES),
                "threshold_policy": "Favor the weakest labeled source's balanced accuracy and recall/specificity balance. Use altered-only DocTamper recall as a secondary signal.",
                "limitations": dataset["limitations"],
            }
            (args.out / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        else:
            stale += 1
        (args.out / "history.json").write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
        if stale >= args.patience:
            break


if __name__ == "__main__":
    parser = options(__doc__)
    parser.add_argument("--steps", type=int, default=300, help="Balanced batches per epoch")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--init", type=Path, help="Initialize weights from a compatible checkpoint before fine-tuning")
    parser.add_argument("--paired-crops", type=Path, help="Optional native crop views of paired training pages")
    parser.add_argument("--amp", action="store_true")
    args = parser.parse_args()
    if args.batch < 8 or args.batch % 8:
        parser.error("--batch must be a positive multiple of eight")
    if args.steps < 1 or args.epochs < 1 or args.workers < 0:
        parser.error("--steps and --epochs must be positive and --workers nonnegative")
    train(args)
