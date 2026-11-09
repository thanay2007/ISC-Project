import argparse
import json
import random
import shutil
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATASET = "kriyam-ai/kriyam-tamperflow"
REVISION = "281155b75f62ea0db538dcff38d06109be58e912"
TIERS = ("C0", "C2", "C4")
BASE = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/"


def fetch(client, path, destination):
    if destination.is_file() and destination.stat().st_size:
        return True
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".part")
    url = BASE + quote(path, safe="/") + "?download=true"
    curl = shutil.which("curl")
    if curl:
        # The platform build can use native certificate and proxy settings.
        run = subprocess.run([curl, "--fail", "--silent", "--location", "--max-time", "18",
                              "--write-out", "%{http_code}", "--output", str(temp), url],
                             capture_output=True, text=True)
        if run.returncode == 0:
            temp.replace(destination)
            return True
        temp.unlink(missing_ok=True)
        if run.stdout in {"403", "404"}:
            return False
    try:
        with client.stream("GET", url) as response:
            if response.status_code in {403, 404}:
                return False
            response.raise_for_status()
            with temp.open("wb") as stream:
                for chunk in response.iter_bytes():
                    stream.write(chunk)
        temp.replace(destination)
        return True
    except (httpx.TransportError, httpx.HTTPStatusError):
        temp.unlink(missing_ok=True)
        return False


def download(args):
    root = args.out
    manifest = root / "metadata.jsonl"
    with httpx.Client(follow_redirects=True, timeout=12) as client:
        if not fetch(client, "metadata.jsonl", manifest):
            raise RuntimeError("The published metadata could not be fetched.")
        rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
        classes = Counter(f"{row['tier']}_{'genuine' if row['is_authentic'] else 'altered'}" for row in rows)
        print(f"Published inventory: {dict(classes)}", flush=True)
        rng = random.Random(args.seed)
        lookup = {(row["id"], row["tier"]): row for row in rows}
        selected, unavailable = [], []

        def save(doc_id):
            verified = []
            for tier in args.tiers:
                row = lookup.get((doc_id, tier))
                if not row:
                    return []
                path = row["file_name"]
                if not path.startswith("images/") or ".." in path:
                    raise ValueError("Unexpected image path in dataset metadata")
                if not fetch(client, path, root / path):
                    return []
                try:
                    with Image.open(root / path) as image:
                        if image.size != (row["image_w"], row["image_h"]):
                            return []
                        image.verify()
                except (OSError, ValueError):
                    return []
                verified.append({"id": doc_id, "source": DATASET, "revision": REVISION, "image": path,
                                 "label": int(not row["is_authentic"]), "tier": tier})
            if args.annotations:
                annotation = f"annotations/{doc_id}.json"
                if not fetch(client, annotation, root / annotation):
                    return []
            return verified

        with ThreadPoolExecutor(max_workers=8) as executor:
            for authentic in (True, False):
                ids = sorted({row["id"] for row in rows if row["is_authentic"] is authentic and row["tier"] == "C0"})
                rng.shuffle(ids)
                target = min(args.per_class, len(ids)) if args.per_class else len(ids)
                accepted = 0
                for start in range(0, len(ids), 8):
                    if accepted >= target:
                        break
                    batch = ids[start:start+8]
                    for doc_id, verified in zip(batch, executor.map(save, batch)):
                        if not verified:
                            unavailable.append(doc_id)
                        elif accepted < target:
                            accepted += 1
                            selected.extend(verified)
                print(f"Verified {accepted} of {target} requested {'genuine' if authentic else 'altered'} source groups", flush=True)
    (root / "manifest.jsonl").write_text("".join(json.dumps(row) + "\n" for row in selected), encoding="utf-8")
    counts = Counter(f"{row['tier']}_{row['label']}" for row in selected)
    (root / "summary.json").write_text(json.dumps({
        "published": classes, "evaluated_candidates": counts, "source": DATASET, "revision": REVISION,
        "requested_per_class": args.per_class, "tiers": args.tiers, "unavailable": unavailable, "seed": args.seed,
    }, indent=2))
    print(f"Verified {len(selected)} selected images: {dict(counts)}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download a non-commercial TamperFlow evaluation sample.")
    parser.add_argument("--accept-noncommercial", action="store_true", help="Confirm CC BY-NC 4.0 use and attribution.")
    parser.add_argument("--out", type=Path, default=ROOT / "datasets/raw/tamperflow")
    parser.add_argument("--per-class", type=int, default=12, help="Unique IDs per class; use 0 for all available files.")
    parser.add_argument("--seed", type=int, default=427)
    parser.add_argument("--tiers", nargs="+", choices=TIERS, default=TIERS)
    parser.add_argument("--annotations", action="store_true", help="Also fetch official polygon annotation files.")
    args = parser.parse_args()
    if not args.accept_noncommercial or args.per_class < 0:
        parser.error("Read the dataset terms and pass --accept-noncommercial with a nonnegative sample size.")
    download(args)
