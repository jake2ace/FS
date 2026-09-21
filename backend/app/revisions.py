"""Create native-format BL copies. Never mutate the participant input files.

Edits require one unambiguous labelled source value. Unsupported/ambiguous
layouts fail visibly; the caller routes them to human review.
"""
from __future__ import annotations

import io
import re
import hashlib
from pathlib import Path
from uuid import uuid4

from .extract import field_for_label, split_label_value, parse_weight_kg
from .parsers import parse_attachment
from .schemas import CaseResult, FIELD_LABELS
from .workflow import now, pair_fields


def replacement(field: str, raw: str, value: str) -> str:
    if field == "container_count":
        if not re.fullmatch(r"\d+\s*[xX×*].*", raw):
            return value
        return re.sub(r"^\d+", value, raw)
    if field == "gross_weight_kg":
        # Keep the existing unit. A unit in a header is handled by the caller.
        n = parse_weight_kg(value)
        if n is None:
            raise ValueError("SI weight is not valid")
        if re.search(r"\b(?:MT|MTS|TONS?|TONNES?)\b", raw, re.I):
            n /= 1000
        elif re.search(r"\b(?:LB|LBS|POUNDS?)\b", raw, re.I):
            n /= 0.45359237
        number = f"{n:,.3f}".rstrip('0').rstrip('.') if ',' in raw else f"{n:.3f}".rstrip('0').rstrip('.')
        return re.sub(r"\d[\d,.]*", lambda _: number, raw, count=1)
    # Preserve address material outside the compared party name.
    if field in ("shipper", "consignee", "notify_party"):
        sep = re.search(r" \| |;|\n", raw)
        return value + raw[sep.start():] if sep else value
    return value


def _replace_runs(paragraph, old: str, new: str) -> None:
    text = paragraph.text
    if text.count(old) != 1:
        raise ValueError("Cannot safely locate the value in the Word paragraph")
    start, end = text.index(old), text.index(old) + len(old)
    offset = 0
    inserted = False
    for run in paragraph.runs:
        original = run.text
        left, right = max(start - offset, 0), min(end - offset, len(original))
        if left < right:
            run.text = original[:left] + (new if not inserted else "") + original[right:]
            inserted = True
        offset += len(original)
    if not inserted:
        raise ValueError("Word value uses unsupported text elements")


def _edit_text(data: bytes, changes: dict) -> bytes:
    text = data.decode('utf-8')
    counts = {f: 0 for f in changes}
    lines = []
    for line in text.splitlines(keepends=True):
        lv = split_label_value(line.rstrip('\r\n'))
        fld = field_for_label(lv[0]) if lv else None
        if fld in changes:
            raw = lv[1]
            new = replacement(fld, raw, changes[fld])
            pos = line.find(raw, len(lv[0]))
            if pos < 0 or not raw:
                raise ValueError("Cannot locate the original TXT value")
            line = line[:pos] + new + line[pos + len(raw):]
            counts[fld] += 1
        lines.append(line)
    _unique(counts)
    return ''.join(lines).encode('utf-8')


def _unique(counts: dict) -> None:
    bad = [FIELD_LABELS[f] for f, n in counts.items() if n != 1]
    if bad:
        raise ValueError("Cannot safely locate exactly one value for: " + ', '.join(bad))


def _edit_docx(data: bytes, changes: dict) -> bytes:
    from docx import Document
    doc = Document(io.BytesIO(data))
    counts = {f: 0 for f in changes}
    for paragraph in doc.paragraphs:
        lv = split_label_value(paragraph.text)
        fld = field_for_label(lv[0]) if lv else None
        if fld in changes and lv[1]:
            _replace_runs(paragraph, lv[1], replacement(fld, lv[1], changes[fld]))
            counts[fld] += 1
    for table in doc.tables:
        for row in table.rows:
            cells = list(row.cells)
            if len(cells) < 2:
                continue
            fld = field_for_label(cells[0].text)
            if fld not in changes:
                continue
            cell = cells[1]
            paragraph = next((p for p in cell.paragraphs if p.text.strip()), None)
            if paragraph is None:
                raise ValueError("Word value cell is empty")
            raw = paragraph.text
            _replace_runs(paragraph, raw, replacement(fld, raw, changes[fld]))
            counts[fld] += 1
    _unique(counts)
    out = io.BytesIO(); doc.save(out)
    return out.getvalue()


