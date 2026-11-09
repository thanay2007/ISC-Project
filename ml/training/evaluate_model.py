import argparse
import hashlib
import json
import shutil
from pathlib import Path
from time import perf_counter

import cv2
import matplotlib
import numpy as np
import torch
from sklearn.metrics import (accuracy_score, average_precision_score, confusion_matrix, f1_score,
                             precision_recall_curve, precision_score, recall_score, roc_auc_score, roc_curve)
from torch.utils.data import DataLoader

from ml.model import ForgeryUNet, image_logit, predict_map
from ml.training.train_segmenter import Pages, rows_for

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def threshold_for(labels, scores):
    fpr, tpr, cuts = roc_curve(labels, scores, drop_intermediate=False)
    # Prioritize balanced accuracy, then prefer the lower false-positive rate.
    valid = np.where(np.isfinite(cuts) & (fpr < 1) & (tpr > 0))[0]
    if not len(valid):
        return .5
    best = max(valid, key=lambda i: (tpr[i] - fpr[i], -fpr[i]))
    return float(cuts[best])


def summarize(labels, scores, threshold, pixels=None, latency=None):
    truth = np.array(labels)
    scores = np.array(scores)
    predicted = scores >= threshold
    tn, fp, fn, tp = confusion_matrix(truth, predicted, labels=[0, 1]).ravel()
    metrics = {
        "count": len(truth), "accuracy": accuracy_score(truth, predicted),
        "precision": precision_score(truth, predicted, zero_division=0),
        "recall": recall_score(truth, predicted, zero_division=0),
        "f1": f1_score(truth, predicted, zero_division=0),
        "false_positive_rate": float(fp / max(1, fp + tn)),
        "roc_auc": roc_auc_score(truth, scores) if len(set(truth)) == 2 else None,
        "average_precision": average_precision_score(truth, scores) if len(set(truth)) == 2 else None,
        "confusion_matrix": [[int(tn), int(fp)], [int(fn), int(tp)]],
    }
    if pixels is not None:
        overlap, marked, actual = np.asarray(pixels).sum(axis=0)
        metrics.update(iou=float(overlap / max(1, marked + actual - overlap)),
                       dice=float(2 * overlap / max(1, marked + actual)),
                       pixel_precision=float(overlap / max(1, marked)),
                       pixel_recall=float(overlap / max(1, actual)))
    if latency is not None:
        metrics["median_ms"] = round(float(np.median(latency)), 3)
    return metrics


def outputs(model, data, rows, config):
    # Evaluate at batch size 1, the same unit as the deployed page inference.
    loader = DataLoader(Pages(data, rows), batch_size=1)
    scores, pixels, durations = [], [], []
    with torch.inference_mode():
        for image, mask, _ in loader:
            start = perf_counter()
            logits = model(image)
            score = float(image_logit(logits).sigmoid().item())
            binary = (logits.sigmoid().numpy() >= config["mask_threshold"])
            durations.append((perf_counter() - start) * 1000)
            actual = mask.numpy().astype(bool)
            scores.append(score)
            pixels.append([(binary & actual).sum(), binary.sum(), actual.sum()])
    return np.array(scores), np.array(pixels), np.array(durations)


def external(model, config, source):
    groups = {}
    for line in (source / "manifest.jsonl").read_text().splitlines():
        row = json.loads(line)
        image = cv2.imdecode(np.frombuffer((source / row["image"]).read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            continue
        # Match backend's image dimension bound before model letterboxing.
        if max(image.shape[:2]) > 1600:
            scale = 1600 / max(image.shape[:2])
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        start = perf_counter()
        score, _ = predict_map(model, image, config["size"])
        item = (row["label"], score, (perf_counter() - start) * 1000)
        groups.setdefault(row["tier"], []).append(item)
    threshold = config["classification_threshold"]
    results = {}
    for key, entries in groups.items():
        labels, scores, durations = zip(*entries)
        results[key] = summarize(labels, scores, threshold, latency=durations)
    return results


def plots(out, test, labels, scores, history):
    matrix = np.array(test["confusion_matrix"])
    fig, ax = plt.subplots(figsize=(5.2, 4))
    ax.imshow(matrix, cmap="Blues")
    for i, j in np.ndindex(matrix.shape):
        ax.text(j, i, matrix[i, j], ha="center", va="center", color="black",
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": .72})
    ax.set(xticks=[0, 1], xticklabels=["Genuine", "Altered"], yticks=[0, 1], yticklabels=["Genuine", "Altered"],
           xlabel="Predicted class", ylabel="Ground truth", title="Held-out certificate templates")
    fig.tight_layout()
    fig.savefig(out / "confusion_matrix.png", dpi=145)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6, 3.6))
    for key, name in (("training_loss", "Training"), ("validation_loss", "Validation")):
        ax.plot([item["epoch"] for item in history], [item[key] for item in history], label=name)
    ax.set(xlabel="Epoch", ylabel="Loss", title="Compact U-Net training")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "training_curves.png", dpi=145)
    plt.close(fig)
    precision, recall, _ = precision_recall_curve(labels, scores)
    fig, ax = plt.subplots(figsize=(5.5, 4))
    ax.step(recall, precision, where="post")
    ax.axhline(np.mean(labels), color="gray", linestyle="--", label="Class prevalence")
    ax.legend()
    ax.set(xlabel="Recall", ylabel="Precision", xlim=(0, 1.02), ylim=(0, 1.02), title="Held-out precision–recall")
    fig.tight_layout()
    fig.savefig(out / "precision_recall.png", dpi=145)
    plt.close(fig)


