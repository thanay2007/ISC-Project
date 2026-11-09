import json
from time import perf_counter

import cv2
import numpy as np
import torch
from sklearn.ensemble import RandomForestClassifier
from torch import nn
from torch.utils.data import DataLoader

from ml.training.evaluate_model import summarize, threshold_for
from ml.training.train_segmenter import Pages, options, rows_for, setup


def text_region_features(image, lines=None):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    # OCR-free fallback estimates text line boxes from horizontal word components.
    if lines is None:
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 12)
        united = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((1, max(5, w//38)), np.uint8))
        count, _, stats, _ = cv2.connectedComponentsWithStats(united)
        lines = [(x/w, y/h, (x+width)/w, (y+height)/h) for x, y, width, height, area in stats[1:count]
                 if w * .02 < width < w * .9 and h * .007 < height < h * .1 and area >= 5]
    vectors = []
    for x0, y0, x1, y1 in sorted(lines, key=lambda box: box[1]):
        block = gray[int(y0*h):max(int(y0*h)+1, int(y1*h)), int(x0*w):max(int(x0*w)+1, int(x1*w))]
        if block.size < 6:
            continue
        edges = np.abs(cv2.Sobel(block, cv2.CV_32F, 1, 0))
        width, height = x1-x0, y1-y0
        transitions = np.where((edges > 30).any(axis=0))[0]
        vectors.append([x0, y0, width, height, width/max(.001, height),
                        block.mean(), block.std(), edges.mean(), np.std(np.diff(transitions)) if len(transitions)>2 else 0])
    patches = [part for row in np.array_split(gray, 8, axis=0) for part in np.array_split(row, 8, axis=1)]
    residuals = [float(cv2.Laplacian(item, cv2.CV_32F).std()) for item in patches]
    distribution = np.quantile(vectors, [.05, .25, .5, .75, .95], axis=0).flatten() if vectors else np.zeros(45)
    return np.r_[len(vectors), distribution, np.quantile(residuals, [.1, .5, .85, .95, .99])]


def forest(args, rows):
    import joblib
    from ml.scripts.prepare_dataset import read_image

    engine = None
    if args.ocr:
        from backend.verifex.documents import Page
        from backend.verifex.ocr_service import OCR
        engine = OCR("paddle")
        engine.warm()
        if not engine.paddle:
            raise RuntimeError("PaddleOCR must be available for --ocr")
    matrices, elapsed = {}, {}
    for split, items in rows.items():
        X, timings = [], []
        for row in items:
            with np.load(args.data / row["data"], allow_pickle=False) as file:
                image = file["image"]
            start = perf_counter()
            if engine:
                raster = read_image(args.synthetic / row["original_image"])
                lines = [item["box"] for item in engine.extract(Page(raster, []))[0]]
                vector = text_region_features(raster, lines)
            else:
                vector = text_region_features(image)
            X.append(vector)
            timings.append((perf_counter() - start) * 1000)
        matrices[split], elapsed[split] = X, timings
    model = RandomForestClassifier(n_estimators=250, min_samples_leaf=4, class_weight="balanced",
                                   random_state=args.seed, n_jobs=min(args.threads, 4))
    model.fit(matrices["train"], [row["label"] for row in rows["train"]])
    predictions = {}
    for split in ("validation", "test"):
        start = perf_counter()
        predictions[split] = model.predict_proba(matrices[split])[:, 1]
        overhead = (perf_counter() - start) * 1000 / len(matrices[split])
        elapsed[split] = [t + overhead for t in elapsed[split]]
    joblib.dump(model, args.out / "ocr_forest.joblib")
    return predictions, elapsed, "PaddleOCR lines" if engine else "OpenCV estimated text regions"


def resnet(args, rows, device):
    from torchvision.models import ResNet18_Weights, resnet18
    model = resnet18(weights=ResNet18_Weights.DEFAULT)
    model.requires_grad_(False)
    model.fc = nn.Linear(model.fc.in_features, 1)
    model.to(device)
    optimizer = torch.optim.AdamW(model.fc.parameters(), lr=args.lr)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    train = DataLoader(Pages(args.data, rows["train"], augment=True, rgb=True), batch_size=args.batch, shuffle=True)
    validation = DataLoader(Pages(args.data, rows["validation"], rgb=True), batch_size=args.batch)

    def infer(loader):
        scores, durations, losses = [], [], []
        with torch.inference_mode():
            for image, _, label in loader:
                start = perf_counter()
                logits = model(image.to(device)).flatten()
                loss = nn.functional.binary_cross_entropy_with_logits(logits, label.to(device))
                values = logits.sigmoid().cpu().tolist()
                durations.extend([(perf_counter() - start) * 1000 / len(values)] * len(values))
                scores.extend(values)
                losses.append(loss.item())
        return scores, durations, float(np.mean(losses))

    best, stale, history = float("inf"), 0, []
    for epoch in range(1, args.epochs + 1):
        model.eval()  # freeze pretrained BatchNorm running statistics
        losses = []
        for image, _, label in train:
            optimizer.zero_grad()
            logits = model(image.to(device)).flatten()
            loss = nn.functional.binary_cross_entropy_with_logits(logits, label.to(device))
            loss.backward()
            optimizer.step()
            losses.append(loss.item())
        schedule.step()
        _, _, val_loss = infer(validation)
        history.append({"epoch": epoch, "training_loss": float(np.mean(losses)), "validation_loss": val_loss})
        print(history[-1], flush=True)
        if val_loss < best:
            best, stale = val_loss, 0
            torch.save(model.state_dict(), args.out / "resnet18.pth")
        else:
            stale += 1
            if stale >= args.patience:
                break
    model.load_state_dict(torch.load(args.out / "resnet18.pth", map_location=device, weights_only=True))
    values, timings = {}, {}
    for split in ("validation", "test"):
        values[split], timings[split], _ = infer(DataLoader(Pages(args.data, rows[split], rgb=True), batch_size=1))
    (args.out / "resnet18-history.json").write_text(json.dumps(history, indent=2))
    return values, timings, "ImageNet-pretrained ResNet18 with frozen backbone"


if __name__ == "__main__":
    parser = options("Train a transfer-learning or text-region classifier")
    parser.add_argument("--architecture", choices=["resnet18", "ocr_forest"], default="resnet18")
    parser.add_argument("--ocr", action="store_true", help="Use PaddleOCR text boxes for the forest")
    parser.add_argument("--synthetic", type=type(parser.get_default("data")), default=parser.get_default("data").parent / "synthetic")
    args = parser.parse_args()
    device = setup(args)
    rows = {split: rows_for(args.data, split) for split in ("train", "validation", "test")}
    scores, times, method = resnet(args, rows, device) if args.architecture == "resnet18" else forest(args, rows)
    labels = {split: [row["label"] for row in rows[split]] for split in ("validation", "test")}
    threshold = threshold_for(labels["validation"], scores["validation"])
    metrics = {split: summarize(labels[split], scores[split], threshold, latency=times[split]) for split in labels}
    metrics.update(threshold=threshold, method=method, device=str(device))
    (args.out / f"{args.architecture}-metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2), flush=True)
