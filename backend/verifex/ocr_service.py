import csv
import io
import logging
import os
import re
import shutil
import subprocess
from threading import Lock, Thread

import cv2
import numpy as np

from .documents import Page, clamp_box, png

LOG = logging.getLogger(__name__)
FIELD_PATTERNS = {
    "student_name": r"(?:student(?: name)?|name)",
    "institution_name": r"(?:institution(?: name)?|university|college)",
    "certificate_id": r"(?:certificate\s*(?:id|no\.?|number))",
    "roll_number": r"(?:roll\s*(?:no\.?|number))",
    "course": r"(?:course|program(?:me)?)",
    "grade": r"(?:grade|result)",
    "marks": r"(?:marks|score)",
    "issue_date": r"(?:issue(?:d)? date|date of issue|date)",
    "signatory": r"(?:signatory|signed by)",
    "account_number": r"(?:account|customer|consumer)\s*(?:no\.?|number|id)",
    "document_number": r"(?:bill|invoice|receipt|statement|document)\s*(?:no\.?|number|id|#)",
    "provider": r"(?:service provider|supplier|vendor|merchant|billed by|issued by)",
    "customer_name": r"(?:customer name|account holder|bill(?:ed)? to|recipient)",
    "billing_period": r"(?:billing period|statement period|service period)",
    "due_date": r"(?:due date|payment due date|pay by)",
    "amount_due": r"(?:total amount due|amount due|balance due|total due|amount payable|total amount|grand total|total)",
    "service_address": r"(?:service address|billing address|delivery address|address)",
}
ALIASES = {
    "grade": "Grade", "marks": "Marks", "student_name": "Student name",
    "institution_name": "Institution", "certificate_id": "Certificate ID",
    "roll_number": "Roll number", "course": "Course", "issue_date": "Issue date",
    "signatory": "Signatory",
    "account_number": "Account number", "document_number": "Document number", "provider": "Provider",
    "customer_name": "Customer name", "billing_period": "Billing period", "due_date": "Due date",
    "amount_due": "Amount due", "service_address": "Service address",
}


