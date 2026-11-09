import argparse
import json
import random
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = 20
FIELDS = ("Student", "Institution", "Certificate ID", "Roll Number", "Course", "Grade", "Marks", "Issue Date")
PALETTES = [("#182b52", "#d9ab56"), ("#1c4844", "#6d9f88"), ("#45273a", "#bc8367"), ("#253246", "#698fb7")]
CHANGES = ("grade", "marks", "name", "number", "date", "copy_move", "erase", "local_blur", "local_compression", "scan_patch")


def font(size: int, family: int, bold=False):
    names = (("DejaVuSans", "arial"), ("DejaVuSerif", "times"), ("DejaVuSansMono", "cour"))
    linux, windows = names[family]
    suffix = ("-Bold" if bold else "") + ".ttf"
    for path in (linux + suffix, str(Path("C:/Windows/Fonts") / (windows + ("bd" if bold else "") + ".ttf"))):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def certificate(index: int, rng: random.Random):
    template = index % TEMPLATES
    palette = PALETTES[template % len(PALETTES)]
    portrait = template in {3, 8, 13, 15, 18, 19}
    width, height = rng.choice([(640, 470), (704, 500), (768, 540)])
    if portrait:
        width, height = height, width
    tint = np.array(rng.choice([(243, 237, 219), (233, 241, 240), (248, 241, 235), (237, 239, 248)]))
    yy, xx = np.indices((height, width), dtype=np.float32)
    grain = (2 * np.cos(xx / rng.uniform(10, 45) + yy / 45) + 2 * np.sin(yy / 30)).astype(np.int16)
    paper = np.clip(tint + grain[:, :, None], 0, 255).astype(np.uint8)
    img = Image.fromarray(paper)
    draw = ImageDraw.Draw(img)
    border = 13 + template % 4 * 4
    draw.rectangle((border, border, width - border, height - border), outline=palette[0], width=2)
    if template % 3:
        draw.rectangle((border + 6, border + 6, width - border - 6, height - border - 6), outline=palette[1], width=2)
    if template % 5 < 2:
        draw.rectangle((border + 8, border + 8, width - border - 8, int(height * .17)), fill=palette[0])
        heading_color = "white"
    else:
        heading_color = palette[0]
    family = template % 3
    draw.text((width // 2, int(height * .113)), "CERTIFICATE OF MERIT",
              font=font(int(width * .045), family, True), anchor="mm", fill=heading_color)
    draw.text((width // 2, int(height * .216)), "FICTIONAL ACADEMIC RECORD  /  VERIFEX LAB",
              font=font(max(10, int(width * .023)), 0), anchor="mm", fill=palette[0])
    values = [
        f"{rng.choice(['Arlen','Tavi','Nima','Corin','Sela','Riven','Vela','Orin'])} {rng.choice(['Cloudfell','Fernstrand','Quillridge','Stonereef','Asterwell','Briarhollow'])}",
        f"{rng.choice(['Quillspire','Valewing','Noravelle','Alderwake','Thistlefrost'])} Fictional Institute",
        f"VX-{index:05d}-{rng.randrange(100, 999)}", f"R-{rng.randrange(10000, 99999)}",
        rng.choice(["Digital Forensics", "Applied Cryptography", "Network Studies", "Computer Vision"]),
        rng.choice(["B", "B", "C", "A", "B+"]), str(rng.randrange(61, 77)),
        f"20{rng.randrange(18, 27)}-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}",
    ]
    positions = []
    text_size = rng.randrange(18, 24)
    body_font = font(text_size, family)
    centered = template % 4 == 2
    for row, (label, value) in enumerate(zip(FIELDS, values)):
        y = int(height * (.29 + row * .063))
        x = border + rng.randrange(25, 34)
        if centered:
            x = max(x, (width - int(draw.textlength(f"{label}: {value}", font=body_font))) // 2)
        draw.text((x, y), label + ": ", fill=palette[0], font=body_font, anchor="lt")
        x += int(draw.textlength(label + ": ", font=body_font))
        positions.append((x, y))
        draw.text((x, y), value, fill=palette[0], font=body_font, anchor="lt")
    cx, cy = int(width * .81), int(height * .86)
    radius = int(height * .053)
    for r in (radius, radius - 5):
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=palette[1], width=2)
    draw.text((cx, cy), "VX", fill=palette[0], font=font(15, family, True), anchor="mm")
    x0 = int(width * .21)
    draw.line([(x0 + i * 7, cy + rng.randrange(-12, 11)) for i in range(12)], fill=palette[0], width=2)
    draw.text((x0 + 38, cy + 24), "Synthetic seal and signature", fill=palette[0], font=font(11, 0), anchor="mm")

    category = CHANGES[(index // TEMPLATES + template * 3) % len(CHANGES)]
    fields = {"grade": 5, "marks": 6, "name": 0, "number": 2, "date": 7}
    row = fields.get(category, rng.randrange(len(FIELDS)))
    changed = {
        "grade": "A+", "marks": "95", "name": "Zuri Mossfield",
        "number": f"VX-{rng.randrange(10000, 99999)}", "date": "2030-10-23",
        "copy_move": values[(row + 1) % len(FIELDS)], "erase": "",
    }.get(category, values[row])
    x, y = positions[row]
    patch_width = min(width - x - border - 10, max(50, int(draw.textlength(max((changed, values[row]), key=len), font=body_font)) + 9))
    region = (x - 2, y - 4, x + patch_width, y + text_size + 3)
    forged = img.copy()
    if category == "copy_move":
        sx, sy = positions[(row + 1) % len(FIELDS)]
        forged.paste(img.crop((sx - 2, sy - 4, sx + patch_width, sy + text_size + 3)), region[:2])
    elif category in {"local_blur", "local_compression", "scan_patch"}:
        patch = np.array(img.crop(region))
        if category == "local_blur":
            patch = cv2.GaussianBlur(patch, (5, 5), rng.uniform(0.8, 1.6))
        elif category == "local_compression":
            patch = jpeg(patch, rng.randrange(22, 65))
        else:
            patch = np.clip(patch.astype(np.int16) + rng.choice([-11, -7, 7, 12]), 0, 255).astype(np.uint8)
        forged.paste(Image.fromarray(patch), region[:2])
    else:
        patch = paper[region[1]:region[3], region[0]:region[2]].astype(np.int16)
        patch = np.clip(patch + rng.choice([-13, -8, -4, 0, 4, 7, 12]), 0, 255).astype(np.uint8)
        forged.paste(Image.fromarray(patch), region[:2])
        ImageDraw.Draw(forged).text((x + rng.choice([-1, 0, 2]), y + rng.choice([-2, 0, 1])), changed,
                                    fill=palette[0], font=font(text_size + rng.choice([-2, 0, 0, 1]), rng.choice([family, family, (family + 1) % 3])), anchor="lt")
    a, b = np.array(img), np.array(forged)
    mask = (np.any(a != b, axis=2) * 255).astype(np.uint8)
    condition = ("clean", "compressed", "scan", "low_resolution")[(index // TEMPLATES + template) % 4]
    if condition == "compressed":
        quality = rng.randrange(37, 86)
        a, b = jpeg(a, quality), jpeg(b, quality)
    elif condition == "scan":
        source = np.float32([[0, 0], [width - 1, 0], [0, height - 1], [width - 1, height - 1]])
        target = source + np.float32([[rng.randrange(-9, 10), rng.randrange(-9, 10)] for _ in range(4)])
        warp = cv2.getPerspectiveTransform(source, target)
        noise = np.random.default_rng(index).normal(0, 2.5, (height, width, 1))
        def scan(page):
            warped = cv2.warpPerspective(page, warp, (width, height), borderMode=cv2.BORDER_REPLICATE)
            return np.clip(cv2.GaussianBlur(warped, (3, 3), .55) + noise, 0, 255).astype(np.uint8)
        a, b = scan(a), scan(b)
        mask = cv2.warpPerspective(mask, warp, (width, height), flags=cv2.INTER_NEAREST)
    elif condition == "low_resolution":
        dimensions = (width // 2, height // 2)
        a = cv2.resize(a, dimensions, interpolation=cv2.INTER_AREA)
        b = cv2.resize(b, dimensions, interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask, dimensions, interpolation=cv2.INTER_NEAREST)
    return a, b, mask, {
        "id": f"synth-{index:05d}", "source": "verifex-synthetic", "template": f"T{template:02d}",
        "condition": condition, "category": category, "field": FIELDS[row],
        "before": values[row], "after": changed, "fields": dict(zip(FIELDS, values)),
    }


def jpeg(data, quality):
    ok, encoded = cv2.imencode(".jpg", data, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def generate(out: Path, pairs: int, seed: int):
    for directory in ("original", "tampered", "masks"):
        (out / directory).mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    with (out / "manifest.jsonl").open("w", encoding="utf-8") as manifest:
        for index in range(pairs):
            original, tampered, mask, row = certificate(index, rng)
            for key, folder, data in (("original", "original", original), ("tampered", "tampered", tampered), ("mask", "masks", mask)):
                row[key] = f"{folder}/{row['id']}.png"
                stream = BytesIO()
                Image.fromarray(data).save(stream, format="PNG", compress_level=1)
                (out / row[key]).write_bytes(stream.getvalue())
            manifest.write(json.dumps(row) + "\n")
    print(f"Generated {pairs} original/tampered pairs with aligned masks in {out}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "datasets/synthetic")
    parser.add_argument("--pairs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=427)
    args = parser.parse_args()
    if args.pairs < 20:
        parser.error("Generate at least 20 pairs for template coverage")
    generate(args.out, args.pairs, args.seed)
