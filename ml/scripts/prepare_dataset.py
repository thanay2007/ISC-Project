import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPLITS = {"train": range(14), "validation": range(14, 17), "test": range(17, 20)}


def letterbox(image: np.ndarray, size: int, mask=False):
    height, width = image.shape[:2]
    scale = size / max(height, width)
    w, h = max(1, round(width * scale)), max(1, round(height * scale))
    x, y = (size - w) // 2, (size - h) // 2
    interpolation = cv2.INTER_NEAREST if mask else cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    padded = np.full((size, size) + image.shape[2:], 0 if mask else 245, dtype=np.uint8)
    padded[y:y+h, x:x+w] = cv2.resize(image, (w, h), interpolation=interpolation)
    return padded, (x, y, w, h)


def read_image(path: Path, flags=cv2.IMREAD_COLOR):
    decoded = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), flags)
    if decoded is None or min(decoded.shape[:2]) < 16:
        raise ValueError(f"Unreadable dataset item {path}")
    return decoded


def prepare(dataset: Path, out: Path, size: int):
    out.mkdir(parents=True, exist_ok=True)
    manifest = [json.loads(line) for line in (dataset / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    groups, seen = set(), set()
    counts = Counter()
    with (out / "manifest.jsonl").open("w", encoding="utf-8") as stream:
        for row in manifest:
            split = next(name for name, templates in SPLITS.items() if int(row["template"][1:]) in templates)
            paths = [dataset / row[key] for key in ("original", "tampered", "mask")]
            images = [read_image(path) for path in paths[:2]]
            mask = read_image(paths[2], cv2.IMREAD_GRAYSCALE)
            if images[0].shape != images[1].shape or images[0].shape[:2] != mask.shape:
                raise ValueError(f"Unaligned mask for {row['id']}")
            hashes = {hashlib.sha256(image.tobytes()).digest() for image in images}
            group = (row["source"], row["id"])
            if len(hashes) != 2 or hashes & seen or group in groups:
                counts["duplicate_pairs_removed"] += 1
                continue
            seen.update(hashes)
            groups.add(group)
            processed_mask = letterbox(mask, size, mask=True)[0]
            if not processed_mask.any():
                counts["invisible_masks_removed"] += 1
                continue
            for label, image in enumerate(images):
                item_id = f"{row['id']}-{label}"
                processed = letterbox(image, size)[0]
                np.savez_compressed(out / f"{item_id}.npz", image=processed,
                                    mask=processed_mask if label else np.zeros_like(processed_mask))
                record = {k: row[k] for k in ("id", "source", "template", "condition", "category")}
                record.update(split=split, label=label, data=f"{item_id}.npz",
                              original_image=str(paths[label].relative_to(dataset)))
                stream.write(json.dumps(record) + "\n")
                counts[f"{split}_{label}"] += 1
    (out / "summary.json").write_text(json.dumps({"image_size": size, "counts": counts,
                                                  "template_split": {k: list(v) for k, v in SPLITS.items()}}, indent=2))
    print(dict(counts), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "datasets/synthetic")
    parser.add_argument("--out", type=Path, default=ROOT / "datasets/processed")
    parser.add_argument("--size", type=int, default=128)
    args = parser.parse_args()
    if args.size < 64 or args.size % 4:
        parser.error("--size must be at least 64 and divisible by 4")
    prepare(args.dataset, args.out, args.size)
