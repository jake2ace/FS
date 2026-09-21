"""Deterministic (rule based) extraction of the seven shipment fields from a
parsed document.  Works on the label/value lines produced by parsers.py.

Labels are aligned by meaning, not by exact text: "Port of Loading (POL)",
"Load Port" and "POL" all map to port_of_loading.  Values that are blank or
placeholders ("???", "____", "TBA", "N/A") are reported as missing, never
guessed.
"""
from __future__ import annotations

import re
import math
from typing import Optional

from .parsers import ParsedDoc
from .schemas import FIELDS, FieldValue

# (field, regex on the normalised label).  Order matters: "Notify Party /
# Intermediate Consignee" must resolve to notify_party, not consignee.
LABEL_RULES: list[tuple[str, re.Pattern]] = [
    ("notify_party", re.compile(r"\bnotify\b")),
    ("consignee", re.compile(r"\bconsignee\b|\bto the order of\b|\border of\b")),
    ("shipper", re.compile(r"\bshipper\b|\bexporter\b|\bprincipal or seller\b")),
    ("port_of_loading", re.compile(r"\bport of loading\b|\bloading port\b|\bload port\b|\bpol\b")),
    ("port_of_discharge", re.compile(r"\bport of discharge\b|\bdischarge port\b|\bdischarging port\b|\bpod\b|\bport of destination\b|\bdestination port\b")),
    ("container_count", re.compile(r"\bno\.? of containers?\b|\bnumber of containers?\b|\btotal containers?\b|\bcontainer count\b|\bcontainers? or packages\b|\bno\.? of cntrs?\b|\bqty of containers?\b|\bcontainer qty\b")),
    ("gross_weight_kg", re.compile(r"\bgross\s*w(?:eigh)?t\b|\bgross weight\b|\bg\.?w\.?\b|\btotal gross\b")),
]
# labels that look like our fields but are not
NEGATIVE_LABEL = re.compile(r"\bnet\s*w(?:eigh)?t\b|\bnet weight\b|\bb/?l\b|\bbill of lading no\b|\bbooking\b|\bvessel\b|\bvoyage\b|\bhs code\b|\bdescription\b|\bcommodity\b|\bfreight\b|\bplace of\b")

# label prefixes for lines that have no colon (typical of PDF text)
PDF_LABEL_PREFIX = re.compile(
    r"^\s*(?P<label>"
    r"notify party(?:/intermediate consignee)?|notify|"
    r"consignee(?: \(non-negotiable\))?|to the order of|"
    r"shipper(?:/exporter| \(principal or seller\))?|exporter|"
    r"port of loading(?: \(pol\))?|loading port|load port|pol|"
    r"port of discharge(?: \(pod\))?|discharge port|discharging port|pod|"
    r"(?:total )?no\. of containers(?: or packages)?|total containers|container count|number of containers|"
    r"(?:total )?gross w(?:eigh)?t(?:\s*\((?:kgs?|kilos?)\))?|(?:total )?gross weight(?:\s*\((?:kgs?)\))?"
    r")\s*[:：]?\s+(?P<value>\S.*)$",
    re.IGNORECASE,
)

PLACEHOLDER = re.compile(r"^[\s_\-–—?*.]*(?:mt|mts|kg|kgs|n/?a|na|tba|tbd|tbc|nil|none|null|pending)?[\s_\-–—?*.]*$", re.IGNORECASE)
CONTAINER_NO = re.compile(r"^[A-Z]{4}\s?\d{7}\b")


