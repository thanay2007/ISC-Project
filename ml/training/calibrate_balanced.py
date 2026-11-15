"""Calibrate page and localization score weights on the validation split."""

import argparse
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader

from ml.model import image_logit
from ml.training.evaluate_model import load_model
from ml.training.train_balanced import CLASSIFICATION_SOURCES, select_threshold
from ml.training.common import Pages, rows_for


DIVISORS = (1000, 160)
BLENDS = ((0., 160), *((weight, divisor) for divisor in DIVISORS for weight in (.2, .35, .5)))


def validation_logits(model, loader, device):
    pages, masks = [], []
    with torch.inference_mode():
        for image, _, _ in loader:
            pixel, page = model(image.to(device, memory_format=torch.channels_last))
            pages.append(page.cpu())
            masks.append(torch.stack([image_logit(pixel, divisor) for divisor in DIVISORS]).cpu())
    return torch.cat(pages), dict(zip(DIVISORS, torch.cat(masks, dim=1)))


def calibrate(args):
    if (args.out / "config.json").exists():
        raise ValueError("Use a fresh directory for the calibrated checkpoint.")
    torch.set_num_threads(args.threads)
    cv2.setNumThreads(1)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, config, digest = load_model(args.candidate, device)
    if config.get("architecture") != "balanced-unet" or config.get("mask_score_weight"):
        raise ValueError("Calibration requires an unblended balanced U-Net checkpoint.")
    if json.loads((args.data / "summary.json").read_text(encoding="utf-8"))["image_size"] != config["size"]:
        raise ValueError("Validation inputs must match the checkpoint resolution.")
    rows = rows_for(args.data, "validation")
    loader = DataLoader(Pages(args.data, rows), batch_size=args.batch)
    pages, masks = validation_logits(model, loader, device)
    labels = np.array([row["label"] for row in rows])
    sources = np.array([row["source"] for row in rows])
    results = []
    for weight, divisor in BLENDS:
        scores = torch.lerp(pages, masks[divisor], weight).sigmoid().numpy()
        threshold, quality, groups = select_threshold(labels, scores, sources)
        utility = quality + .025 * groups["doctamper"]["recall"]
        results.append({"mask_score_weight": weight, "mask_score_divisor": divisor,
                        "classification_threshold": threshold, "utility": utility, "groups": groups})
    baseline = results[0]
    eligible = [baseline]
    for result in results[1:]:
        if (result["utility"] >= baseline["utility"] + .005 and
                all(result["groups"][source]["roc_auc"] >= baseline["groups"][source]["roc_auc"] - .02
                    for source in CLASSIFICATION_SOURCES) and
                result["groups"]["doctamper"]["recall"] >= baseline["groups"]["doctamper"]["recall"] - .03):
            eligible.append(result)
    selected = max(eligible, key=lambda result: (result["utility"], -result["mask_score_weight"]))
    args.out.mkdir(parents=True, exist_ok=True)
    for field in ("mask_score_weight", "mask_score_divisor", "classification_threshold"):
        config[field] = selected[field]
    config["calibration_policy"] = "Validation-only page and top-mask logit blend with per-source ROC-AUC and DocTamper recall guards."
    shutil.copy2(args.candidate / "best_model.pth", args.out / "best_model.pth")
    (args.out / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    record = {"checkpoint_sha256": digest, "split": "validation", "count": len(rows),
              "selected": selected, "candidates": results}
    (args.out / "calibration.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(selected), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("data", "candidate", "out"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--threads", type=int, default=5)
    calibrate(parser.parse_args())
