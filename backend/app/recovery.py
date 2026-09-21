"""Local attachment recovery. Missing/wrong documents never enter this path."""
from __future__ import annotations

import csv
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from .parsers import ParsedDoc, detect_doc_type


def recover_document(doc: ParsedDoc, data: bytes) -> ParsedDoc:
    if doc.readable or not data or doc.fmt not in {"pdf", "png", "jpg", "jpeg", "tif", "tiff"}:
        return doc
    doc.recovery = "attempted"
    # Try a second PDF reader before OCR (some layouts defeat the first reader).
    if doc.fmt == "pdf":
        try:
            from pypdf import PdfReader
            pages = PdfReader(io.BytesIO(data)).pages
            if len(pages) > 10:
                raise ValueError("recovery is limited to 10 pages")
            text = "\n".join(p.extract_text() or "" for p in pages)
            if text.strip():
                return _recovered(doc, text, "pdf-reparse", 1.0)
        except Exception:
            pass
    tesseract, renderer = shutil.which("tesseract"), shutil.which("pdftoppm")
    if not tesseract or (doc.fmt == "pdf" and not renderer):
        doc.recovery = "unavailable: install tesseract and poppler on the backend"
        return doc
    try:
        with tempfile.TemporaryDirectory(prefix="freightsentinel-ocr-") as tmp:
            src = Path(tmp) / ("source." + doc.fmt)
            src.write_bytes(data)
            images = [src]
            if doc.fmt == "pdf":
                from pypdf import PdfReader
                if len(PdfReader(io.BytesIO(data)).pages) > 10:
                    raise ValueError("OCR is limited to 10 pages")
                subprocess.run([renderer, "-r", "180", "-png", str(src), str(Path(tmp) / "page")],
                               check=True, capture_output=True, timeout=30)
                images = sorted(Path(tmp).glob("page-*.png"))
            texts, confidences = [], []
            for image in images:
                out = subprocess.run([tesseract, str(image), "stdout", "-l", "eng", "--psm", "6", "tsv"],
                                     check=True, capture_output=True, text=True, timeout=20)
                lines: dict[tuple, list[str]] = {}
                for row in csv.DictReader(io.StringIO(out.stdout), delimiter="\t"):
                    word = (row.get("text") or "").strip()
                    if not word:
                        continue
                    conf = float(row["conf"])
                    if conf >= 0:
                        confidences.append(conf / 100)
                    key = tuple(row[k] for k in ("page_num", "block_num", "par_num", "line_num"))
                    lines.setdefault(key, []).append(word)
                texts.append("\n".join(" ".join(words) for words in lines.values()))
            confidence = sum(confidences) / len(confidences) if confidences else 0.0
            if not confidences or confidence < 0.85 or min(confidences) < 0.5:
                doc.recovery = "failed: OCR reading is uncertain"
                return doc
            return _recovered(doc, "\n".join(texts), "ocr", confidence)
    except Exception:  # malformed documents and OCR failures remain visible review cases
        doc.recovery = "failed: OCR or PDF recovery could not complete; retry with a readable document"
        return doc


def _recovered(doc: ParsedDoc, text: str, method: str, confidence: float) -> ParsedDoc:
    doc.text = text
    doc.lines = text.splitlines()
    doc.detected_type = detect_doc_type(doc.lines, doc.filename)
    doc.readable = bool(text.strip())
    doc.error = None if doc.readable else doc.error
    doc.recovery = method
    doc.recovery_confidence = confidence
    return doc
