"""Features and inference for the document verdict classifier."""

import math

import cv2
import numpy as np


def page_features(image, mask, score, embedding):
    """Summarize the submitted page and its predicted localization map."""
    flat = mask.ravel()
    peak_count = max(1, flat.size // 200)
    peak = np.partition(flat, -peak_count)[-peak_count:]
    _, _, components, _ = cv2.connectedComponentsWithStats((mask >= .5).astype(np.uint8))
    areas = components[1:, cv2.CC_STAT_AREA]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    residual = np.abs(gray - cv2.GaussianBlur(gray, (5, 5), .85))
    return [
        score, float(peak.mean()), *np.quantile(flat, (.5, .9, .97, .99)),
        float((flat >= .5).mean()), float((flat >= .75).mean()),
        float(areas.max(initial=0) / flat.size), float(len(areas) / flat.size),
        *np.quantile(gray, (.1, .5, .9)), float(gray.std()),
        float(residual.mean()), *np.quantile(residual, (.9, .97, .99)),
        float((gray < .75).mean()), image.shape[1] / image.shape[0], *embedding,
    ]


def alteration_probability(features, config):
    if "trees" in config:
        tree_features = np.asarray(features, dtype=np.float32)
        logit = config["intercept"]
        for tree in config["trees"]:
            node = 0
            while tree[node][0] >= 0:
                feature, split, left, right = tree[node]
                node = left if float(tree_features[feature]) <= split else right
            logit += tree[node][1]
    else:
        normalized = (np.asarray(features) - np.asarray(config["feature_mean"])) / config["feature_scale"]
        logit = float(normalized @ np.asarray(config["coefficients"]) + config["intercept"])
    raw = float(np.clip(features[0], .001, .999))
    weight = config["raw_weight"]
    logit = weight * math.log(raw / (1 - raw)) + (1 - weight) * logit
    return 1 / (1 + math.exp(-max(-30., min(30., logit))))
