import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

from ml.model import tensor_image


def rows_for(folder, split):
    with (folder / "manifest.jsonl").open(encoding="utf-8") as stream:
        return [row for line in stream if (row := json.loads(line))["split"] == split]


class Pages(Dataset):
    def __init__(self, folder, rows, augment=False, classification_sources=None):
        self.folder = folder
        self.rows = rows
        self.augment = augment
        self.classification_sources = classification_sources

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        rng = random
        if isinstance(index, tuple):
            index, seed = index
            rng = random.Random(seed)
        row = self.rows[index]
        with np.load(self.folder / row["data"], allow_pickle=False) as file:
            image, mask = file["image"], file["mask"]
        if self.augment:
            if rng.random() < .5:
                size = image.shape[0]
                warp = cv2.getRotationMatrix2D((size / 2, size / 2), rng.uniform(-3, 3), 1)
                image = cv2.warpAffine(image, warp, (size, size), borderMode=cv2.BORDER_REPLICATE)
                mask = cv2.warpAffine(mask, warp, (size, size), flags=cv2.INTER_NEAREST)
            if rng.random() < .6:
                image = np.clip(image.astype(np.float32) * rng.uniform(.9, 1.1) +
                                rng.uniform(-9, 9), 0, 255).astype(np.uint8)
            if rng.random() < .16:
                image = cv2.GaussianBlur(image, (3, 3), .55)
            if rng.random() < .16:
                ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, rng.randrange(55, 92)])
                if ok:
                    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        target = (mask > 0).astype(np.float32)
        if row.get("mask_kind") == "image":
            target.fill(-1)
        label = row["label"]
        if self.classification_sources is not None and row["source"] not in self.classification_sources:
            label = -1
        return tensor_image(image), torch.from_numpy(target)[None], torch.tensor(label).float()


def options(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path(".verifex/balanced-training"))
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch", type=int, default=24)
    parser.add_argument("--lr", type=float, default=.002)
    parser.add_argument("--threads", type=int, default=5)
    parser.add_argument("--seed", type=int, default=427)
    parser.add_argument("--patience", type=int, default=5)
    return parser


def setup(args):
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    cv2.setNumThreads(1)
    torch.use_deterministic_algorithms(True, warn_only=True)
    args.out.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Training on {device}", flush=True)
    return device
