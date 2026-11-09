import cv2
import numpy as np
from sklearn.ensemble import IsolationForest

from .documents import clamp_box


def texture_signals(gray, page):
    height, width = gray.shape
    step = max(48, min(height, width) // 9)
    features, boxes = [], []
    high = cv2.absdiff(gray, cv2.GaussianBlur(gray, (5, 5), .85))
    for y in range(0, height - step + 1, step):
        for x in range(0, width - step + 1, step):
            patch = gray[y:y+step, x:x+step]
            if patch.mean() < 60:
                continue
            details = high[y:y+step, x:x+step]
            features.append([patch.mean(), patch.std(), details.mean(), np.quantile(details, .9)])
            boxes.append(clamp_box((x, y, x+step, y+step), width, height))
    if len(features) < 12:
        return [], None
    forest = IsolationForest(n_estimators=28, contamination="auto", random_state=427, n_jobs=1)
    scores = -forest.fit(features).score_samples(features)
    findings = []
    for index in np.argsort(scores)[-2:][::-1]:
        if scores[index] >= .66:
            findings.append({"kind": "texture", "page": page, "box": boxes[index],
                             "finding": "Local texture differs from peer patches. Layout and seals can cause this."})
    return findings, round(float(max(scores)), 3)
