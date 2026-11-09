import hashlib
import json
import logging
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

from backend.verifex.opencv_service import regions

LOG = logging.getLogger(__name__)


class CustomForgeryModel:
    def __init__(self, directory: Path, results: Path):
        self.model = None
        self.config = {}
        self.metrics = {}
        self.reason = "Trained model artifacts are unavailable."
        try:
            import torch
            from ml.model import ForgeryUNet, predict_map

            config = json.loads((directory / "config.json").read_text())
            weights = directory / "best_model.pth"
            digest = hashlib.sha256(weights.read_bytes()).hexdigest()
            torch.set_num_threads(min(4, torch.get_num_threads()))
            model = ForgeryUNet()
            model.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
            self.config = {**config, "version": f"{config['version']}+{digest[:12]}"}
            self.model = model.eval()
            self.predict = predict_map
            if (results / "metrics.json").is_file():
                metrics = json.loads((results / "metrics.json").read_text())
                if metrics.get("checkpoint_sha256") == digest and metrics.get("threshold") == config["classification_threshold"]:
                    self.metrics = metrics
        except (ImportError, OSError, ValueError, RuntimeError, KeyError):
            LOG.warning("Custom forgery model unavailable", exc_info=True)

    def infer(self, pages):
        if self.model is None:
            return {"status": "unavailable", "detail": self.reason}, []
        started = perf_counter()
        scores, boxes, overlays = [], [], []
        for index, page in enumerate(pages, start=1):
            score, values = self.predict(self.model, page.image, self.config["size"])
            scores.append(score)
            binary = values >= self.config["mask_threshold"]
            boxes.extend(regions(binary, index, "custom_model", "Region exceeds the model's learned mask threshold.", 8))
            heat = cv2.applyColorMap((values * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
            heat = np.dstack((heat, np.clip((values - .1) * 235, 0, 190).astype(np.uint8)))
            mask = np.zeros((*binary.shape, 4), dtype=np.uint8)
            mask[:, :, :3] = (65, 72, 255)
            mask[:, :, 3] = np.where(binary, 170, 0)
            overlays.append({"heatmap": heat, "mask": mask})
        risk = max(scores)
        prediction = self.config["classes"][int(risk >= self.config["classification_threshold"])]
        return {
            "status": "complete", "name": self.config["name"], "version": self.config["version"],
            "predicted_class": prediction, "risk_score": round(risk, 4), "threshold": self.config["classification_threshold"],
            "regions": boxes, "page_scores": [round(score, 4) for score in scores],
            "inference_ms": round((perf_counter() - started) * 1000, 2),
            "limitations": self.config["limitations"],
        }, overlays
