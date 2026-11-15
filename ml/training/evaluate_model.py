"""Evaluate the Balanced U-Net and generate its model card from held-out pages."""

import argparse
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path

import cv2
import matplotlib
import numpy as np
import torch
from sklearn.metrics import (accuracy_score, average_precision_score, confusion_matrix, f1_score,
                             precision_recall_curve, precision_score, recall_score, roc_auc_score)

from ml.model import model_for, predict_map, tensor_image
from ml.scripts.prepare_dataset import ROOT, read_image
from ml.training.common import rows_for

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_model(directory, device):
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    checkpoint = directory / "best_model.pth"
    model = model_for(config).to(device)
    model.load_state_dict(torch.load(checkpoint, map_location=device, weights_only=True))
    return model.eval(), config, hashlib.sha256(checkpoint.read_bytes()).hexdigest()


def summarize(labels, scores, threshold, pixels=None):
    truth = np.array(labels)
    scores = np.array(scores)
    predicted = scores >= threshold
    tn, fp, fn, tp = confusion_matrix(truth, predicted, labels=[0, 1]).ravel()
    metrics = {
        "count": len(truth), "accuracy": accuracy_score(truth, predicted),
        "precision": precision_score(truth, predicted, zero_division=0),
        "recall": recall_score(truth, predicted, zero_division=0),
        "f1": f1_score(truth, predicted, zero_division=0),
        "false_positive_rate": float(fp / (fp + tn)) if fp + tn else None,
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
    return metrics


def score(data, rows, model, config, device, batch_size):
    size = config["size"]
    scored = []
    with torch.inference_mode():
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset:offset + batch_size]
            inputs, truth = [], []
            for row in batch:
                with np.load(data / row["data"], allow_pickle=False) as file:
                    image, mask = file["image"], file["mask"]
                if image.shape[:2] != (size, size):
                    raise ValueError("Prepared images must match the checkpoint input size.")
                inputs.append(tensor_image(image))
                truth.append(mask > 0 if row["mask_kind"] == "pixel" else None)
            logits, classification = model(torch.stack(inputs).to(device))
            scores = classification.sigmoid().cpu().tolist()
            masks = logits.sigmoid().cpu().numpy()[:, 0] >= config["mask_threshold"]
            for row, value, prediction, target in zip(batch, scores, masks, truth):
                pixels = None if target is None else (int((prediction & target).sum()),
                                                       int(prediction.sum()), int(target.sum()))
                scored.append((row["label"], value, pixels))
    return scored


def metrics(scored, threshold):
    labels, scores, _ = zip(*scored)
    annotated = [entry[2] for entry in scored if entry[2] is not None]
    result = summarize(labels, scores, threshold, annotated or None)
    result["pixel_mask_images"] = len(annotated)
    result["balanced_accuracy"] = ((1 + result["recall"] - result["false_positive_rate"]) / 2
                                   if len(set(labels)) == 2 else None)
    return result


def plots(out, test, labels, scores, history):
    matrix = np.array(test["confusion_matrix"])
    fig, ax = plt.subplots(figsize=(5.2, 4))
    ax.imshow(matrix, cmap="Blues")
    for i, j in np.ndindex(matrix.shape):
        ax.text(j, i, matrix[i, j], ha="center", va="center", color="black",
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": .72})
    ax.set(xticks=[0, 1], xticklabels=["Genuine", "Altered"], yticks=[0, 1], yticklabels=["Genuine", "Altered"],
           xlabel="Predicted class", ylabel="Ground truth", title="Held-out documents")
    fig.tight_layout()
    fig.savefig(out / "confusion_matrix.png", dpi=145)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(6, 3.6))
    ax.plot([item["epoch"] for item in history], [item["training_loss"] for item in history])
    ax.set(xlabel="Epoch", ylabel="Loss", title="Balanced U-Net training")
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


def grouped_metrics(rows, scored, threshold):
    groups = defaultdict(list)
    for row, result in zip(rows, scored):
        groups[row["source"]].append(result)
        if row["source"] == "tamperflow":
            groups[f"tamperflow-{row['condition']}"].append(result)
    return {key: metrics(group, threshold) for key, group in sorted(groups.items())}


def record_examples(out, model, config, synthetic, rows, scored, report):
    threshold = config["classification_threshold"]
    by_outcome = defaultdict(list)
    for row, (label, value, _) in zip(rows, scored):
        prediction = int(value >= threshold)
        by_outcome[label, prediction].append({**{key: row[key] for key in ("id", "template", "condition")},
                                               "label": label, "prediction": prediction, "score": round(value, 5)})
    report["samples"] = [sample for group in by_outcome.values()
                         for sample in sorted(group, key=lambda item: abs(item["score"] - threshold), reverse=True)[:3]]

    # Publish a fictional failure fixture only after checking it through the inference preprocessing.
    for name in ("failure.png", "failure-original.png"):
        (out / name).unlink(missing_ok=True)
    model.cpu()
    for row, (label, value, _) in zip(rows, scored):
        if not row.get("original_image") or label == (value >= threshold):
            continue
        path = synthetic / row["original_image"]
        original = synthetic / "original" / path.name
        if not path.is_file() or (label and not original.is_file()):
            continue
        risk, _ = predict_map(model, read_image(path), config["size"])
        prediction = int(risk >= threshold)
        if prediction == label:
            continue
        shutil.copyfile(path, out / "failure.png")
        if label:
            shutil.copyfile(original, out / "failure-original.png")
        report["failure_case"] = {**{key: row[key] for key in ("id", "template", "condition")},
                                  "label": label, "prediction": prediction, "score": round(risk, 5)}
        break


def evaluate(args):
    cv2.setNumThreads(1)
    torch.set_num_threads(args.threads)
    args.out.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, config, digest = load_model(args.model, device)
    threshold = config["classification_threshold"]
    report = {
        "checkpoint_sha256": digest,
        "manifest_sha256": hashlib.sha256((args.data / "manifest.jsonl").read_bytes()).hexdigest(),
        "threshold": threshold,
        "history": json.loads((args.model / "history.json").read_text(encoding="utf-8")),
    }
    for split in ("validation", "test"):
        rows = rows_for(args.data, split)
        if not rows:
            raise ValueError(f"No {split} pages found.")
        scored = score(args.data, rows, model, config, device, args.batch)
        report[split] = metrics(scored, threshold)
        report["groups" if split == "test" else "validation_groups"] = grouped_metrics(rows, scored, threshold)
    labels, scores, _ = zip(*scored)
    record_examples(args.out, model, config, args.synthetic, rows, scored, report)
    plots(args.out, report["test"], labels, scores, report["history"])
    (args.out / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"validation": report["validation"], "test": report["test"]}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--synthetic", type=Path, default=ROOT / "datasets/synthetic")
    parser.add_argument("--model", type=Path, default=ROOT / "models")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    parser.add_argument("--threads", type=int, default=5)
    parser.add_argument("--batch", type=int, default=16)
    evaluate(parser.parse_args())
