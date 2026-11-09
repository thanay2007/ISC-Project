from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from threading import Lock

import cv2
import numpy as np
import pymupdf
from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 8
MAX_PIXELS = 22_000_000
MAX_SIDE = 1600
PDF_LOCK = Lock()


@dataclass
class Page:
    image: np.ndarray  # BGR
    text: list


def read_upload(file: UploadFile) -> bytes:
    data = file.file.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(413, "Upload a non-empty file of at most 10 MiB.")
    return data


def safe_name(name: str | None) -> str:
    name = PurePath((name or "document").replace("\\", "/")).name
    return "".join(c for c in name if c.isprintable())[:160] or "document"


def decode(data: bytes) -> tuple[str, list[Page]]:
    try:
        if data.startswith(b"%PDF-"):
            with PDF_LOCK, pymupdf.open(stream=data, filetype="pdf") as pdf:
                if pdf.needs_pass or not 1 <= pdf.page_count <= MAX_PAGES:
                    raise ValueError("Use an unlocked PDF of 1–8 pages.")
                pages = []
                for page in pdf:
                    rect = page.rect
                    if min(rect.width, rect.height) < 16:
                        raise ValueError("PDF page dimensions are invalid.")
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(MAX_SIDE / max(rect.width, rect.height), MAX_SIDE / max(rect.width, rect.height)),
                                          colorspace=pymupdf.csRGB, alpha=False, annots=False)
                    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                    # Only rendered text belongs in OCR fallback. OCR raster takes priority.
                    lines = []
                    for span in page.get_texttrace():
                        if span["type"] != 0 and span["type"] != 1 or span["opacity"] < .2:
                            continue
                        text = "".join(chr(c[0]) for c in span["chars"]
                                       if 0 < c[0] <= 0x10FFFF and not 0xD800 <= c[0] <= 0xDFFF).strip()
                        box = pymupdf.Rect(span["bbox"]) * page.rotation_matrix
                        if text and rect.intersects(box):
                            lines.append({"text": text[:1000], "confidence": None,
                                          "box": clamp_box(box, rect.width, rect.height)})
                        if len(lines) >= 250:
                            break
                    pages.append(Page(cv2.cvtColor(image, cv2.COLOR_RGB2BGR), lines))
                return "application/pdf", pages
        with Image.open(BytesIO(data)) as src:
            if src.format not in {"JPEG", "PNG"} or getattr(src, "n_frames", 1) != 1:
                raise ValueError("Use a single-frame PNG, JPEG, or PDF.")
            if src.width * src.height > MAX_PIXELS or min(src.size) < 16:
                raise ValueError("Image dimensions exceed the allowed limits.")
            mime = Image.MIME[src.format]
            image = ImageOps.exif_transpose(src)
            image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            if image.has_transparency_data:
                rgba = image.convert("RGBA")
                white = Image.new("RGBA", rgba.size, "white")
                image = Image.alpha_composite(white, rgba)
            return mime, [Page(cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR), [])]
    except (UnidentifiedImageError, OSError, RuntimeError, OverflowError, Image.DecompressionBombError) as exc:
        raise ValueError("The file could not be safely decoded as PDF, PNG, or JPEG.") from exc


def clamp_box(box, width, height):
    limits = (width, height, width, height)
    return [round(min(1, max(0, coord / limit)), 5) for coord, limit in zip(box, limits)]


def upload_document(file: UploadFile) -> tuple[bytes, str, list[Page]]:
    data = read_upload(file)
    try:
        mime, pages = decode(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return data, mime, pages


def png(image: np.ndarray) -> bytes:
    valid, buffer = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not valid:
        raise ValueError("Image encoding failed")
    return buffer.tobytes()
