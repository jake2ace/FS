"""Review reports are separate from the detection on original attachments."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .schemas import CaseResult, FIELDS, FieldValue


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pair_fields(result: CaseResult) -> tuple[dict, dict]:
    si = [d for d in result.docs if d.detected_type == "SI" and d.readable]
    bl = [d for d in result.docs if d.detected_type == "BL" and d.readable]
    if len(si) != 1 or len(bl) != 1:
        raise ValueError("Provide one readable, identified SI and one draft BL before editing field readings.")
    return ({k: v.model_copy(deep=True) for k, v in si[0].fields.items()},
            {k: v.model_copy(deep=True) for k, v in bl[0].fields.items()})


async def human_report(result: CaseResult, values: dict, note: str, analyser, policy="standard") -> dict:
    if result.category != "BL_COMPARISON":
        raise ValueError("This email is not a BL comparison request.")
    if not note.strip():
        raise ValueError("Record why these readings were confirmed or corrected.")
    si, bl = pair_fields(result)
    changes = []
    # Require an explicit full review, so seven defaults cannot silently stand in for confirmation.
    if set(values) != set(FIELDS):
        raise ValueError("Confirm all seven SI and BL field readings.")
    for field in FIELDS:
        raw = values[field]
        if not isinstance(raw, dict) or set(raw) != {"si_value", "bl_value"}:
            raise ValueError("Each field needs si_value and bl_value.")
        for side, dest in (("si", si), ("bl", bl)):
            value = raw[side + "_value"]
            if value is not None and (not isinstance(value, str) or len(value) > 500):
                raise ValueError("Field values must be text up to 500 characters.")
            value = value.strip() if value else None
            old = dest.get(field)
            if old is None or old.value != value:
                changes.append({"field": field, "side": side.upper(), "before": old.value if old else None, "after": value})
            dest[field] = FieldValue(value=value, evidence=(old.evidence if old and old.evidence else "Human reading: " + note), source="human")
    from .parsers import ParsedDoc
    # The reviewer's readings are explicit new input, not silently substituted source evidence.
    docs = []
    for role, fields in (("SI", si), ("BL", bl)):
        text = ("SHIPPING INSTRUCTION" if role=="SI" else "DRAFT BILL OF LADING") + "\n"
        text += "\n".join(f"{field}: {fields[field].value if fields[field].value is not None else 'MISSING'}" for field in FIELDS)
        docs.append(ParsedDoc(path=f'human-{role}.txt', filename=f'human-{role}.txt', fmt='txt', size=len(text), readable=True, text=text))
    email = dict(email_id=result.email_id, subject='Compare human-confirmed SI and BL field readings',
                 body='These values were explicitly reviewed by a human. Compare them and identify uncertainty.', attachments=[d.path for d in docs])
    check = await analyser.judge(email, docs, policy=policy)
    report = attachment_report(check, note)
    report.update(kind='human_reading', changes=changes, docs=[d.model_dump() for d in result.docs],
                  reviewed_readings=values)
    return report



def attachment_report(result: CaseResult, note: str) -> dict:
    return {"revision_id": uuid4().hex, "kind": "replacement_attachments", "created_at": now(),
            "status": result.status, "review_reason": result.review_reason, "fields": [r.model_dump() for r in result.fields],
            "changes": [], "note": note, "docs": [d.model_dump() for d in result.docs],
            "explanation": result.explanation, "warnings": result.warnings, "decision": None,
            "decision_method": result.decision_method, "ai_model": result.ai_model}

