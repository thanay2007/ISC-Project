from collections import Counter

import cv2
import numpy as np

from .anomaly_service import texture_signals
from .documents import clamp_box


def regions(binary, page, kind, description, limit=12):
    height, width = binary.shape
    contours, _ = cv2.findContours(binary.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < max(10, .00015 * width * height):
            continue
        boxes.append({"page": page, "box": clamp_box((x, y, x+w, y+h), width, height),
                      "kind": kind, "finding": description})
        if len(boxes) >= limit:
            break
    return boxes


def forensics(image, lines, page, mime):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    findings, anomaly = texture_signals(gray, page)
    heights = np.array([item["box"][3] - item["box"][1] for item in lines])
    if len(heights) >= 7:
        typical = np.median(heights)
        for index in np.where((heights < typical * .47) | (heights > typical * 2.7))[0][:3]:
            findings.append({"page": page, "box": lines[index]["box"], "kind": "line_height",
                             "finding": "Text height differs from surrounding lines. Headings and fine print can cause this."})
    if mime == "image/jpeg":
        ok, encoded = cv2.imencode(".jpg", gray, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if ok:
            difference = cv2.absdiff(gray, cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE))
            smoothed = cv2.blur(difference.astype(np.float32), (19, 19))
            cutoff = max(7., float(np.quantile(smoothed, .997)))
            findings.extend(regions(smoothed >= cutoff, page, "compression", "Localized JPEG re-encoding residual. Edges and prior scans can produce this pattern.", 3))
    keypoints, desc = cv2.ORB_create(nfeatures=340).detectAndCompute(gray, None)
    if desc is not None and len(desc) >= 3:
        vectors = Counter()
        locations = {}
        for candidates in cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(desc, desc, k=3):
            distinct = [item for item in candidates if item.queryIdx != item.trainIdx]
            if len(distinct) < 2 or distinct[0].distance >= min(24, distinct[1].distance * .72):
                continue
            match = distinct[0]
            x, y = keypoints[match.queryIdx].pt
            a, b = keypoints[match.trainIdx].pt
            if abs(a-x) + abs(b-y) < 45 or (a, b) < (x, y):
                continue
            key = (round((a-x)/8), round((b-y)/8))
            vectors[key] += 1
            locations.setdefault(key, []).append((a, b))
        if vectors and (top := vectors.most_common(1)[0])[1] >= 6:
            x, y = np.asarray(locations[top[0]]).T
            height, width = gray.shape
            if np.ptp(x) + np.ptp(y) < .3 * max(height, width):
                findings.append({"page": page, "box": clamp_box((x.min()-12, y.min()-12, x.max()+12, y.max()+12), width, height),
                                 "kind": "copy_move", "finding": "Several keypoints repeat at the same displacement. Repeated decorations may produce this."})
    return findings, anomaly


def compare_images(original, uploaded, page):
    height, width = uploaded.shape[:2]
    source = cv2.resize(original, (width, height), interpolation=cv2.INTER_AREA)
    gray_a = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(uploaded, cv2.COLOR_BGR2GRAY)
    if not np.array_equal(gray_a, gray_b):
        try:
            transform = np.eye(2, 3, dtype=np.float32)
            scale = min(1., 700 / max(height, width))
            small_a = cv2.resize(gray_a, None, fx=scale, fy=scale)
            small_b = cv2.resize(gray_b, None, fx=scale, fy=scale)
            score, transform = cv2.findTransformECC(small_b, small_a, transform, cv2.MOTION_EUCLIDEAN,
                                                     (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 24, .0001))
            transform[:, 2] /= scale
            if score > .55 and np.max(np.abs(transform[:, 2])) < .08 * max(height, width):
                gray_a = cv2.warpAffine(gray_a, transform, (width, height),
                                        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
        except cv2.error:
            pass
    difference = cv2.absdiff(gray_a, gray_b)
    binary = cv2.morphologyEx((difference > 27).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 9), np.uint8))
    heat = np.zeros((height, width, 4), np.uint8)
    heat[:, :, :3] = (65, 78, 255)
    heat[:, :, 3] = np.where(binary, 175, 0)
    return {"changed_fraction": round(float(binary.mean()), 5),
            "regions": regions(binary, page, "image_difference", "Rendered pixels differ from the authorized original.")}, heat
