"""Deterministic comparison of the seven fields between the SI (reference)
and the draft BL.  Values are normalised so that formatting differences do not
raise false alarms, while real differences (another company, another port,
±1 container, a different weight) are reported with both values.
"""
from __future__ import annotations

import re
from typing import Optional

from .extract import parse_container_count, parse_weight_kg, valid_value
from .schemas import FIELDS, FIELD_LABELS, FieldRow, FieldValue

def _upper_ascii(s: str) -> str:
    s = s.upper()
    s = re.sub(r"[^\x00-\x7f]+", " ", s)
    return s


def norm_party(value: Optional[str]) -> str:
    if not value:
        return ""
    v = _upper_ascii(value)
    v = v.replace("&", " AND ")
    v = re.sub(r"[.,;:'\"()\[\]/\\-]", " ", v)
    v = re.sub(r"\s+", " ", v).strip()
    return v


def _party_core(v: str) -> str:
    # Expand equivalent abbreviations without discarding legal identity.
    aliases = {"LIMITED": "LTD", "COMPANY": "CO", "CORPORATION": "CORP", "INCORPORATED": "INC"}
    return " ".join(aliases.get(token, token) for token in v.split())


def parties_equal(a: Optional[str], b: Optional[str]) -> tuple[bool, str]:
    na, nb = norm_party(a), norm_party(b)
    if not na or not nb:
        return False, "value missing"
    if na == nb:
        return True, "names match"
    ca, cb = _party_core(na), _party_core(nb)
    if ca == cb:
        return True, "names match (legal suffix differs only)"
    return False, "different party"


def norm_port(value: Optional[str]) -> str:
    if not value:
        return ""
    v = _upper_ascii(value)
    v = re.sub(r"\([^)]*\)", " ", v)           # drop (WESTPORT) / (MYPKG) decorations
    v = v.split(",")[0]                         # drop country
    v = re.sub(r"\bPORT OF\b", " ", v)
    v = re.sub(r"[^A-Z0-9/ ]", " ", v)
    v = re.sub(r"\s+", " ", v).strip()
    return v


def port_code(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    m = re.search(r"\(([A-Z]{5})\)\s*$", value.strip().upper())
    return m.group(1) if m else None


def ports_equal(a: Optional[str], b: Optional[str]) -> tuple[bool, str]:
    na, nb = norm_port(a), norm_port(b)
    if not na or not nb:
        return False, "value missing"
    if na == nb:
        return True, "port names match"
    sa, sb = na.replace(" ", ""), nb.replace(" ", "")
    if sa == sb:
        return True, "port names match (spacing differs only)"
    ca, cb = port_code(a), port_code(b)
    if ca and cb and ca == cb and len(sa) >= 5 and len(sb) >= 5 and (sa in sb or sb in sa):
        return True, "same port (same UN/LOCODE, one name is more specific)"
    return False, "different port"


def count_equal(a: Optional[str], b: Optional[str]) -> tuple[Optional[bool], str, Optional[int], Optional[int]]:
    ia = parse_container_count(a) if a else None
    ib = parse_container_count(b) if b else None
    if ia is None or ib is None:
        return None, "value missing or not a number", ia, ib
    if ia == ib:
        return True, "container counts match", ia, ib
    return False, f"container count differs: SI {ia} / BL {ib}", ia, ib


def weight_equal(a: Optional[str], b: Optional[str], tolerance_kg: float = 0.000001) -> tuple[Optional[bool], str, Optional[float], Optional[float]]:
    wa = parse_weight_kg(a) if a else None
    wb = parse_weight_kg(b) if b else None
    if wa is None or wb is None:
        return None, "value missing or not a number", wa, wb
    if abs(wa - wb) <= tolerance_kg:
        return True, "gross weights match", wa, wb
    return False, f"gross weight differs: SI {_fmt_num(wa)} kg / BL {_fmt_num(wb)} kg", wa, wb


def _fmt_num(x: float) -> str:
    return f"{int(x):,}" if float(x).is_integer() else f"{x:,.2f}"


def display_value(field: str, fv: Optional[FieldValue]) -> Optional[str]:
    if fv is None or fv.value is None:
        return None
    if field == "gross_weight_kg":
        w = parse_weight_kg(fv.value)
        return f"{_fmt_num(w)} kg" if w is not None else fv.value
    return fv.value


def compare_fields(si: dict[str, FieldValue], bl: dict[str, FieldValue]) -> tuple[list[FieldRow], list[str]]:
    """Returns (rows, defect_fields). Fields missing on either side get
    match=None and are NOT counted as defects (they are a review reason)."""
    rows: list[FieldRow] = []
    defects: list[str] = []
    for fld in FIELDS:
        s, b = si.get(fld), bl.get(fld)
        sv = s.value if s else None
        bv = b.value if b else None
        row = FieldRow(field=fld, label=FIELD_LABELS[fld], si_value=display_value(fld, s),
                       bl_value=display_value(fld, b), si_evidence=s.evidence if s else None,
                       bl_evidence=b.evidence if b else None)
        if not valid_value(fld, sv) or not valid_value(fld, bv):
            row.match = None
            invalid = [side for side, value in (("SI", sv), ("draft BL", bv)) if not valid_value(fld, value)]
            row.reason = "missing or invalid in " + " and ".join(invalid)
            rows.append(row)
            continue
        if fld in ("shipper", "consignee", "notify_party"):
            ok, why = parties_equal(sv, bv)
        elif fld in ("port_of_loading", "port_of_discharge"):
            ok, why = ports_equal(sv, bv)
        elif fld == "container_count":
            ok, why, _, _ = count_equal(sv, bv)
        else:
            ok, why, _, _ = weight_equal(sv, bv)
        row.match = ok
        row.reason = why if ok else (why if fld in ("container_count", "gross_weight_kg") else f"{why}: SI '{sv}' vs BL '{bv}'")
        if ok is False:
            defects.append(fld)
        rows.append(row)
    return rows, defects
