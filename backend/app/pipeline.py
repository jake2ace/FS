"""AI owns classification, document readings, comparisons and business outcomes.

Python only loads files, validates response structure/source excerpts, routes
technical failures and persists/displays the model's decision. No rules fallback.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional
from pydantic import ValidationError

from .ai import AIClient
from .ai_contract import Classification, Verdict, source_excerpt
from .data import Inbox
from .parsers import ParsedDoc, parse_attachment
from .recovery import recover_document
from .schemas import (FIELDS, FIELD_LABELS, DRAFT_REQUESTED_UI, CaseResult, DocInfo,
                      FieldRow, FieldValue, SeniorReview)

CATEGORY_LABELS = {'BL_COMPARISON':'BL comparison request', 'SI_REQUEST':'New SI request',
                   'INVOICE_QUERY':'Invoice query', 'GENERAL':'General / operational notice', 'SPAM':'Spam'}
CATEGORY_ACTIONS = {'SI_REQUEST':'Route to the documentation team.', 'INVOICE_QUERY':'Route to billing / finance.',
                    'GENERAL':'Keep for reference.', 'SPAM':'Ignore. Do not open links or attachments.'}
REVIEW_LABELS = {'missing_attachment':'Missing attachment', 'wrong_doc_type':'Wrong document type',
                 'unreadable':'Unreadable or uncertain input', 'missing_value':'Missing value in the documents'}


class AIUnavailable(RuntimeError):
    """A technical failure; never manufacture a category or a successful result."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _doc_info(doc: ParsedDoc) -> DocInfo:
    # Parser type guesses and filename hints are deliberately not exposed as judgements.
    return DocInfo(path=doc.path, filename=doc.filename, format=doc.fmt, detected_type='UNKNOWN',
                   readable=doc.readable, read_error=doc.error, size_bytes=doc.size,
                   text_chars=len(doc.text), text_preview=doc.text[:2500], recovery=doc.recovery,
                   recovery_confidence=doc.recovery_confidence)


