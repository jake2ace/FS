"""FreightSentinel API (FastAPI).

Routes
------
GET  /health, /api/health                 service + data + AI status
GET  /api/dashboard                       counts for Today Work Centre + priority list
GET  /api/emails                          inbox list (with result summary when analysed)
GET  /api/emails/{email_id}               one email record + result
GET  /api/emails/{email_id}/attachments/{index}/text   text preview of an attachment
POST /api/analyse/{email_id}              analyse one email (?force=true to re-run)
GET  /api/results/{email_id}              stored result
GET  /api/results                         all results (summary rows)
POST /api/runs/full-inbox                 start a batch run over the whole inbox
GET  /api/runs, /api/runs/{run_id}        run status
POST /api/runs/{run_id}/cancel
POST /api/runs/{run_id}/retry/{email_id}  re-run one failed email of a run
POST /api/cases/{email_id}/decision       confirm | escalate | resolve | reopen
POST /api/cases/{email_id}/correction-draft
GET  /api/submission                      official self-evaluation JSON
GET/POST /api/settings/policy             standard | strict
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__, config
from .ai import AIClient
from .data import Inbox
from .pipeline import Analyser, build_correction_draft
from .schemas import CATEGORIES, CaseResult
from .store import Store
from .submission import build_submission

inbox = Inbox(config.DATA_DIR, config.DATA_ZIP)
ai = AIClient()
store = Store(config.CACHE_DIR)
analyser = Analyser(inbox, ai)
_run_tasks: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    inbox.ensure()
    inbox.emails()
    store.policy = config.DEFAULT_POLICY if config.DEFAULT_POLICY in ("standard", "strict") else "standard"
    store.load()
    yield
    store.flush(force=True)


app = FastAPI(title="FreightSentinel API", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- helpers

def _email_or_404(email_id: str) -> dict:
    email = inbox.get(email_id)
    if not email:
        raise HTTPException(status_code=404, detail=f"unknown email_id {email_id}")
    return email


def _summary_row(email: dict, res: Optional[CaseResult]) -> dict:
    row = {
        "email_id": email["email_id"],
        "subject": email.get("subject", ""),
        "from": email.get("from", ""),
        "attachment_count": len(email.get("attachments") or []),
        "attachments": email.get("attachments") or [],
        "body_preview": (email.get("body") or "")[:160],
        "analysed": res is not None,
    }
    if res:
        row.update({
            "category": res.category,
            "category_confidence": res.category_confidence,
            "status": res.status,
            "ui_status": res.ui_status,
            "risk": res.risk,
            "review_reason": res.review_reason,
            "defect_fields": res.defect_fields,
            "headline": res.headline,
            "confidence": res.confidence,
            "automation": res.automation,
            "resolved": res.resolved,
            "decision": res.decision.model_dump() if res.decision else None,
            "analysed_at": res.analysed_at,
            "ai_used": res.ai_used,
        })
    return row


RISK_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}


async def _analyse_and_store(email: dict, explain_with_ai: bool = False) -> CaseResult:
    res = await analyser.analyse(email, policy=store.policy, explain_with_ai=explain_with_ai)
    store.put(res)
    return res


# ---------------------------------------------------------------- health

@app.get("/health")
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "freightsentinel-api",
        "version": __version__,
        "emails": len(inbox),
        "results_cached": len(store.results),
        "ai": ai.describe(),
        "policy": store.policy,
    }


# ---------------------------------------------------------------- inbox

@app.get("/api/emails")
async def list_emails(
    category: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    analysed: Optional[bool] = Query(default=None),
    has_attachments: Optional[bool] = Query(default=None),
    limit: int = Query(default=600, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
):
    rows = []
    ql = (q or "").strip().lower()
    for email in inbox.emails():
        res = store.get(email["email_id"])
        if category and (not res or res.category != category.upper()):
            continue
        if status and (not res or (res.status != status.upper() and res.ui_status.lower() != status.lower())):
            continue
        if analysed is not None and (res is not None) != analysed:
            continue
        if has_attachments is not None and bool(email.get("attachments")) != has_attachments:
            continue
        if ql and ql not in (email.get("subject", "") + " " + email.get("from", "") + " " + email["email_id"]).lower():
            continue
        rows.append(_summary_row(email, res))
    total = len(rows)
    return {"total": total, "items": rows[offset: offset + limit]}


@app.get("/api/emails/{email_id}")
async def get_email(email_id: str):
    email = _email_or_404(email_id)
    res = store.get(email_id)
    atts = []
    for i, p in enumerate(email.get("attachments") or []):
        atts.append({"index": i, "path": p, "filename": p.rsplit("/", 1)[-1], "size_bytes": inbox.attachment_size(p)})
    return {"email": email, "attachments": atts, "result": res.model_dump(mode="json") if res else None}


@app.get("/api/emails/{email_id}/attachments/{index}/text")
async def attachment_text(email_id: str, index: int):
    email = _email_or_404(email_id)
    atts = email.get("attachments") or []
    if index < 0 or index >= len(atts):
        raise HTTPException(status_code=404, detail="no such attachment")
    from .parsers import parse_attachment  # local import: keeps module import light

    data = await asyncio.to_thread(inbox.read_bytes, atts[index])
    doc = await asyncio.to_thread(parse_attachment, atts[index], data)
    return {
        "path": doc.path, "format": doc.fmt, "readable": doc.readable, "error": doc.error,
        "detected_type": doc.detected_type, "size_bytes": doc.size, "text": doc.text[:20000],
    }


# ---------------------------------------------------------------- analysis

@app.post("/api/analyse/{email_id}")
async def analyse_email(email_id: str, force: bool = Query(default=True), explain: bool = Query(default=True)):
    email = _email_or_404(email_id)
    existing = store.get(email_id)
    if existing and not force:
        return existing.model_dump(mode="json")
    res = await _analyse_and_store(email, explain_with_ai=explain)
    return res.model_dump(mode="json")


@app.get("/api/results")
async def list_results():
    return {"total": len(store.results), "items": [_summary_row(inbox.get(r.email_id) or {"email_id": r.email_id}, r) for r in store.all()]}


@app.get("/api/results/{email_id}")
async def get_result(email_id: str):
    res = store.get(email_id)
    if not res:
        raise HTTPException(status_code=404, detail="not analysed yet")
    return res.model_dump(mode="json")


@app.delete("/api/results")
async def clear_results():
    store.clear()
    return {"ok": True}


# ---------------------------------------------------------------- batch runs

async def _run_batch(run_id: str, email_ids: list[str], force: bool) -> None:
    run = store.get_run(run_id)
    if not run:
        return
    sem = asyncio.Semaphore(max(1, config.BATCH_CONCURRENCY))

    async def one(eid: str) -> None:
        async with sem:
            if run.status == "cancelled":
                return
            email = inbox.get(eid)
            if not email:
                run.failed.append({"email_id": eid, "error": "unknown email"})
                run.done += 1
                return
            if not force and store.get(eid):
                res = store.get(eid)
            else:
                run.current = eid
                try:
                    res = await _analyse_and_store(email, explain_with_ai=False)
                except Exception as exc:  # keep the run alive, report the failure
                    run.failed.append({"email_id": eid, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                    run.done += 1
                    return
            run.done += 1
            if res.category != "BL_COMPARISON":
                run.not_applicable += 1
            elif res.status == "MISMATCH":
                run.mismatch += 1
            elif res.status == "NEEDS_REVIEW":
                run.needs_review += 1
            else:
                run.ok += 1

    try:
        await asyncio.gather(*(one(eid) for eid in email_ids))
        if run.status != "cancelled":
            run.status = "completed"
    except asyncio.CancelledError:
        run.status = "cancelled"
        raise
    except Exception as exc:
        run.status = "failed"
        run.failed.append({"email_id": "-", "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    finally:
        run.current = None
        from datetime import datetime, timezone
        run.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        store.flush(force=True)


@app.post("/api/runs/full-inbox")
async def start_full_run(payload: Optional[dict] = Body(default=None)):
    payload = payload or {}
    force = bool(payload.get("force", False))
    only_ids = payload.get("email_ids")
    active = [r for r in store.runs.values() if r.status == "running"]
    if active:
        raise HTTPException(status_code=409, detail=f"run {active[0].run_id} is still running")
    ids = [e["email_id"] for e in inbox.emails()]
    if isinstance(only_ids, list) and only_ids:
        ids = [i for i in ids if i in set(only_ids)]
    run = store.new_run(total=len(ids), force=force)
    _run_tasks[run.run_id] = asyncio.create_task(_run_batch(run.run_id, ids, force))
    return run.model_dump(mode="json")


@app.get("/api/runs")
async def list_runs():
    return {"items": [r.model_dump(mode="json") for r in store.runs_list()]}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="unknown run")
    return run.model_dump(mode="json")


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="unknown run")
    run.status = "cancelled"
    task = _run_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
    return run.model_dump(mode="json")


@app.post("/api/runs/{run_id}/retry/{email_id}")
async def retry_email(run_id: str, email_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="unknown run")
    email = _email_or_404(email_id)
    try:
        res = await _analyse_and_store(email, explain_with_ai=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"retry failed: {type(exc).__name__}: {str(exc)[:200]}")
    run.failed = [f for f in run.failed if f.get("email_id") != email_id]
    if res.category != "BL_COMPARISON":
        run.not_applicable += 1
    elif res.status == "MISMATCH":
        run.mismatch += 1
    elif res.status == "NEEDS_REVIEW":
        run.needs_review += 1
    else:
        run.ok += 1
    return {"run": run.model_dump(mode="json"), "result": res.model_dump(mode="json")}


# ---------------------------------------------------------------- human decisions

@app.post("/api/cases/{email_id}/decision")
async def case_decision(email_id: str, payload: dict = Body(...)):
    action = str(payload.get("action", "")).lower()
    if action not in ("confirm", "escalate", "resolve", "reopen"):
        raise HTTPException(status_code=400, detail="action must be confirm | escalate | resolve | reopen")
    note = payload.get("note")
    res = store.record_decision(email_id, action, str(note)[:1000] if note else None, by=str(payload.get("by") or "operator"))
    if not res:
        raise HTTPException(status_code=404, detail="case not analysed yet")
    return res.model_dump(mode="json")


@app.post("/api/cases/{email_id}/correction-draft")
async def correction_draft(email_id: str):
    email = _email_or_404(email_id)
    res = store.get(email_id)
    if not res:
        raise HTTPException(status_code=404, detail="case not analysed yet")
    return {"email_id": email_id, "draft": build_correction_draft(res, email), "editable": True, "sends_email": False}


# ---------------------------------------------------------------- dashboard / submission / settings

@app.get("/api/dashboard")
async def dashboard():
    summary = store.summary(len(inbox))
    open_cases = [r for r in store.all() if r.category == "BL_COMPARISON" and r.automation == "review_required" and not r.resolved]
    open_cases.sort(key=lambda r: (RISK_ORDER.get(r.risk, 9), -len(r.defect_fields), r.email_id))
    priority = [_summary_row(inbox.get(r.email_id) or {"email_id": r.email_id}, r) for r in open_cases[:12]]
    runs = store.runs_list()
    return {
        "summary": summary,
        "priority": priority,
        "policy": {
            "name": store.policy,
            "auto_complete_threshold": 0.9 if store.policy == "strict" else 0.8,
            "description": "Only cases whose seven fields all match, with evidence available and confidence above the threshold, are auto-completed. Every mismatch, missing document, unreadable file or blank value goes to a person.",
        },
        "last_run": runs[0].model_dump(mode="json") if runs else None,
        "ai": ai.describe(),
    }


@app.get("/api/submission")
async def submission(download: bool = Query(default=False)):
    ids = [e["email_id"] for e in inbox.emails()]
    sub, missing = build_submission(ids, store.results)
    headers = {}
    if download:
        headers["Content-Disposition"] = 'attachment; filename="submission.json"'
    if missing:
        headers["X-Unanalysed-Emails"] = str(len(missing))
    return JSONResponse(content=sub, headers=headers)


@app.get("/api/submission/status")
async def submission_status():
    ids = [e["email_id"] for e in inbox.emails()]
    _, missing = build_submission(ids, store.results)
    return {"total": len(ids), "analysed": len(ids) - len(missing), "missing": missing[:50], "missing_count": len(missing), "ready": not missing}


@app.get("/api/settings/policy")
async def get_policy():
    return {"policy": store.policy}


@app.post("/api/settings/policy")
async def set_policy(payload: dict = Body(...)):
    policy = str(payload.get("policy", "")).lower()
    if policy not in ("standard", "strict"):
        raise HTTPException(status_code=400, detail="policy must be standard or strict")
    store.policy = policy
    store.flush(force=True)
    return {"policy": store.policy}


@app.get("/api/categories")
async def categories():
    return {"categories": CATEGORIES}
