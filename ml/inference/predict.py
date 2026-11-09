import argparse
import json
from pathlib import Path

from backend.verifex.config import ROOT
from backend.app.services.custom_forgery_model import CustomForgeryModel
from backend.verifex.documents import decode, png

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the deployed detector on a PNG, JPEG, or PDF")
    parser.add_argument("document", type=Path)
    parser.add_argument("--model", type=Path, default=ROOT / "ml/models")
    parser.add_argument("--out", type=Path, help="Write per-page heatmaps and masks")
    args = parser.parse_args()
    model = CustomForgeryModel(args.model, ROOT / "ml/results")
    _, pages = decode(args.document.read_bytes())
    result, layers = model.infer(pages)
    print(json.dumps(result, indent=2))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        for index, page in enumerate(layers, start=1):
            for name, image in page.items():
                (args.out / f"{index}-{name}.png").write_bytes(png(image))
    if result["status"] != "complete":
        raise SystemExit(1)
