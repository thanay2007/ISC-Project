"""Build a split-safe VERIFEX training manifest from local research datasets."""

import argparse
import hashlib
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ml.scripts.prepare_dataset import ROOT, SPLITS, letterbox, read_image

FOLDS = ("test", "validation", "train")
TIERS = {"C0", "C2", "C4"}
SYNTHETIC = "verifex-synthetic"


@dataclass
class Example:
    source: str
    key: str
    group: str
    image: np.ndarray
    label: int
    mask: np.ndarray | None
    condition: str = "standard"
    original_image: str | None = None


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def image_digest(image: np.ndarray) -> str:
    return digest(str(image.shape).encode() + image.tobytes())


def fold_bucket(key: str, seed: int) -> int:
    return int(digest(f"{seed}:{key}".encode())[:8], 16) % 100


def grouped_fold(key: str, seed: int) -> str:
    bucket = fold_bucket(key, seed)
    return "test" if bucket < 20 else "validation" if bucket < 35 else "train"


def jsonl(path):
    with path.open(encoding="utf-8-sig") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def synthetic_examples(root, fold):
    for row in jsonl(root / "manifest.jsonl"):
        if int(row["template"][1:]) not in SPLITS[fold]:
            continue
        for name, label in (("original", 0), ("tampered", 1)):
            relative = row[name]
            image = read_image(root / relative)
            mask = read_image(root / row["mask"], cv2.IMREAD_GRAYSCALE) if label else np.zeros(image.shape[:2], np.uint8)
            yield Example(SYNTHETIC, f"{row['id']}-{label}", row["id"], image, label, mask, row["condition"], relative)


def paired_aiforge(root, seed):
    """Use official test pairs and partition the rest by the original image digest."""
    pairs = {fold: [] for fold in FOLDS}
    heldout = set()
    for part in ("TestingSet", "TrainingSet"):
        base = root / part
        for original in sorted((base / "authentic").glob("*.png")):
            forged = base / "images" / original.name
            mask = base / "masks" / original.name
            if not forged.is_file() or not mask.is_file():
                continue
            group = image_digest(read_image(original))
            if part == "TestingSet":
                heldout.add(group)
                fold = "test"
            else:
                if group in heldout:
                    continue
                fold = "validation" if fold_bucket(group, seed) < 15 else "train"
            pairs[fold].append((part, group, original, forged, mask))
    return pairs


def aiforge_examples(pairs):
    for part, group, original, forged, mask_path in pairs:
        mask = read_image(mask_path, cv2.IMREAD_GRAYSCALE)
        key = f"{part}-{original.stem}"
        yield Example("aiforge-v2", key + "-genuine", group, read_image(original), 0, np.zeros_like(mask))
        yield Example("aiforge-v2", key + "-altered", group, read_image(forged), 1, mask)


def aiforge_pilot_examples(root, fold, seed):
    part = "TestingSet" if fold == "test" else "TrainingSet"
    directory = root / part
    for image in sorted((directory / "images").glob("*.png")):
        key = f"{part}-{image.stem}"
        if fold != "test" and (fold_bucket(key, seed) < 15) != (fold == "validation"):
            continue
        mask = directory / "masks" / image.name
        if mask.is_file():
            yield Example("aiforge-v2", key, key, read_image(image), 1, read_image(mask, cv2.IMREAD_GRAYSCALE))


def tamperflow_folds(rows, seed):
    labels = {}
    for row in rows:
        label = int(row["label"]) if "label" in row else int(not row["is_authentic"])
        if labels.setdefault(row["id"], label) != label:
            raise ValueError(f"TamperFlow label varies across tiers: {row['id']}")
    folds = {}
    for label in (0, 1):
        groups = sorted(key for key, actual in labels.items() if actual == label)
        random.Random(f"{seed}:tamperflow:{label}").shuffle(groups)
        test, validation = round(len(groups) * .20), round(len(groups) * .15)
        for index, key in enumerate(groups):
            folds[key] = "test" if index < test else "validation" if index < test + validation else "train"
    return folds