class OCR:
    def __init__(self, engine="auto", tesseract=""):
        self.engine = engine
        self.tesseract = tesseract or shutil.which("tesseract")
        self.lock = Lock()
        self.paddle = None
        self.unavailable = False
        self.warming = False

    def preload(self):
        if self.engine in {"paddle", "auto"}:
            self.warming = True
            Thread(target=self.warm, name="verifex-ocr-warmup", daemon=True).start()

    def warm(self):
        if self.engine not in {"paddle", "auto"}:
            return
        with self.lock:
            if self.paddle is not None or self.unavailable:
                return
            try:
                os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
                from paddleocr import PaddleOCR
                self.paddle = PaddleOCR(device="cpu", enable_mkldnn=False, cpu_threads=3,
                                        use_doc_orientation_classify=False, use_doc_unwarping=False,
                                        use_textline_orientation=False,
                                        text_detection_model_name="PP-OCRv5_mobile_det",
                                        text_recognition_model_name="en_PP-OCRv5_mobile_rec")
            except Exception:
                self.unavailable = True
                LOG.warning("PaddleOCR startup failed", exc_info=True)
            finally:
                self.warming = False

    def extract(self, page: Page) -> tuple[list, str, list]:
        warnings = []
        if self.engine in {"paddle", "auto"}:
            if self.paddle is None and not (self.warming and page.text):
                self.warm()
            if self.paddle is not None:
                try:
                    lines = self._paddle_lines(page.image)
                    if not self._readable(lines):
                        try:
                            enhanced = self._paddle_lines(self._enhance_scan(page.image))
                            lines = max((lines, enhanced), key=self._readability)
                        except Exception:
                            LOG.warning("PaddleOCR enhanced pass failed", exc_info=True)
                            warnings.append("Enhanced scan OCR was unavailable.")
                    if lines and (not page.text or self._readable(lines)):
                        return lines, "PaddleOCR", warnings
                    warnings.append("PaddleOCR found limited readable text.")
                except Exception:
                    LOG.warning("PaddleOCR inference failed", exc_info=True)
                    warnings.append("PaddleOCR inference failed.")
            else:
                warnings.append("PaddleOCR is warming up." if self.warming else "PaddleOCR is unavailable.")
        if self.engine in {"auto", "tesseract", "paddle"} and self.tesseract:
            try:
                if lines := self._tesseract(page.image):
                    return lines, "Tesseract", warnings
                warnings.append("Tesseract found no readable text.")
            except (OSError, subprocess.SubprocessError, ValueError, KeyError):
                warnings.append("Tesseract is unavailable or timed out.")
        if page.text:
            return page.text, "PDF text layer", warnings
        return [], "No text engine result", warnings + ["No text was extracted from this page."]

    @staticmethod
    def _readability(lines):
        return sum(sum(char.isalnum() for char in line["text"]) * line["confidence"] ** 2 for line in lines)

    def _readable(self, lines):
        return self._readability(lines) >= 20 and np.median([line["confidence"] for line in lines]) >= .7

    @staticmethod
    def _enhance_scan(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
        corrected = cv2.divide(gray, np.maximum(background, 1), scale=255)
        return cv2.cvtColor(cv2.createCLAHE(2., (8, 8)).apply(corrected), cv2.COLOR_GRAY2BGR)

    def _paddle_lines(self, image):
        with self.lock:
            result = next(iter(self.paddle.predict(image)))
        height, width = image.shape[:2]
        lines = []
        for text, score, polygon in zip(result["rec_texts"], result["rec_scores"], result["rec_polys"]):
            if score < .45 or not str(text).strip():
                continue
            xy = np.asarray(polygon)
            lines.append({"text": str(text).strip()[:1000], "confidence": round(float(score), 3),
                          "box": clamp_box([*xy.min(axis=0), *xy.max(axis=0)], width, height)})
        return lines[:250]

    def _tesseract(self, image):
        result = subprocess.run([self.tesseract, "stdin", "stdout", "--psm", "11", "tsv"],
                                input=png(image), capture_output=True, check=True, timeout=15,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        grouped = {}
        for row in csv.DictReader(io.StringIO(result.stdout.decode("utf-8", errors="replace")), delimiter="\t"):
            if row["level"] != "5" or not row["text"].strip():
                continue
            group = tuple(row[key] for key in ("block_num", "par_num", "line_num"))
            grouped.setdefault(group, []).append(row)
        height, width = image.shape[:2]
        lines = []
        for words in grouped.values():
            x, y, w, h = (np.array([int(row[key]) for row in words]) for key in ("left", "top", "width", "height"))
            lines.append({"text": " ".join(row["text"] for row in words)[:1000],
                          "confidence": round(float(np.mean([float(row["conf"]) for row in words])) / 100, 3),
                          "box": clamp_box((x.min(), y.min(), (x+w).max(), (y+h).max()), width, height)})
        return lines[:250]


def fields_for(lines):
    fields = {}
    ordered = sorted(lines, key=lambda line: (line["page"], line["box"][1], line["box"][0]))
    for line in ordered:
        for field, pattern in FIELD_PATTERNS.items():
            match = re.match(rf"^\s*{pattern}(?!\w)\s*[:#–-]?\s*(.*)$", line["text"], flags=re.IGNORECASE)
            if not match or field in fields:
                continue
            value = match[1].strip()
            if re.fullmatch(r"\(\s*in (?:block|capital) letters\s*\)", value, re.IGNORECASE):
                value = ""
            box = line["box"]
            if not value:
                candidates = [other for other in ordered if other["page"] == line["page"]
                              and other["box"][0] >= box[2] - .005 and abs(other["box"][1] - box[1]) < .02]
                if candidates:
                    neighbor = min(candidates, key=lambda other: other["box"][0])
                    value = neighbor["text"].strip()
                    box = [box[0], min(box[1], neighbor["box"][1]), neighbor["box"][2], max(box[3], neighbor["box"][3])]
            if value:
                fields[field] = {"value": value, "page": line["page"], "box": box}
    return fields


def normalized_field(value):
    return " ".join(value.casefold().split()) if value else ""


def compare_fields(original, uploaded):
    differences = []
    for name in FIELD_PATTERNS:
        before, after = original.get(name), uploaded.get(name)
        a, b = (field["value"] if field else None for field in (before, after))
        if normalized_field(a) != normalized_field(b):
            differences.append({"field": name, "label": ALIASES[name], "original": a, "uploaded": b,
                                "kind": "changed" if a and b else "missing_or_unreadable",
                                "page": after["page"] if after else None, "box": after["box"] if after else None})
    return differences


def field_agreement(fields, gemini):
    if not gemini:
        return {}
    extracted = gemini.get("extracted_fields", {})
    return {name: normalized_field(field["value"]) == normalized_field(extracted[name])
            for name, field in fields.items() if extracted.get(name)}