def _edit_xlsx(data: bytes, changes: dict) -> bytes:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data))
    counts = {f: 0 for f in changes}
    for ws in wb:
        for row in ws:
            for i, cell in enumerate(row[:-1]):
                if not isinstance(cell.value, str):
                    continue
                fld = field_for_label(cell.value)
                if fld not in changes:
                    continue
                target = row[i + 1]
                if target.data_type == 'f' or target.value is None:
                    raise ValueError("Cannot safely modify an empty or formula cell")
                raw = str(target.value)
                new = replacement(fld, raw, changes[fld])
                target.value = float(new) if isinstance(target.value, (int, float)) else new
                counts[fld] += 1
    _unique(counts)
    out = io.BytesIO(); wb.save(out)
    return out.getvalue()


def _edit_pdf(data: bytes, changes: dict, bl_doc) -> bytes:
    import pymupdf as fitz
    doc = fitz.open(stream=data, filetype='pdf')
    edits = []
    for fld, value in changes.items():
        fv = bl_doc.fields[fld]
        if not fv.label:
            raise ValueError("PDF label cannot be located safely")
        # Parser evidence includes a source line; use the original printed value.
        lv = split_label_value((fv.evidence or '').split(' / ')[0])
        raw = lv[1] if lv else fv.value
        if not raw:
            raise ValueError("PDF value has no source text")
        candidates = []
        for page in doc:
            labels = page.search_for(fv.label)
            for rect in page.search_for(raw):
                if any(abs(label.y0 - rect.y0) < 6 and rect.x0 >= label.x0 for label in labels):
                    candidates.append((page.number, rect))
        if len(candidates) != 1:
            raise ValueError(f"Cannot safely locate {FIELD_LABELS[fld]} in the PDF layout")
        page_number, rect = candidates[0]
        page = doc[page_number]
        spans = [span for block in page.get_text('dict')['blocks'] if 'lines' in block
                 for line in block['lines'] for span in line['spans'] if fitz.Rect(span['bbox']).intersects(rect)]
        spans = [span for span in spans if raw in span['text']]
        if len(spans) != 1 or spans[0]['text'].strip() != raw.strip():
            raise ValueError("PDF value shares a text span with other content")
        span = spans[0]
        family = span['font'].lower()
        font = 'hebo' if 'bold' in family and 'helvetica' in family else 'helv' if 'helvetica' in family else 'tiro' if 'times' in family and 'bold' not in family else 'cour' if 'courier' in family and 'bold' not in family else None
        if font is None or any(ord(c) > 127 for c in value):
            raise ValueError("PDF font cannot be preserved safely")
        new = replacement(fld, raw, value)
        width = fitz.get_text_length(new, fontname=font, fontsize=span['size'])
        target = fitz.Rect(rect.x0, rect.y0, rect.x0 + max(width, rect.width), rect.y1)
        if target.x1 > page.rect.x1 - 10:
            raise ValueError("Replacement text does not fit the PDF page")
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines', []):
                for other in line['spans']:
                    if other != span and fitz.Rect(other['bbox']).intersects(target):
                        raise ValueError("Replacement text would overlap other PDF content")
        edits.append((page_number, rect, span, new, font))
    for page in doc:
        selected = [e for e in edits if e[0] == page.number]
        for _, rect, _, _, _ in selected:
            page.add_redact_annot(rect, fill=(1, 1, 1), cross_out=False)
        if selected:
            page.apply_redactions(images=0, graphics=0)
        for _, rect, span, new, font in selected:
            color = tuple(((span['color'] >> shift) & 255) / 255 for shift in (16, 8, 0))
            page.insert_text((rect.x0, span['origin'][1]), new, fontname=font, fontsize=span['size'], color=color)
    return doc.tobytes(garbage=4, deflate=True)