def tamperflow_examples(root, rows, fold, folds):
    for row in rows:
        key, tier = row["id"], row["tier"]
        if tier not in TIERS or folds[key] != fold:
            continue
        path = root / row.get("file_name", row.get("image"))
        label = int(row["label"]) if "label" in row else int(not row["is_authentic"])
        # Published boxes are coarse. Use image labels and score pixel masks only on precise annotations.
        yield Example("tamperflow", f"{key}-{tier}", key, read_image(path), label, None, tier)


def doctamper_examples(partitions, fold, seed, limit, pilot=False):
    import lmdb

    for path in partitions:
        name = path.parent.name
        training = name.endswith("-TrainingSet")
        if not pilot and training == (fold == "test"):
            continue
        if pilot and not name.endswith("-FCD"):
            continue
        environment = lmdb.open(str(path.parent), readonly=True, lock=False, readahead=False, meminit=False)
        try:
            with environment.begin() as txn:
                size = int(txn.get(b"num-samples"))
                indices = range(size)
                if pilot:
                    indices = [index for index in indices if grouped_fold(f"{name}:{index}", seed) == fold]
                elif training:
                    indices = [index for index in indices if (index % 11 == 0) == (fold == "validation")]
                picks = random.Random(f"{seed}:{name}:{fold}").sample(indices, min(limit, len(indices))) if limit else indices
                for index in sorted(picks):
                    key = f"{index:09d}".encode()
                    image_data = txn.get(b"image-" + key)
                    mask_data = txn.get(b"label-" + key)
                    if not image_data or not mask_data:
                        continue
                    image = cv2.imdecode(np.frombuffer(image_data, dtype=np.uint8), cv2.IMREAD_COLOR)
                    mask = cv2.imdecode(np.frombuffer(mask_data, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
                    if image is None or mask is None:
                        continue
                    record = f"{name}-{index}"
                    yield Example("doctamper", record, record, image, int(bool(mask.any())), mask, name)
        finally:
            environment.close()


def prepare(args):
    cv2.setNumThreads(1)
    args.out.mkdir(parents=True, exist_ok=True)
    if (args.out / "manifest.jsonl").exists():
        raise ValueError("Use a fresh output directory for each prepared dataset.")
    paired_ai = bool(args.aiforge and (not args.pilot or any((args.aiforge / "TrainingSet/authentic").glob("*.png"))))
    aiforge = paired_aiforge(args.aiforge, args.seed) if paired_ai else {}
    tamperflow = []
    if args.tamperflow:
        root = args.tamperflow.resolve()
        for row in jsonl(root / "metadata.jsonl"):
            if row["tier"] not in TIERS:
                continue
            path = (root / row.get("file_name", row.get("image"))).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f"TamperFlow path escapes its source directory: {row['id']}")
            if path.is_file():
                tamperflow.append(row)
    tamper_folds = tamperflow_folds(tamperflow, args.seed)
    partitions = sorted(args.doctamper.rglob("data.mdb")) if args.doctamper else []
    if args.aiforge and not args.pilot and not aiforge["train"]:
        raise ValueError("AIForge requires the full package with authentic, images, and masks directories.")
    doc_partition = "-FCD" if args.pilot else "-TrainingSet"
    if args.doctamper and not any(path.parent.name.endswith(doc_partition) for path in partitions):
        raise ValueError(f"DocTamper requires the extracted {doc_partition[1:]} LMDB.")

    totals, sources, removed = Counter(), {}, Counter()
    seen, groups = {}, {}
    manifest = args.out / "manifest.jsonl.tmp"
    with manifest.open("w", encoding="utf-8", newline="\n") as stream:
        for fold in FOLDS:
            feeds = [
                (aiforge_pilot_examples(args.aiforge, fold, args.seed) if args.pilot and args.aiforge and not paired_ai
                 else aiforge_examples(aiforge.get(fold, []))),
                tamperflow_examples(args.tamperflow, tamperflow, fold, tamper_folds),
                doctamper_examples(partitions, fold, args.seed, {
                    "train": args.doctamper_train, "validation": args.doctamper_val,
                    "test": args.doctamper_test,
                }[fold], pilot=args.pilot) if partitions else (),
                synthetic_examples(args.synthetic, fold) if args.synthetic else (),
            ]
            for feed in feeds:
                for row in feed:
                    group = (row.source, row.group)
                    if groups.setdefault(group, fold) != fold:
                        raise ValueError(f"Source group crosses data splits: {group}")
                    image_hash = image_digest(row.image)
                    if image_hash in seen:
                        if seen[image_hash] != row.label:
                            raise ValueError(f"Identical image has conflicting labels: {row.source}/{row.key}")
                        removed[f"{row.source}_duplicate_images"] += 1
                        continue
                    if row.mask is not None and row.mask.shape != row.image.shape[:2]:
                        raise ValueError(f"Unaligned mask: {row.source}/{row.key}")
                    page, bounds = letterbox(row.image, args.size)
                    mask = np.zeros((args.size, args.size), np.uint8)
                    if row.mask is not None:
                        x, y, width, height = bounds
                        scaled = cv2.resize((row.mask > 0).astype(np.float32), (width, height), interpolation=cv2.INTER_AREA)
                        mask[y:y + height, x:x + width] = (scaled > 0).astype(np.uint8)
                        if bool(mask.any()) != bool(row.label):
                            raise ValueError(f"Label and mask disagree: {row.source}/{row.key}")
                    seen[image_hash] = row.label
                    stem = f"{row.source}-{row.key}.npz"
                    if Path(stem).name != stem or "/" in stem or "\\" in stem:
                        raise ValueError(f"Unexpected sample identifier: {row.key}")
                    np.savez_compressed(args.out / stem, image=page, mask=mask, bounds=np.asarray(bounds))
                    stream.write(json.dumps({
                        "id": row.key, "source": row.source, "group": row.group, "template": row.source,
                        "condition": row.condition, "category": "altered" if row.label else "genuine",
                        "split": fold, "label": row.label, "data": stem,
                        "mask_kind": "image" if row.mask is None else "pixel",
                        "original_image": row.original_image,
                    }) + "\n")
                    count = f"{fold}_{row.label}"
                    totals[count] += 1
                    sources.setdefault(row.source, Counter())[count] += 1
            print(f"{fold}: " + ", ".join(f"{source}={counts[fold + '_0'] + counts[fold + '_1']}"
                                        for source, counts in sources.items()), flush=True)
    for source, enabled in (("aiforge-v2", args.aiforge), ("tamperflow", args.tamperflow), ("doctamper", args.doctamper)):
        if enabled and not any(sources.get(source, {}).get(f"train_{label}", 0) for label in (0, 1)):
            raise ValueError(f"No training examples found for {source}")
    if not all(totals[f"{fold}_{label}"] for fold in ("train", "validation") for label in (0, 1)):
        raise ValueError("Training and validation each require genuine and altered images.")
    manifest.replace(args.out / "manifest.jsonl")
    summary = {"image_size": args.size, "counts": totals, "sources": sources, "removed": removed,
               "template_split": {key: list(value) for key, value in SPLITS.items()} if args.synthetic else {},
               "split_seed": args.seed,
               "pilot": args.pilot, "aiforge_paired": paired_ai,
               "limitations": "Experimental visual model. Training uses document edits and synthetic certificates. Scores are uncalibrated and depend on document type and image quality."}
    if args.pilot:
        summary["limitations"] += " This pilot uses a local re-split of DocTamper FCD."
        if args.aiforge and not paired_ai:
            summary["limitations"] += " Its AIForge subset contains only altered images."
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aiforge", type=Path)
    parser.add_argument("--tamperflow", type=Path)
    parser.add_argument("--doctamper", type=Path)
    parser.add_argument("--synthetic", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "datasets/mixed")
    parser.add_argument("--size", type=int, default=192)
    parser.add_argument("--seed", type=int, default=427)
    parser.add_argument("--doctamper-train", type=int, default=6000, help="Training patches, 0 for all")
    parser.add_argument("--doctamper-val", type=int, default=1000)
    parser.add_argument("--doctamper-test", type=int, default=400, help="Patches per official test partition")
    parser.add_argument("--pilot", action="store_true", help="Allow altered-only AIForge and a local re-split of DocTamper FCD for a separate pilot")
    args = parser.parse_args()
    if args.size < 64 or args.size % 4:
        parser.error("--size must be at least 64 and divisible by 4")
    prepare(args)
