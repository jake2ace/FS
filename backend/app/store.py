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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .schemas import CaseResult, Decision, RunState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, cache_dir: Optional[Path] = None):
        self.results: dict[str, CaseResult] = {}
        self.runs: dict[str, RunState] = {}
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
            for item in payload.get("results", []):
                try:
                    r = CaseResult.model_validate(item)
                    self.results[r.email_id] = r
                except Exception:
                    continue
            self.policy = payload.get("policy", "standard")
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
                }
                tmp = f.with_suffix(".tmp")
                tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                tmp.replace(f)
                self._dirty = False
                self._last_flush = time.time()
            except Exception:
                pass

    # -- results -------------------------------------------------------------
    def put(self, result: CaseResult) -> None:
        prev = self.results.get(result.email_id)
        if prev and prev.decision and not result.decision:
            # keep the human decision when a case is re-analysed
            result.decision = prev.decision
            result.resolved = prev.resolved
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
        r.decision = Decision(action=action, note=note, by=by, at=_now())
        r.resolved = action in ("confirm", "resolve")
        if action == "reopen":
            r.resolved = False
        self._dirty = True
        self.flush(force=True)
        return r

    # -- runs ----------------------------------------------------------------
    def new_run(self, total: int, force: bool) -> RunState:
        run = RunState(run_id=f"run_{int(time.time())}", started_at=_now(), total=total, force=force)
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
            by_cat[r.category] = by_cat.get(r.category, 0) + 1
        bl = [r for r in res if r.category == "BL_COMPARISON"]
        open_review = [r for r in bl if r.automation == "review_required" and not r.resolved]
        return {
            "total_emails": total_emails,
            "analysed": len(res),
            "not_analysed": max(0, total_emails - len(res)),
            "by_category": by_cat,
            "comparison_requests": len(bl),
            "high_risk": sum(1 for r in bl if r.status == "MISMATCH" and not r.resolved),
            "needs_review": sum(1 for r in bl if r.status == "NEEDS_REVIEW" and not r.resolved),
            "safe_completed": sum(1 for r in bl if r.automation == "auto_completed"),
            "awaiting_draft": sum(1 for r in bl if r.ui_status == "Awaiting draft BL"),
            "resolved": sum(1 for r in bl if r.resolved),
            "open_review_queue": len(open_review),
            "policy": self.policy,
            "ai_used_cases": sum(1 for r in res if r.ai_used),
        }