class Analyser:
    def __init__(self, inbox: Inbox, ai: AIClient, senior_ai: Optional[AIClient] = None):
        self.inbox, self.ai, self.senior_ai = inbox, ai, senior_ai

    @staticmethod
    def _trace(tier, ai, result):
        return dict(tier=tier, provider=ai.provider, model=ai.model, category=result.category,
                    thinking=ai.thinking, reasoning_effort=ai.reasoning_effort if ai.thinking else None,
                    status=result.status, method=result.decision_method, reason=result.explanation,
                    unconfirmed_assessment=result.unconfirmed_ai_assessment)

    async def _escalate(self, result, run_senior):
        result.decision_chain = [self._trace('primary', self.ai, result)]
        if result.status != 'NEEDS_REVIEW':
            return result
        if not self.senior_ai or not self.senior_ai.enabled:
            result.decision_chain.append(dict(tier='senior', available=False, reason='Senior AI is not configured or unavailable.'))
            result.decision_chain.append(dict(tier='human', status='pending'))
            return result
        senior = await run_senior(Analyser(self.inbox, self.senior_ai))
        senior.decision_chain = result.decision_chain + [self._trace('senior', self.senior_ai, senior)]
        senior.senior_review = SeniorReview(model=self.senior_ai.model,
            available=senior.decision_method=='ai', triggers=[result.explanation],
            category=senior.category, outcome=senior.status, assessment=senior.explanation,
            category_confidence=senior.category_confidence, confidence=senior.confidence)
        # A failed senior classification cannot erase an already evidenced primary category.
        if senior.category is None and result.category is not None:
            for name in ('category','category_confidence','category_reason','category_evidence','category_method','intent','docs'):
                setattr(senior, name, getattr(result, name))
        if senior.status == 'NEEDS_REVIEW':
            senior.decision_chain.append(dict(tier='human', status='pending'))
        return senior

    def require_ai(self):
        if not self.ai.enabled:
            raise AIUnavailable('AI is not enabled. Configure the provider and retry; no rule-based decision was made.')

    async def analyse(self, email: dict, policy: str = 'standard', explain_with_ai: bool = False) -> CaseResult:
        result = await self._analyse_once(email, policy, explain_with_ai)
        return await self._escalate(result, lambda senior: senior._analyse_once(email, policy, explain_with_ai))

    async def _analyse_once(self, email: dict, policy: str = 'standard', explain_with_ai: bool = False) -> CaseResult:
        started = time.perf_counter()
        if not self.ai.enabled:
            return self._unclassified_review(email, 'AI is unavailable. A person must classify and review this email.', started)
        classification = await self.ai.classify_email(email)
        if classification is None:
            return self._unclassified_review(email, 'AI classification was unavailable or invalid. No category was assigned; human review is required.', started)
        try:
            classified = Classification.model_validate(classification)
            classified.validate_sources(email)
        except (ValidationError, ValueError):
            return self._unclassified_review(email, 'AI classification has invalid structure or source evidence. A person must determine the category.', started)
        if classified.needs_review:
            return self._unclassified_review(email, classified.reason, started)
        base = self._base(email, classified)
        if classified.category != 'BL_COMPARISON':
            return CaseResult(**base, status='OK', ui_status='No action', risk='none',
                              headline=CATEGORY_LABELS[classified.category], explanation=classified.reason,
                              suggested_action=CATEGORY_ACTIONS[classified.category], confidence=classified.confidence,
                              evidence_available=True, automation='none', ai_used=True,
                              duration_ms=int((time.perf_counter()-started)*1000))
        docs = []
        for path in email.get('attachments') or []:
            try:
                data = await asyncio.to_thread(self.inbox.read_bytes, path)
                doc = await asyncio.to_thread(parse_attachment, path, data)
                if not doc.readable:
                    doc = await asyncio.to_thread(recover_document, doc, data)
            except FileNotFoundError:
                doc = ParsedDoc(path=path, filename=path.rsplit('/',1)[-1], fmt='missing', size=0,
                                readable=False, error='Attachment file not found')
            except Exception as exc:
                doc = ParsedDoc(path=path, filename=path.rsplit('/',1)[-1], fmt='unknown', size=0,
                                readable=False, error=f'Attachment could not be read: {type(exc).__name__}')
            docs.append(doc)
        return await self._judge_once(email, docs, base=base, policy=policy, started=started)

    def _base(self, email, classification=None):
        return dict(pipeline_version=3, email_id=email['email_id'], subject=email.get('subject',''),
                    sender=email.get('from',''), attachments=list(email.get('attachments') or []),
                    category=classification.category if classification else 'BL_COMPARISON',
                    category_confidence=classification.confidence if classification else 1,
                    category_reason=classification.reason if classification else 'Recheck of the confirmed BL comparison case.',
                    category_evidence=classification.evidence if classification else [],
                    category_prompt_version=self.ai.CLASSIFY_PROMPT_VERSION if classification else None,
                    category_method='ai' if classification else 'confirmed_case',
                    intent=classification.intent if classification else 'verify_documents',
                    analysed_at=_now(), decision_method='ai', ai_model=self.ai.model)

    def _handoff(self, base, detail, *, docs=None, started=None, method='ai_unavailable', assessment=None):
        return CaseResult(**dict(base, decision_method=method), status='NEEDS_REVIEW',
            review_reason='unreadable', review_detail=detail, ui_status='Needs review', risk='medium',
            headline='Human review required', explanation=detail,
            suggested_action='Review the original email and attachments, then record a human conclusion. AI approval is not required.',
            confidence=0, evidence_available=False, automation='review_required', docs=docs or [],
            ai_used=self.ai.enabled, warnings=[detail], processing_status='REVIEW_REQUIRED',
            unconfirmed_ai_assessment=assessment,
            duration_ms=int((time.perf_counter()-(started or time.perf_counter()))*1000))

    def _unclassified_review(self, email, detail, started):
        base = dict(self._base(email), category=None, category_confidence=0,
                    category_reason=detail, category_method='unavailable', intent='other',
                    category_prompt_version=self.ai.CLASSIFY_PROMPT_VERSION)
        return self._handoff(base, detail, started=started)

    async def judge(self, email: dict, docs: list[ParsedDoc], *, base=None,
                    policy='standard', started=None) -> CaseResult:
        result = await self._judge_once(email, docs, base=base, policy=policy, started=started)
        async def again(senior):
            senior_base = dict(base, ai_model=senior.ai.model) if base else None
            return await senior._judge_once(email, docs, base=senior_base, policy=policy, started=started)
        return await self._escalate(result, again)

    async def _judge_once(self, email: dict, docs: list[ParsedDoc], *, base=None,
                          policy='standard', started=None) -> CaseResult:
        started = started or time.perf_counter()
        base = base or self._base(email)
        infos = [_doc_info(d) for d in docs]
        if not self.ai.enabled:
            return self._handoff(base, 'AI is unavailable. Review the documents manually.', docs=infos, started=started)
        payload = [{'index':i, 'filename':d.filename, 'readable':d.readable, 'error':d.error,
                    'file_missing':d.fmt=='missing', 'text':d.text} for i,d in enumerate(docs)]
        raw = await self.ai.verify_documents(email, payload, policy)
        if raw is None:
            return self._handoff(base, 'AI document analysis returned no usable result. The documents need human review; no match or mismatch was confirmed.', docs=infos, started=started)
        try:
            verdict = Verdict.model_validate(raw)
            rows = self._validate_response(verdict, docs, infos, base.get('intent', 'verify_documents'))
        except (ValidationError, ValueError) as exc:
            # Rejected output is not repaired or replaced by a rule-based judgement.
            detail = str(exc) if not isinstance(exc, ValidationError) else 'AI response schema is invalid: ' + '; '.join(
                '.'.join(str(part) for part in e['loc']) + ' (' + e['type'] + ')'
                for e in exc.errors(include_input=False, include_url=False)[:5])
            return self._handoff(base, detail, docs=infos, started=started, method='response_validation',
                                 assessment=str(raw.get('explanation') or '')[:2000])
        status = verdict.status
        # An email that only asks for the draft BL to be sent has no documents to compare yet.
        # It is neither an automated completion nor a failure needing a human decision: it is a
        # business action for the recipient. The AI decided the intent; this only routes it.
        awaiting_draft = status == 'OK' and base.get('intent') == 'request_draft' and not docs
        if awaiting_draft:
            ui, risk, automation = DRAFT_REQUESTED_UI, 'none', 'none'
        else:
            ui, risk, automation = ('Safe to complete','low','auto_completed') if status=='OK' else (
                ('Mismatch','high','review_required') if status=='MISMATCH' else ('Needs review','medium','review_required'))
        return CaseResult(**base, status=status, review_reason=verdict.review_reason,
            review_detail=verdict.explanation if status=='NEEDS_REVIEW' else None,
            has_defect=status=='MISMATCH', defect_fields=verdict.defect_fields,
            ui_status=ui, risk=risk,
            headline='Draft BL requested - nothing to compare yet' if awaiting_draft else
                     {'OK':'No mismatch detected','MISMATCH':'AI detected field mismatches',
                      'NEEDS_REVIEW':'AI requests human review'}[status],
            explanation=verdict.explanation, suggested_action=verdict.suggested_action, confidence=verdict.confidence,
            evidence_available=bool(rows) and all(r.si_evidence and r.bl_evidence for r in rows),
            automation=automation, fields=rows, docs=infos, ai_used=True,
            processing_status='NO_ACTION' if status=='OK' else 'REVIEW_REQUIRED',
            duration_ms=int((time.perf_counter()-started)*1000))

    @staticmethod
    def _validate_response(v: Verdict, docs: list[ParsedDoc], infos: list[DocInfo],
                           intent: str = 'verify_documents') -> list[FieldRow]:
        if sorted(d.index for d in v.documents) != list(range(len(docs))):
            raise ValueError('AI must account for each received attachment exactly once.')
        for reading in v.documents:
            info, source = infos[reading.index], docs[reading.index]
            info.detected_type = reading.doc_type
            info.extraction_method = 'ai' if source.readable else 'none'
            if reading.doc_type in ('SI','BL') and set(reading.fields) != set(FIELDS):
                raise ValueError('AI must return all seven field entries for each SI/BL, including nulls.')
            for field, value in reading.fields.items():
                if field not in FIELDS:
                    raise ValueError('AI returned an unsupported field name.')
                if value.value is not None:
                    if not value.value.strip() or not source_excerpt(value.evidence, source.text):
                        raise ValueError(f'AI {FIELD_LABELS[field]} has no matching source excerpt in {source.filename}.')
                if value.label and not source_excerpt(value.label, source.text):
                    raise ValueError(f'AI field label is absent from {source.filename}.')
                info.fields[field] = FieldValue(value=value.value, evidence=value.evidence, label=value.label, source='ai')
        if v.status == 'NEEDS_REVIEW':
            if v.review_reason is None or v.defect_fields:
                raise ValueError('AI review status requires a reason and no confirmed defect list.')
        elif v.review_reason is not None:
            raise ValueError('AI result contains a contradictory review reason.')
        pair = [[d for d in infos if d.detected_type==role and d.readable] for role in ('SI','BL')]
        # A request to send the draft BL arrives with no attachments at all, so the
        # "one readable SI and one readable BL" requirement cannot apply to it: there is
        # nothing to compare yet. Only an OK on an entirely empty attachment list qualifies -
        # anything that carries files must still produce a real, readable pair.
        awaiting_draft = v.status == 'OK' and not docs and intent == 'request_draft'
        if not awaiting_draft and v.status in ('OK','MISMATCH') and (
                any(not d.readable for d in docs) or any(len(x)!=1 for x in pair)):
            raise ValueError('AI successful comparison requires one readable SI and one readable BL.')
        if not all(len(x)==1 for x in pair):
            if v.comparisons:
                raise ValueError('AI supplied comparisons without one identified SI/BL pair.')
            return []
        if set(v.comparisons) != set(FIELDS):
            raise ValueError('AI must return exactly seven field comparisons.')
        si, bl = pair[0][0], pair[1][0]
        rows = []
        for field in FIELDS:
            s, b, comparison = si.fields[field], bl.fields[field], v.comparisons[field]
            if comparison.match is not None and (s.value is None or b.value is None):
                raise ValueError('AI compared a field whose source value is null.')
            rows.append(FieldRow(field=field, label=FIELD_LABELS[field], si_value=s.value, bl_value=b.value,
                si_evidence=s.evidence, bl_evidence=b.evidence, match=comparison.match, reason=comparison.reason))
        if v.status=='OK' and (v.defect_fields or not all(r.match is True for r in rows)):
            raise ValueError('AI OK conflicts with its own field comparisons.')
        if v.status=='MISMATCH':
            false_fields = [r.field for r in rows if r.match is False]
            if any(r.match is None for r in rows) or not false_fields or sorted(v.defect_fields)!=sorted(false_fields):
                raise ValueError('AI MISMATCH conflicts with its own field comparisons.')
        return rows

    async def recheck_copy(self, result: CaseResult, revised: bytes, inbox, policy='standard') -> CaseResult:
        si = next(d for d in result.docs if d.detected_type=='SI')
        bl = next(d for d in result.docs if d.detected_type=='BL')
        docs = [await asyncio.to_thread(parse_attachment, si.path, await asyncio.to_thread(inbox.read_bytes, si.path)),
                await asyncio.to_thread(parse_attachment, bl.path, revised)]
        email = dict(email_id=result.email_id, subject='Recheck corrected draft BL against the original SI',
                     body='Verify all seven fields from these documents.', attachments=[si.path,bl.path])
        return await self.judge(email, docs, policy=policy)


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