def normalise_label(label: str) -> str:
    s = label.lower()
    s = re.sub(r"[^\x00-\x7f]+", " ", s)      # drop CJK / non-ascii decorations
    s = s.replace("_", " ")
    s = re.sub(r"[()\[\]{}]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" :：-")
    return s


def field_for_label(label: str) -> Optional[str]:
    norm = normalise_label(label)
    if not norm or len(norm) > 60:
        return None
    if NEGATIVE_LABEL.search(norm) and not re.search(r"gross", norm):
        return None
    for fld, rx in LABEL_RULES:
        if rx.search(norm):
            return fld
    return None


def is_placeholder(value: Optional[str]) -> bool:
    if value is None:
        return True
    v = value.strip()
    if not v:
        return True
    return bool(PLACEHOLDER.match(v))


def split_label_value(line: str) -> Optional[tuple[str, str]]:
    """Return (label, value) for 'Label: value' or PDF style 'Label value'."""
    if not line or not line.strip():
        return None
    if line.startswith((" ", "\t")):
        return None  # continuation / address line
    m = re.match(r"^\s*([^:：]{2,70}?)\s*[:：]\s*(.*)$", line)
    if m:
        label, value = m.group(1), m.group(2)
        # avoid treating 'http://' or times like '12:30' as label/value
        if re.search(r"https?$", label.strip(), re.IGNORECASE) or re.fullmatch(r"\d{1,2}", label.strip()):
            return None
        return label.strip(), value.strip()
    m = PDF_LABEL_PREFIX.match(line)
    if m:
        return m.group("label").strip(), m.group("value").strip()
    return None


def parse_container_count(value: str) -> Optional[int]:
    if value is None:
        return None
    v = value.strip()
    # A count or explicit sum of container groups; never take the first number
    # of an ambiguous string (e.g. "3 or 4", "3.5", or a container ID).
    plain = re.fullmatch(r"(\d{1,4})\s*(?:containers?|cntrs?|units?|boxes|x)?", v, re.IGNORECASE)
    if plain:
        return int(plain.group(1))
    groups = re.split(r"\s*\+\s*", v)
    total = 0
    for group in groups:
        m = re.fullmatch(r"(\d{1,4})\s*[xX×*]\s*(?:20|40|45)\s*['’\"]?\s*(?:HC|HQ|GP|DC|FT|FCL)?", group, re.IGNORECASE)
        if not m:
            return None
        total += int(m.group(1))
    return total


def parse_weight_kg(value: str) -> Optional[float]:
    if value is None:
        return None
    v = value.strip().upper()
    m = re.fullmatch(r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(KG|KGS|KILOGRAMS?|MT|MTS|METRIC TONS?|METRIC TONNES?|TONS?|TONNES?|LB|LBS|POUNDS?)?(?::\s*[A-Z]+)?", v)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    unit = m.group(2) or "KG"
    if unit in ("MT", "MTS") or "TON" in unit:
        num *= 1000.0
    elif unit in ("LB", "LBS", "POUND", "POUNDS"):
        num *= 0.45359237
    return num if math.isfinite(num) else None


def clean_party(value: str) -> str:
    """Keep the party NAME only: text before the first ' | ' / ';' separator."""
    v = value.strip()
    for sep in (" | ", ";", "\n"):
        if sep in v:
            v = v.split(sep, 1)[0].strip()
    return v


def clean_port(value: str) -> str:
    v = value.strip()
    if " | " in v:
        v = v.split(" | ", 1)[0].strip()
    return v


def extract_fields(doc: ParsedDoc) -> dict[str, FieldValue]:
    """Return {field: FieldValue}. Missing fields are present with value=None
    when a label was found but blank, and absent when no label matched."""
    found: dict[str, FieldValue] = {}
    lines = doc.lines
    last_field: Optional[str] = None
    for idx, raw in enumerate(lines):
        line = raw.rstrip()
        lv = split_label_value(line)
        if lv is None:
            # continuation line: keep as evidence for the previous party field
            if last_field in ("shipper", "consignee", "notify_party") and line.strip() and last_field in found:
                fv = found[last_field]
                if fv.evidence and len(fv.evidence) < 300:
                    fv.evidence = fv.evidence + " / " + line.strip()
            continue
        label, value = lv
        fld = field_for_label(label)
        if fld is None:
            last_field = None
            continue
        # a later line rarely overrides an earlier one, except TOTAL rows for weight
        if fld in found and found[fld].value is not None:
            if fld == "gross_weight_kg" and re.search(r"total", normalise_label(label)):
                pass  # TOTAL line wins over per-container rows
            else:
                last_field = fld
                continue
        last_field = fld
        if is_placeholder(value):
            found[fld] = FieldValue(value=None, evidence=line.strip(), label=label, source="rules")
            continue
        if fld in ("shipper", "consignee", "notify_party"):
            val = clean_party(value)
        elif fld in ("port_of_loading", "port_of_discharge"):
            val = clean_port(value)
        elif fld == "container_count":
            n = parse_container_count(value)
            val = str(n) if n is not None else None
        elif fld == "gross_weight_kg":
            unit = re.search(r"\((KG|KGS|MT|MTS|LB|LBS)\)", label, re.IGNORECASE)
            weight_text = value + " " + unit.group(1) if unit and re.fullmatch(r"[\d,.]+", value) else value
            w = parse_weight_kg(weight_text)
            val = (str(int(w)) if w is not None and float(w).is_integer() else (str(w) if w is not None else None))
        else:
            val = value
        if val is None or is_placeholder(val):
            found[fld] = FieldValue(value=None, evidence=line.strip(), label=label, source="rules")
        else:
            found[fld] = FieldValue(value=val, evidence=line.strip(), label=label, source="rules")

    # container count fallback: count container-number rows in a table
    if "container_count" not in found or found["container_count"].value is None:
        rows = [l for l in lines if CONTAINER_NO.match(l.strip())]
        if rows and ("container_count" not in found):
            found["container_count"] = FieldValue(value=str(len(rows)), evidence=f"{len(rows)} container rows listed",
                                                  label="container table", source="rules")
    return found


def missing_fields(fields: dict[str, FieldValue]) -> list[str]:
    return [f for f in FIELDS if f not in fields or not valid_value(f, fields[f].value)]


def valid_value(field: str, value: Optional[str]) -> bool:
    if is_placeholder(value):
        return False
    if field == "container_count":
        n = parse_container_count(value)
        return n is not None and n > 0
    if field == "gross_weight_kg":
        n = parse_weight_kg(value)
        return n is not None and math.isfinite(n) and n > 0
    return bool(value and any(c.isalnum() for c in value))