def evaluate(args):
    cv2.setNumThreads(1)
    torch.set_num_threads(args.threads)
    args.out.mkdir(parents=True, exist_ok=True)
    config_path = args.model / "config.json"
    config = json.loads(config_path.read_text())
    weights = args.model / "best_model.pth"
    model = ForgeryUNet()
    model.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
    model.eval()
    validation = rows_for(args.data, "validation")
    val_labels = [item["label"] for item in validation]
    val_scores, val_pixels, val_times = outputs(model, args.data, validation, config)
    if args.select_threshold:
        config["classification_threshold"] = threshold_for(val_labels, val_scores)
        config["threshold_selection"] = "Maximum balanced accuracy on held-out validation templates; tie favors lower false-positive rate."
        config_path.write_text(json.dumps(config, indent=2) + "\n")
    threshold = config["classification_threshold"]
    test = rows_for(args.data, "test")
    labels = np.array([item["label"] for item in test])
    scores, pixels, duration = outputs(model, args.data, test, config)
    predicted = scores >= threshold
    report = {
        "checkpoint_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256((args.data / "manifest.jsonl").read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
        "threshold": threshold,
        "validation": summarize(val_labels, val_scores, threshold, val_pixels, val_times),
        "test": summarize(labels, scores, threshold, pixels, duration),
        "history": json.loads((args.model / "history.json").read_text()),
    }
    report["groups"] = {}
    for tag in ("condition", "template"):
        for value in sorted({item[tag] for item in test}):
            selection = np.array([row[tag] == value for row in test])
            report["groups"][value] = summarize(labels[selection], scores[selection], threshold, pixels[selection], duration[selection])
    report["comparisons"] = {"Compact U-Net": report["test"]}
    for candidate in ("resnet18", "ocr_forest"):
        path = args.model / f"{candidate}-metrics.json"
        if path.is_file():
            report["comparisons"][candidate] = json.loads(path.read_text())["test"]
    if args.public:
        report["public_by_tier"] = external(model, config, args.public)
        report["public_benchmark"] = report["public_by_tier"].get("C0")
        report["public_source"] = "Kriyam TamperFlow. Results are reported per compression tier."
    report["samples"] = []
    for truth, prediction in ((0, 0), (1, 1), (0, 1), (1, 0)):
        selected = np.where((labels == truth) & (predicted == prediction))[0]
        selected = sorted(selected, key=lambda i: abs(scores[i] - threshold), reverse=True)[:3]
        for index in selected:
            row = test[index]
            item = {**{key: row[key] for key in ("id", "template", "condition")},
                    "label": truth, "prediction": prediction, "score": round(float(scores[index]), 5)}
            report["samples"].append(item)
            path = args.synthetic / row["original_image"]
            if truth != prediction and path.is_file() and "failure_case" not in report:
                shutil.copyfile(path, args.out / "failure.png")
                if truth:
                    original = args.synthetic / "original" / path.name
                    shutil.copyfile(original, args.out / "failure-original.png")
                else:
                    (args.out / "failure-original.png").unlink(missing_ok=True)
                report["failure_case"] = item
    (args.out / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    plots(args.out, report["test"], labels, scores, report["history"])
    print(json.dumps({"validation": report["validation"], "test": report["test"],
                      "public": report.get("public_by_tier")}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=ROOT / "datasets/processed")
    parser.add_argument("--synthetic", type=Path, default=ROOT / "datasets/synthetic")
    parser.add_argument("--model", type=Path, default=ROOT / "models")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    parser.add_argument("--public", type=Path)
    parser.add_argument("--select-threshold", action="store_true", help="Select threshold using validation before computing held-out metrics.")
    parser.add_argument("--threads", type=int, default=4)
    evaluate(parser.parse_args())
