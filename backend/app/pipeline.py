"""The end-to-end analysis of one email:

    classify -> load attachments -> identify SI / BL -> extract 7 fields
    -> compare -> decide OK / MISMATCH / NEEDS_REVIEW -> explain

AI is used for understanding (classification, document reading); deterministic
code owns the comparison and the safety rules, so every outcome is
reproducible and explainable.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

from .ai import AIClient
from .classify import classify_rules
from .compare import compare_fields, norm_party, norm_port
from .data import Inbox
from .extract import extract_fields, missing_fields, parse_container_count, parse_weight_kg
from .parsers import (DOC_BL, DOC_CI, DOC_COO, DOC_PL, DOC_SI, DOC_TYPE_LABELS, DOC_UNKNOWN, ParsedDoc,
                      parse_attachment)
from .schemas import FIELDS, FIELD_LABELS, CaseResult, DocInfo, FieldRow, FieldValue

CATEGORY_LABELS = {
    "BL_COMPARISON": "BL comparison request",
    "SI_REQUEST": "New SI request",
    "INVOICE_QUERY": "Invoice query",
    "GENERAL": "General / operational notice",
    "SPAM": "Spam",
}
CATEGORY_ACTIONS = {
    "SI_REQUEST": "Route to the documentation team to prepare or file the shipping instruction. No BL comparison required.",
    "INVOICE_QUERY": "Route to billing / finance. No BL comparison required.",
    "GENERAL": "No document action required. Keep for reference.",
    "SPAM": "Ignore. Do not open links or attachments.",
}
REVIEW_LABELS = {
    "missing_attachment": "Missing attachment",
    "wrong_doc_type": "Wrong document type",
    "unreadable": "Unreadable document",
    "missing_value": "Missing value in the documents",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _values_agree(field: str, a: Optional[str], b: Optional[str]) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if field in ("shipper", "consignee", "notify_party"):
        return norm_party(a) == norm_party(b)
    if field in ("port_of_loading", "port_of_discharge"):
        return norm_port(a) == norm_port(b)
    if field == "container_count":
        return parse_container_count(a) == parse_container_count(b)
    wa, wb = parse_weight_kg(a), parse_weight_kg(b)
    return wa is not None and wb is not None and abs(wa - wb) <= 1.0


def _doc_info(doc: ParsedDoc, fields: dict[str, FieldValue], method: str) -> DocInfo:
    return DocInfo(
        path=doc.path, filename=doc.filename, format=doc.fmt, role_hint=doc.role_hint,
        detected_type=doc.detected_type, readable=doc.readable, read_error=doc.error,
        size_bytes=doc.size, text_chars=len(doc.text), text_preview=doc.text[:2500],
        fields=fields, extraction_method=method,
    )


class Analyser:
    def __init__(self, inbox: Inbox, ai: AIClient):
        self.inbox = inbox
        self.ai = ai

    # ------------------------------------------------------------------ main
    async def analyse(self, email: dict, policy: str = "standard", explain_with_ai: bool = False) -> CaseResult:
        res = await self._analyse(email, policy=policy)
        if explain_with_ai and res.category == "BL_COMPARISON":
            try:
                res = await self.polish_with_ai(res)
            except Exception as exc:  # explanation polish must never break a result
                res.warnings.append(f"AI explanation unavailable: {type(exc).__name__}")
        return res

    async def _analyse(self, email: dict, policy: str = "standard") -> CaseResult:
        t0 = time.perf_counter()
        warnings: list[str] = []
        ai_used = False

        # 1. classification --------------------------------------------------
        rules = classify_rules(email)
        category, cat_conf, cat_reason, intent, method = rules.category, rules.confidence, rules.reason, rules.intent, "rules"
        if self.ai.enabled and (self.ai.mode == "full" or rules.confidence < 0.8):
            ai_cls = await self.ai.classify_email(email)
            if ai_cls:
                ai_used = True
                if ai_cls["category"] == rules.category:
                    cat_conf = round(min(0.99, max(rules.confidence, ai_cls["confidence"]) + 0.05), 2)
                    cat_reason = ai_cls["reason"] or cat_reason
                    method = "ai+rules"
                else:
                    # the model reads the whole body; rules only see keywords. Prefer the model
                    # unless it is clearly unsure and the rules are confident.
                    if ai_cls["confidence"] >= 0.6 or rules.confidence < 0.7:
                        warnings.append(f"Rule engine suggested {rules.category} ({rules.confidence:.2f}); AI chose {ai_cls['category']} ({ai_cls['confidence']:.2f}).")
                        category, cat_conf, cat_reason, method = ai_cls["category"], round(min(ai_cls["confidence"], 0.85), 2), ai_cls["reason"], "ai"
                    else:
                        warnings.append(f"AI suggested {ai_cls['category']} ({ai_cls['confidence']:.2f}) but rules kept {rules.category}.")
                        cat_conf = round(min(cat_conf, 0.75), 2)
                        method = "rules"
                if category == "BL_COMPARISON":
                    intent = ai_cls["intent"] if ai_cls["intent"] != "other" else (rules.intent if rules.category == "BL_COMPARISON" else "other")
            else:
                warnings.append("AI classification unavailable; rule-based classification used.")

        base = dict(
            email_id=email["email_id"], subject=email.get("subject", ""), sender=email.get("from", ""),
            attachments=list(email.get("attachments") or []), category=category, category_confidence=cat_conf,
            category_reason=cat_reason, category_method=method, intent=intent, analysed_at=_now(),
        )

        # 2. non-comparison categories ------------------------------------------
        if category != "BL_COMPARISON":
            res = CaseResult(
                **base, status="OK", has_defect=False, defect_fields=[], ui_status="No action", risk="none",
                headline=CATEGORY_LABELS[category],
                explanation=f"Classified as {CATEGORY_LABELS[category].lower()} ({cat_reason}). No shipping-document comparison is required for this email.",
                suggested_action=CATEGORY_ACTIONS.get(category, "No action required."),
                confidence=cat_conf, evidence_available=True, automation="none", ai_used=ai_used, warnings=warnings,
            )
            res.duration_ms = int((time.perf_counter() - t0) * 1000)
            return res

        # 3. attachments ------------------------------------------------------
        docs: list[ParsedDoc] = []
        for path in email.get("attachments") or []:
            try:
                data = await asyncio.to_thread(self.inbox.read_bytes, path)
            except FileNotFoundError:
                docs.append(ParsedDoc(path=path, filename=path.rsplit("/", 1)[-1], fmt="missing", size=0,
                                      readable=False, error="attachment file not found in the bundle"))
                continue
            docs.append(await asyncio.to_thread(parse_attachment, path, data))

        if not docs:
            if intent == "request_draft":
                res = CaseResult(
                    **base, status="OK", has_defect=False, defect_fields=[], ui_status="Awaiting draft BL", risk="none",
                    headline="Draft BL requested - nothing to compare yet",
                    explanation="The sender asks for the draft Bill of Lading to be sent for checking. No documents are attached, so there is nothing to compare at this stage.",
                    suggested_action="Send the draft BL to the requester; the comparison runs once both documents are on file.",
                    confidence=cat_conf, evidence_available=True, automation="none", ai_used=ai_used, warnings=warnings,
                )
            else:
                res = CaseResult(
                    **base, status="NEEDS_REVIEW", review_reason="missing_attachment",
                    review_detail="The email asks for the SI and draft BL to be compared, but no attachment was received.",
                    has_defect=False, defect_fields=[], ui_status="Needs review", risk="medium",
                    headline="Needs review - missing attachment",
                    explanation="This is a comparison request, but the email carries no attachments, so the SI and draft BL cannot be checked.",
                    suggested_action="Ask the sender to resend the SI and the draft BL.",
                    confidence=cat_conf, evidence_available=True, automation="review_required", ai_used=ai_used, warnings=warnings,
                )
            res.duration_ms = int((time.perf_counter() - t0) * 1000)
            return res

        # 4. extraction (rules first, AI to confirm / fill) --------------------
        doc_fields: list[dict[str, FieldValue]] = []
        methods: list[str] = []
        disagreements = 0
        ai_filled = 0
        for doc in docs:
            if not doc.readable:
                doc_fields.append({})
                methods.append("none")
                continue
            fields = extract_fields(doc)
            method = "rules"
            need_ai = self.ai.enabled and (self.ai.mode == "full" or missing_fields(fields) or doc.detected_type == DOC_UNKNOWN or doc.fmt != "txt")
            if need_ai:
                ai_ex = await self.ai.extract_document(doc.text, doc.filename)
                if ai_ex:
                    ai_used = True
                    method = "ai+rules"
                    if doc.detected_type == DOC_UNKNOWN and ai_ex["doc_type"] != DOC_UNKNOWN:
                        doc.detected_type = ai_ex["doc_type"]
                    for fld in FIELDS:
                        rv = fields.get(fld)
                        av = ai_ex["fields"].get(fld, {})
                        if (rv is None or rv.value is None) and av.get("value"):
                            fields[fld] = FieldValue(value=av["value"], evidence=av.get("evidence"), label="(AI)", source="ai")
                            ai_filled += 1
                        elif rv is not None and rv.value is not None and av.get("value") and not _values_agree(fld, rv.value, av["value"]):
                            disagreements += 1
                            warnings.append(f"{doc.filename}: rules read {FIELD_LABELS[fld]} as '{rv.value}', AI read '{av['value']}'. Rule value kept.")
                else:
                    warnings.append(f"AI extraction unavailable for {doc.filename}; rule-based extraction used.")
            doc_fields.append(fields)
            methods.append(method)

        doc_infos = [_doc_info(d, f, m) for d, f, m in zip(docs, doc_fields, methods)]

        # 5. readability / document roles -------------------------------------
        unreadable = [d for d in docs if not d.readable]
        if unreadable:
            names = "; ".join(f"{d.filename}: {d.error}" for d in unreadable)
            return self._finish(base, t0, docs=doc_infos, status="NEEDS_REVIEW", reason="unreadable",
                                detail=f"Could not read {names}.", headline="Needs review - document cannot be read",
                                explanation=f"One or more attachments could not be read ({names}). The comparison cannot be made from unreadable input.",
                                action="Request a readable copy of the affected document (text-based PDF, DOCX, XLSX or TXT).",
                                confidence=cat_conf, ai_used=ai_used, warnings=warnings, policy=policy)

        si_idx = next((i for i, d in enumerate(docs) if d.detected_type == DOC_SI), None)
        bl_idx = next((i for i, d in enumerate(docs) if d.detected_type == DOC_BL), None)
        # fall back to filename hints for unknown documents
        if si_idx is None:
            si_idx = next((i for i, d in enumerate(docs) if d.detected_type == DOC_UNKNOWN and d.role_hint == DOC_SI), None)
        if bl_idx is None:
            bl_idx = next((i for i, d in enumerate(docs) if d.detected_type == DOC_UNKNOWN and d.role_hint == DOC_BL and i != si_idx), None)

        wrong = [d for i, d in enumerate(docs) if d.detected_type in (DOC_CI, DOC_PL, DOC_COO)]
        if si_idx is None or bl_idx is None:
            if wrong:
                w = wrong[0]
                missing_role = "draft BL" if bl_idx is None else "SI"
                return self._finish(base, t0, docs=doc_infos, status="NEEDS_REVIEW", reason="wrong_doc_type",
                                    detail=f"{w.filename} is a {DOC_TYPE_LABELS[w.detected_type]}, not the {missing_role}.",
                                    headline="Needs review - wrong document attached",
                                    explanation=f"The attachment {w.filename} is a {DOC_TYPE_LABELS[w.detected_type].lower()}, so the {missing_role} needed for the comparison is not on file.",
                                    action=f"Ask the sender for the correct {missing_role}.",
                                    confidence=cat_conf, ai_used=ai_used, warnings=warnings, policy=policy)
            missing_role = "draft BL" if bl_idx is None else "SI"
            have = ", ".join(f"{d.filename} ({DOC_TYPE_LABELS.get(d.detected_type, d.detected_type).lower()})" for d in docs)
            return self._finish(base, t0, docs=doc_infos, status="NEEDS_REVIEW", reason="missing_attachment",
                                detail=f"The {missing_role} is missing. Received: {have}.",
                                headline=f"Needs review - {missing_role} missing",
                                explanation=f"Only {have} was received; the {missing_role} required for the comparison is not attached.",
                                action=f"Ask the sender to send the {missing_role}.",
                                confidence=cat_conf, ai_used=ai_used, warnings=warnings, policy=policy)

        si_fields, bl_fields = doc_fields[si_idx], doc_fields[bl_idx]
        si_doc, bl_doc = docs[si_idx], docs[bl_idx]
        rows, defects = compare_fields(si_fields, bl_fields)

        # 6. missing values ---------------------------------------------------
        miss_si, miss_bl = missing_fields(si_fields), missing_fields(bl_fields)
        if miss_si or miss_bl:
            parts = []
            if miss_si:
                parts.append("SI: " + ", ".join(FIELD_LABELS[f] for f in miss_si))
            if miss_bl:
                parts.append("draft BL: " + ", ".join(FIELD_LABELS[f] for f in miss_bl))
            detail = "Blank or unreadable fields - " + "; ".join(parts) + "."
            return self._finish(base, t0, docs=doc_infos, rows=rows, status="NEEDS_REVIEW", reason="missing_value", detail=detail,
                                headline="Needs review - required value missing",
                                explanation=f"{detail} A blank value is not a discrepancy; the comparison cannot be completed without it.",
                                action="Ask the customer / sender to complete the blank fields, then re-run the check.",
                                confidence=cat_conf, ai_used=ai_used, warnings=warnings, policy=policy)

        # 7. outcome ----------------------------------------------------------
        extraction_conf = 0.95
        if disagreements:
            extraction_conf = 0.7
        elif ai_filled:
            extraction_conf = 0.85
        if si_doc.fmt == "pdf" or bl_doc.fmt == "pdf":
            extraction_conf = min(extraction_conf, 0.9)
        confidence = round(min(cat_conf, extraction_conf), 2)
        evidence_ok = all(r.si_evidence and r.bl_evidence for r in rows)

        if defects:
            labels = [FIELD_LABELS[f] for f in defects]
            headline = f"High risk - {labels[0]} mismatch" if len(defects) == 1 else f"High risk - {len(defects)} field mismatches ({', '.join(labels)})"
            detail_lines = []
            for r in rows:
                if r.match is False:
                    detail_lines.append(f"{r.label}: SI says {r.si_value}; draft BL says {r.bl_value}.")
            explanation = " ".join(detail_lines[:4]) + " Suggested action: review and align the draft BL to the verified SI."
            action = "Review the highlighted fields and ask the carrier / agent to amend the draft BL to match the SI."
            return self._finish(base, t0, docs=doc_infos, rows=rows, status="MISMATCH", defects=defects, headline=headline,
                                explanation=explanation, action=action, confidence=confidence, evidence_ok=evidence_ok,
                                ai_used=ai_used, warnings=warnings, policy=policy)

        explanation = (f"No mismatch detected. All seven fields on the draft BL ({bl_doc.filename}) agree with the Shipping Instruction "
                       f"({si_doc.filename}): shipper, consignee, notify party, ports, container count and gross weight.")
        return self._finish(base, t0, docs=doc_infos, rows=rows, status="OK", headline="No mismatch detected",
                            explanation=explanation, action="Safe to complete - confirm the draft BL with the carrier.",
                            confidence=confidence, evidence_ok=evidence_ok, ai_used=ai_used, warnings=warnings,
                            policy=policy)

    # ---------------------------------------------------------------- finish
    def _finish(self, base: dict, t0: float, docs: list[DocInfo], status: str, headline: str, explanation: str, action: str,
                confidence: float, rows: Optional[list[FieldRow]] = None, defects: Optional[list[str]] = None,
                reason: Optional[str] = None, detail: Optional[str] = None, evidence_ok: bool = True, ai_used: bool = False,
                warnings: Optional[list[str]] = None, policy: str = "standard") -> CaseResult:
        defects = defects or []
        rows = rows or []
        if status == "MISMATCH":
            ui, risk, automation = "High risk", "high", "review_required"
        elif status == "NEEDS_REVIEW":
            ui, risk, automation = "Needs review", "medium", "review_required"
        else:
            threshold = 0.9 if policy == "strict" else 0.8
            if confidence >= threshold and evidence_ok:
                ui, risk, automation = "Safe to complete", "low", "auto_completed"
            else:
                ui, risk, automation = "Needs review", "medium", "review_required"
                explanation += " Confidence is below the automation threshold, so the case is routed to a person instead of being auto-completed."
        res = CaseResult(
            **base, status=status, review_reason=reason, review_detail=detail, has_defect=bool(defects), defect_fields=defects,
            ui_status=ui, risk=risk, headline=headline, explanation=explanation, suggested_action=action, confidence=confidence,
            evidence_available=evidence_ok, automation=automation, fields=rows, docs=docs, ai_used=ai_used, warnings=warnings or [],
        )
        res.duration_ms = int((time.perf_counter() - t0) * 1000)
        return res

    async def polish_with_ai(self, res: CaseResult) -> CaseResult:
        """Optional: let the model phrase the explanation (deterministic facts stay the source of truth)."""
        if not self.ai.enabled or res.category != "BL_COMPARISON":
            return res
        facts = [f"Email {res.email_id}: '{res.subject}'", f"Outcome: {res.status}" + (f" ({res.review_reason}: {res.review_detail})" if res.review_reason else "")]
        for r in res.fields:
            facts.append(f"- {r.label}: SI='{r.si_value}' BL='{r.bl_value}' match={r.match} ({r.reason})")
        out = await self.ai.explain_case("\n".join(facts))
        if out and out.get("explanation"):
            res.explanation = out["explanation"]
            if out.get("suggested_action"):
                res.suggested_action = out["suggested_action"]
            res.ai_used = True
        return res


# ---------------------------------------------------------------------------
# correction e-mail draft (template; only produced on explicit user request)
# ---------------------------------------------------------------------------

def build_correction_draft(res: CaseResult, email: dict) -> str:
    sender = email.get("from", "")
    name = sender.split("@")[0].replace(".", " ").replace("_", " ").title() if sender else "Team"
    ref = ""
    for token in (email.get("subject") or "").replace("_", " ").split():
        if any(ch.isdigit() for ch in token) and len(token) >= 6:
            ref = token
            break
    lines = [f"Subject: RE: {email.get('subject', '')}".strip(), "", f"Dear {name},", ""]
    if res.status == "MISMATCH":
        lines.append("Thank you for the draft Bill of Lading" + (f" for {ref}" if ref else "") + ". We compared it against the Shipping Instruction and found the following differences:")
        lines.append("")
        for r in res.fields:
            if r.match is False:
                lines.append(f"  - {r.label}: SI shows \"{r.si_value}\", draft BL shows \"{r.bl_value}\".")
        lines += ["", "Kindly amend the draft BL to match the Shipping Instruction and send us the revised draft for confirmation.", ""]
    elif res.status == "NEEDS_REVIEW":
        lines.append("Thank you for your email" + (f" regarding {ref}" if ref else "") + f". We could not complete the document check: {res.review_detail or REVIEW_LABELS.get(res.review_reason or '', 'the documents are incomplete')}")
        lines += ["", res.suggested_action, ""]
    else:
        lines.append("We have checked the draft Bill of Lading against the Shipping Instruction and found no mismatch. Please proceed with the release.")
        lines.append("")
    lines += ["Best regards,", "Shipping Documentation Team"]
    return "\n".join(lines)
