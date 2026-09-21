"""Map internal case results to the official submission shape
(sample_submission.json): one object per email_id with
category / status / review_reason / defect_fields / has_defect.
"""
from __future__ import annotations

from typing import Optional

from .schemas import CaseResult, SubmissionEntry


def to_entry(res: CaseResult) -> SubmissionEntry:
    if res.category is None:
        raise ValueError('A person must classify this email before export.')
    if res.category != "BL_COMPARISON":
        return SubmissionEntry(category=res.category, status="OK", review_reason=None, defect_fields=[], has_defect=False)
    if res.status == "MISMATCH":
        return SubmissionEntry(category=res.category, status="MISMATCH", review_reason=None,
                               defect_fields=list(res.defect_fields), has_defect=True)
    if res.status == "NEEDS_REVIEW":
        return SubmissionEntry(category=res.category, status="NEEDS_REVIEW", review_reason=res.review_reason,
                               defect_fields=[], has_defect=False)
    return SubmissionEntry(category=res.category, status="OK", review_reason=None, defect_fields=[], has_defect=False)


def build_submission(email_ids: list[str], results: dict[str, CaseResult]) -> tuple[dict, list[str]]:
    """Returns (submission, missing_ids). Every email_id is present; emails
    that were never analysed fall back to the sample default (GENERAL / OK)."""
    out: dict[str, dict] = {}
    missing: list[str] = []
    for eid in email_ids:
        r: Optional[CaseResult] = results.get(eid)
        if r is None or r.category is None:
            missing.append(eid)
            entry = SubmissionEntry(category="GENERAL", status="OK", review_reason=None, defect_fields=[], has_defect=False)
        else:
            entry = to_entry(r)
        d = entry.model_dump()
        # keep the exact key order of sample_submission.json
        out[eid] = {
            "category": d["category"],
            "status": d["status"],
            "review_reason": d["review_reason"],
            "defect_fields": d["defect_fields"],
            "has_defect": d["has_defect"],
        }
    return out, missing
