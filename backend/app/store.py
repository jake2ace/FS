"""In-memory result store with a small JSON cache on disk.

The MVP keeps everything in process memory (fast, zero setup).  Results are
also written to CACHE_DIR/results.json so a restart of the service does not
lose analysed cases.  Swapping this for Supabase/Postgres only touches this
file.
"""
from __future__ import annotations

import json
import threading
import time
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .schemas import CaseResult, Decision, RunState, ManualReviewInput, FIELDS, DRAFT_REQUESTED_UI


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, cache_dir: Optional[Path] = None):
        self.results: dict[str, CaseResult] = {}
        self.runs: dict[str, RunState] = {}
        self.legacy_results: list[dict] = []
        self.policy: str = "standard"
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._lock = threading.Lock()
        self._dirty = False
        self._last_flush = 0.0

    # -- persistence ---------------------------------------------------------
    @property
    def cache_file(self) -> Optional[Path]:
        return (self.cache_dir / "results.json") if self.cache_dir else None

    def load(self) -> int:
        f = self.cache_file
        if not f or not f.exists():
            return 0
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
            self.legacy_results = payload.get("legacy_results", [])
            for item in payload.get("results", []):
                try:
                    r = CaseResult.model_validate(item)
                    if r.pipeline_version < 3:
                        self.legacy_results.append(item)
                        continue
                    self.results[r.email_id] = r
                except Exception:
                    continue
            self.policy = payload.get("policy", "standard")
            for item in payload.get("runs", []):
                run = RunState.model_validate(item)
                if run.status == "running":
                    run.status = "failed"
                    run.finished_at = _now()
                    run.failed.append({"email_id": "-", "error": "Server restarted during processing; start a new run to continue."})
                self.runs[run.run_id] = run
            return len(self.results)
        except Exception:
            return 0

    def flush(self, force: bool = False) -> None:
        f = self.cache_file
        if not f:
            return
        with self._lock:
            if not self._dirty and not force:
                return
            if not force and time.time() - self._last_flush < 5:
                return
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "saved_at": _now(),
                    "policy": self.policy,
                    "results": [r.model_dump(mode="json") for r in self.results.values()],
                    "legacy_results": self.legacy_results,
                    "runs": [r.model_dump(mode="json") for r in self.runs.values()],
                }
                tmp = f.with_suffix(".tmp")
                tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                tmp.replace(f)
                self._dirty = False
                self._last_flush = time.time()
            except OSError as exc:
                raise OSError("Could not persist the review report; check backend storage and retry") from exc

    # -- results -------------------------------------------------------------
    def put(self, result: CaseResult) -> None:
        prev = self.results.get(result.email_id)
        if prev:
            result.history = prev.history + [{"event": "reanalysis", "at": _now(),
                                             "previous": prev.model_dump(exclude={"history"})}]
        # Re-analysis invalidates a previous approval. The earlier report remains in history.
        self.results[result.email_id] = result
        self._dirty = True
        self.flush()

    def get(self, email_id: str) -> Optional[CaseResult]:
        return self.results.get(email_id)

    def all(self) -> list[CaseResult]:
        return sorted(self.results.values(), key=lambda r: r.email_id)

    def clear(self) -> None:
        self.results.clear()
        self._dirty = True
        self.flush(force=True)

    def record_decision(self, email_id: str, action: str, note: Optional[str], by: str = "operator") -> Optional[CaseResult]:
        r = self.results.get(email_id)
        if not r:
            return None
        decision = Decision(action=action, note=note, by=by, at=_now())
        if action in ("approve_revision", "reject_revision"):
            if not r.working_report or r.processing_status != "PENDING_HUMAN_APPROVAL":
                raise ValueError("There is no pending revision to review.")
            if action == "approve_revision" and (r.working_report["status"] != "OK" or len(r.working_report["fields"]) != 7
                                                 or not all(row["match"] is True for row in r.working_report["fields"])):
                raise ValueError("Only a working report with seven confirmed matches can be adopted.")
            r.working_report["decision"] = decision.model_dump()
            r.resolved = action == "approve_revision"
            r.processing_status = "RESOLVED_BY_HUMAN" if r.resolved else "REVIEW_REQUIRED"
        elif action in ("confirm", "resolve"):
            if r.status != "OK" or r.automation == "review_required":
                raise ValueError("Review the field readings or replacement attachments first; unresolved discrepancies cannot be closed.")
            r.resolved = True
            r.processing_status = "RESOLVED_BY_HUMAN"
        else:
            r.resolved = False
            r.processing_status = "REVIEW_REQUIRED"
            r.automation = "review_required"
        r.decision = decision
        if r.resolved:
            r.manual_review = dict(category=r.category, status=r.status, note=note or 'Human approval recorded.',
                                   by=by, at=decision.at, complete=True)
            r.decision_chain.append(dict(tier='human', status='completed', at=decision.at, by=by))
        elif r.manual_review:
            r.manual_review['complete'] = False
        r.history.append({"event": "decision", **decision.model_dump()})
        self._dirty = True
        self.flush(force=True)
        return r

    def record_manual_review(self, email_id: str, review: ManualReviewInput) -> CaseResult:
        r = self.results[email_id]
        if r.processing_status == 'PENDING_HUMAN_APPROVAL':
            raise ValueError('Adopt or reject the pending copy first.')
        if not review.note.strip() or not review.by.strip():
            raise ValueError('Provide a handling note and reviewer name.')
        if len(set(review.defect_fields)) != len(review.defect_fields) or set(review.defect_fields) - set(FIELDS):
            raise ValueError('Select valid, distinct comparison fields.')
        if review.status == 'MISMATCH':
            if review.category != 'BL_COMPARISON' or not review.defect_fields:
                raise ValueError('A mismatch requires a BL comparison and confirmed defect fields.')
        elif review.defect_fields:
            raise ValueError('Only a confirmed mismatch can have defect fields.')
        if review.complete and review.status == 'NEEDS_REVIEW':
            raise ValueError('Choose a confirmed outcome before completing human handling.')
        event = dict(event='human_review', at=_now(), **review.model_dump())
        event['note'] = review.note.strip()
        event['previous'] = r.model_dump(exclude={'history'})
        r.history.append(event)
        r.manual_review = {k: v for k, v in event.items() if k not in ('previous', 'event')}
        r.category = review.category
        r.category_method = r.decision_method = 'human'
        r.category_reason = r.explanation = review.note.strip()
        r.category_confidence = r.confidence = 1.0
        r.category_evidence = []
        r.status = review.status
        r.defect_fields = review.defect_fields
        r.has_defect = review.status == 'MISMATCH'
        r.fields = []  # Original AI readings remain in the history snapshot.
        # Saving progress is not a new finding: keep the reason already established for this case
        # (missing_attachment / wrong_doc_type / unreadable) instead of restating it as missing_value.
        r.review_reason = (r.review_reason or 'missing_value') if review.status == 'NEEDS_REVIEW' else None
        r.review_detail = review.note.strip() if review.status == 'NEEDS_REVIEW' else None
        r.resolved = review.complete
        r.processing_status = 'RESOLVED_BY_HUMAN' if review.complete else 'REVIEW_REQUIRED'
        r.automation = 'none' if review.complete else 'review_required'
        r.ui_status = 'Human completed' if review.complete else 'Needs review'
        r.risk = 'none' if review.complete else 'medium'
        r.headline = 'Human handling completed' if review.complete else 'Human handling in progress'
        r.suggested_action = 'No further AI processing.' if review.complete else 'Continue human handling.'
        r.decision = Decision(action='resolve' if review.complete else 'escalate', note=review.note.strip(), by=review.by.strip(), at=event['at'])
        r.decision_chain.append(dict(tier='human', status='completed' if review.complete else 'pending', category=r.category, outcome=r.status, by=review.by.strip(), at=event['at']))
        self._dirty = True
        self.flush(force=True)
        return r

    def set_working_report(self, email_id: str, report: dict) -> CaseResult:
        r = self.results[email_id]
        if r.working_report:
            r.history.append({"event": "working_report_replaced", "at": _now(), "report": r.working_report})
        r.working_report = report
        r.resolved = False
        r.decision = None
        r.processing_status = "PENDING_HUMAN_APPROVAL" if report["status"] == "OK" else "REVIEW_REQUIRED"
        r.automation = "review_required"
        r.history.append({"event": "working_report_created", "at": _now(), "revision_id": report["revision_id"], "kind": report["kind"], "note": report["note"]})
        self._dirty = True
        self.flush(force=True)
        return r

    # -- runs ----------------------------------------------------------------
    def new_run(self, total: int, force: bool) -> RunState:
        run = RunState(run_id=f"run_{uuid4().hex[:12]}", started_at=_now(), total=total, force=force)
        self.runs[run.run_id] = run
        return run

    def get_run(self, run_id: str) -> Optional[RunState]:
        return self.runs.get(run_id)

    def runs_list(self) -> list[RunState]:
        return sorted(self.runs.values(), key=lambda r: r.started_at, reverse=True)

    # -- dashboard -----------------------------------------------------------
    def summary(self, total_emails: int) -> dict:
        res = list(self.results.values())
        by_cat: dict[str, int] = {}
        for r in res:
            if r.category is not None:
                by_cat[r.category] = by_cat.get(r.category, 0) + 1
        bl = [r for r in res if r.category == "BL_COMPARISON"]
        open_review = [r for r in res if r.automation == "review_required" and not r.resolved]
        # Which of the seven fields actually goes wrong. A supervisor asks this to find
        # out where the paperwork keeps breaking - one carrier always getting the notify
        # party wrong is a conversation to have, not twelve cases to fix one at a time.
        # Resolved cases stay in the count on purpose: the point is where differences
        # arise, not how many are still open.
        by_field: dict[str, int] = {}
        defect_cases = defect_cases_multi = 0
        for r in bl:
            if r.status == "MISMATCH" and r.defect_fields:
                defect_cases += 1
                if len(r.defect_fields) > 1:
                    defect_cases_multi += 1
                for f in r.defect_fields:
                    by_field[f] = by_field.get(f, 0) + 1
        return {
            "total_emails": total_emails,
            "analysed": len(res),
            "not_analysed": max(0, total_emails - len(res)),
            "by_category": by_cat,
            "comparison_requests": len(bl),
            "high_risk": sum(1 for r in bl if r.status == "MISMATCH" and not r.resolved),
            "needs_review": sum(1 for r in res if r.status == "NEEDS_REVIEW" and not r.resolved),
            "safe_completed": sum(1 for r in bl if r.automation == "auto_completed" and r.processing_status == "NO_ACTION"),
            "pending_approval": sum(1 for r in bl if r.processing_status == "PENDING_HUMAN_APPROVAL"),
            "awaiting_draft": sum(1 for r in bl if r.ui_status == DRAFT_REQUESTED_UI and not r.resolved),
            "resolved": sum(1 for r in res if r.resolved),
            "open_review_queue": len(open_review),
            "policy": self.policy,
            "ai_used_cases": sum(1 for r in res if r.ai_used),
            "defects_by_field": by_field,
            # How many drafts are wrong in more than one place. This is the number that
            # changes what an operator does: if most bad drafts differ on two fields,
            # "fix the one we spotted and resend" is the wrong habit.
            "defect_cases": defect_cases,
            "defect_cases_multi": defect_cases_multi,
        }
