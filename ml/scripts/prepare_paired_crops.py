"""Prepare matched, native-resolution crop views from paired training pages."""

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from ml.scripts.prepare_dataset import letterbox, read_image
from ml.scripts.prepare_mixed import SYNTHETIC, jsonl


def crop_bounds(mask, size, seed):
    x, y, width, height = cv2.boundingRect(mask)
    if width == 0:
        raise ValueError("An altered training page has an empty mask.")
    side = max(size, round(1.5 * max(width, height)))
    crop_width, crop_height = min(side, mask.shape[1]), min(side, mask.shape[0])
    rng = random.Random(seed)
    left = rng.randint(max(0, x + width - crop_width), min(x, mask.shape[1] - crop_width))
    top = rng.randint(max(0, y + height - crop_height), min(y, mask.shape[0] - crop_height))
    return np.s_[top:top + crop_height, left:left + crop_width]


def write_pair(out, size, genuine, edited, originals):
    original_path, edited_path, mask_path = originals
    mask = read_image(mask_path, cv2.IMREAD_GRAYSCALE)
    window = crop_bounds(mask, size, edited["id"])
    results = []
    for row, path in ((genuine, original_path), (edited, edited_path)):
        image = read_image(path)
        if image.shape[:2] != mask.shape:
            raise ValueError(f"Unaligned paired crop: {path}")
        page, bounds = letterbox(image[window], size)
        target = np.zeros((size, size), dtype=np.uint8)
        if row["label"]:
            x, y, width, height = bounds
            region = (mask[window] > 0).astype(np.float32)
            target[y:y + height, x:x + width] = cv2.resize(region, (width, height), interpolation=cv2.INTER_AREA) > 0
        name = f"{row['source']}-{edited['id']}-{row['label']}.npz"
        if Path(name).name != name:
            raise ValueError(f"Invalid crop identifier: {name}")
        np.savez_compressed(out / name, image=page, mask=target, bounds=np.asarray(bounds))
        results.append({**row, "data": name, "view": "native-crop", "view_size": size})
    return results


def prepare(args):
    cv2.setNumThreads(1)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = args.out / "manifest.jsonl"
    if manifest.exists():
        raise ValueError("Use a fresh directory for each set of crop views.")
    rows = [row for row in jsonl(args.data / "manifest.jsonl")
            if row["split"] == "train" and row["source"] in ("aiforge-v2", SYNTHETIC)]
    genuine = {(row["source"], row["group"]): row for row in rows if row["label"] == 0}
    synthetic = {row["id"]: row for row in jsonl(args.synthetic / "manifest.jsonl")}
    jobs = []
    for edited in rows:
        key = (edited["source"], edited["group"])
        if not edited["label"] or key not in genuine:
            continue
        if edited["source"] == "aiforge-v2":
            part, stem, _ = edited["id"].split("-", 2)
            paths = tuple(args.aiforge / part / folder / f"{stem}.png" for folder in ("authentic", "images", "masks"))
        else:
            paths = tuple(args.synthetic / synthetic[edited["group"]][field] for field in ("original", "tampered", "mask"))
        jobs.append((genuine[key], edited, paths))
    if not jobs:
        raise ValueError("No matching genuine/altered pairs in the training split.")
    pending = manifest.with_suffix(".tmp")
    with pending.open("w", encoding="utf-8") as stream, ThreadPoolExecutor(max_workers=args.workers) as pool:
        def process(job):
            return write_pair(args.out, args.size, *job)

        for index, result in enumerate(pool.map(process, jobs), start=1):
            for row in result:
                stream.write(json.dumps(row) + "\n")
            if index % 250 == 0 or index == len(jobs):
                print(f"Prepared {index}/{len(jobs)} matched crop pairs", flush=True)
    pending.replace(manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("data", "aiforge", "synthetic", "out"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    parser.add_argument("--size", type=int, default=320)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.size < 64 or args.size % 4 or args.workers < 1:
        parser.error("--size must be at least 64 and divisible by 4, and --workers must be positive")
    prepare(args)