async def build_revision(result: CaseResult, inbox, cache_dir: Path, analyser, policy="standard") -> dict:
    if result.status != 'MISMATCH' or result.resolved:
        raise ValueError('A verified, unresolved mismatch is required to generate a corrected BL.')
    si, bl = pair_fields(result)
    if len(result.fields) != 7 or any(r.match is None for r in result.fields):
        raise ValueError('All seven fields must have been reliably compared.')
    bl_doc = next(d for d in result.docs if d.detected_type == 'BL')
    changes = {f: si[f].value for f in result.defect_fields}
    data = inbox.read_bytes(bl_doc.path)
    if bl_doc.format == 'pdf':
        revised = _edit_pdf(data, changes, bl_doc)
    else:
        editor = {'txt': _edit_text, 'docx': _edit_docx, 'xlsx': _edit_xlsx}.get(bl_doc.format)
        if not editor:
            raise ValueError('This file format cannot be modified safely; ask a person to correct the BL.')
        revised = editor(data, changes)
    check = await analyser.recheck_copy(result, revised, inbox, policy)
    rows = check.fields
    if check.status != 'OK' or check.decision_method != 'ai' or not all(r.match is True for r in rows):
        raise ValueError('AI could not confirm the generated BL; no copy was saved. ' + check.explanation)
    revision_id = uuid4().hex
    name = f"{Path(bl_doc.filename).stem}-revised{Path(bl_doc.filename).suffix}"
    target_dir = cache_dir / 'revisions' / result.email_id / revision_id
    target_dir.mkdir(parents=True, exist_ok=False)
    try:
        (target_dir / name).write_bytes(revised)
    except Exception:
        import shutil
        shutil.rmtree(target_dir)
        raise
    return {'revision_id': revision_id, 'kind': 'corrected_bl', 'created_at': now(), 'status': 'OK',
            'review_reason': None, 'fields': [r.model_dump() for r in rows],
            'changes': [{'field': f, 'side': 'BL', 'before': bl[f].value, 'after': si[f].value,
                         'evidence': si[f].evidence} for f in changes],
            'note': 'Correct the AI-identified BL discrepancies to the SI; AI seven-field recheck passed.',
            'decision_method': check.decision_method, 'ai_model': check.ai_model,
            'filename': name, 'file_available': True, 'sha256': hashlib.sha256(revised).hexdigest(), 'docs': [], 'decision': None}


async def validate_revision(cache_dir: Path, result: CaseResult, report: dict, analyser, inbox, policy="standard") -> None:
    path = revision_path(cache_dir, result.email_id, report)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != report.get('sha256'):
        raise ValueError('The corrected file is missing or changed; it cannot be adopted. Reject it and generate a new copy.')
    # AI already checked this exact file before it was offered for adoption.
    # The person's approval is final; only verify that the reviewed bytes are unchanged.


def revision_path(cache_dir: Path, email_id: str, report: dict) -> Path:
    path = (cache_dir / 'revisions' / email_id / report['revision_id'] / report['filename']).resolve()
    if not path.is_relative_to((cache_dir / 'revisions').resolve()):
        raise ValueError('Invalid revision path')
    return path


def delete_revision(cache_dir: Path, email_id: str, report: dict) -> None:
    if report.get('kind') != 'corrected_bl' or not report.get('file_available'):
        return
    path = revision_path(cache_dir, email_id, report)
    path.unlink(missing_ok=True)
    if path.parent.exists():
        path.parent.rmdir()
    report['file_available'] = False
    report['deleted_at'] = now()
