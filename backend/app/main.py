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
GET  /api/submission                      official submission JSON
GET  /api/export.csv                      operations report (one row per differing field)
GET/POST /api/settings/policy             standard | strict
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import csv
import io
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

from . import __version__, config
from .ai import AIClient
from .data import Inbox
from .pipeline import Analyser, AIUnavailable, build_correction_draft
from .schemas import CATEGORIES, DRAFT_REQUESTED_UI, CaseResult, ManualReviewInput
from .store import Store
from .submission import build_submission
from .workflow import human_report, attachment_report, now
from .revisions import build_revision, revision_path, delete_revision, validate_revision

inbox = Inbox(config.DATA_DIR, config.DATA_ZIP)
ai = AIClient(mode=config.AI_MODE, thinking=config.AI_THINKING, reasoning_effort=config.AI_REASONING_EFFORT)
store = Store(config.CACHE_DIR)
senior_ai = AIClient(provider=config.AI_SENIOR_PROVIDER, api_key=config.AI_SENIOR_API_KEY,
    model=config.AI_SENIOR_MODEL, timeout=config.AI_SENIOR_TIMEOUT, mode=config.AI_MODE,
    fallback_model='', max_rpm=config.senior_max_rpm(), thinking=config.AI_SENIOR_THINKING,
    reasoning_effort=config.AI_SENIOR_REASONING_EFFORT) if config.AI_SENIOR_MODEL and config.AI_SENIOR_API_KEY else None
analyser = Analyser(inbox, ai, senior_ai)
_run_tasks: dict[str, asyncio.Task] = {}
_case_locks: dict[str, asyncio.Lock] = {}
_retrying: set[tuple[str, str]] = set()

def _case_lock(email_id: str) -> asyncio.Lock:
    return _case_locks.setdefault(email_id, asyncio.Lock())


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


@app.exception_handler(AIUnavailable)
async def ai_unavailable_handler(request, exc):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


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
            "processing_status": res.processing_status,
            "decision": res.decision.model_dump() if res.decision else None,
            "analysed_at": res.analysed_at,
            "ai_used": res.ai_used,
        })
    return row


RISK_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}


async def _analyse_and_store(email: dict, explain_with_ai: bool = False) -> CaseResult:
    async with _case_lock(email["email_id"]):
        previous = store.get(email["email_id"])
        if previous and (previous.manual_review or previous.resolved):
            raise ValueError("Human handling is final; continue through the human review form without AI.")
        if previous and previous.processing_status == "PENDING_HUMAN_APPROVAL":
            raise ValueError("Adopt or reject the pending revision before re-analysing.")
        res = await analyser.analyse(email, policy=store.policy, explain_with_ai=explain_with_ai)
        store.put(res)
        return res


# ---------------------------------------------------------------- health

# HEAD as well as GET: uptime monitors send HEAD by default, and FastAPI's @app.get
# would answer those with 405, which reads as an outage on the monitor.
@app.api_route("/health", methods=["GET", "HEAD"])
@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health():
    return {
        "status": "ok",
        "service": "freightsentinel-api",
        "version": __version__,
        "emails": len(inbox),
        "results_cached": len(store.results),
        "ai": ai.describe(),
        "ai_senior": senior_ai.describe() if senior_ai else {"enabled": False, "provider": config.AI_SENIOR_PROVIDER, "model": config.AI_SENIOR_MODEL or None},
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

    try:
        data = await asyncio.to_thread(inbox.read_bytes, atts[index])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Attachment file is missing")
    doc = await asyncio.to_thread(parse_attachment, atts[index], data)
    return {
        "path": doc.path, "format": doc.fmt, "readable": doc.readable, "error": doc.error,
        "detected_type": next((d.detected_type for d in store.get(email_id).docs if d.path == atts[index]), "UNKNOWN") if store.get(email_id) else "UNKNOWN",
        "size_bytes": doc.size, "text": doc.text[:20000],
    }


# ---------------------------------------------------------------- analysis

@app.post("/api/analyse/{email_id}")
async def analyse_email(email_id: str, force: bool = Query(default=True), explain: bool = Query(default=True)):
    email = _email_or_404(email_id)
    existing = store.get(email_id)
    if existing and not force:
        return existing.model_dump(mode="json")
    try:
        res = await _analyse_and_store(email, explain_with_ai=explain)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
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
            if res.category is None:
                run.needs_review += 1
            elif res.category != "BL_COMPARISON":
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
    if run.status != "running":
        raise HTTPException(status_code=409, detail="Only a running batch can be cancelled")
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
    if run.status == "running":
        raise HTTPException(status_code=409, detail="Wait for this run to finish before retrying failures")
    key = (run_id, email_id)
    if key in _retrying or not any(f.get("email_id") == email_id for f in run.failed):
        raise HTTPException(status_code=409, detail="This email is not an available failed item")
    email = _email_or_404(email_id)
    _retrying.add(key)
    try:
        res = await _analyse_and_store(email, explain_with_ai=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Retry failed: {type(exc).__name__}; try again or inspect the source documents")
    finally:
        _retrying.discard(key)
    run.failed = [f for f in run.failed if f.get("email_id") != email_id]
    if res.category is None:
        run.needs_review += 1
    elif res.category != "BL_COMPARISON":
        run.not_applicable += 1
    elif res.status == "MISMATCH":
        run.mismatch += 1
    elif res.status == "NEEDS_REVIEW":
        run.needs_review += 1
    else:
        run.ok += 1
    store.flush(force=True)
    return {"run": run.model_dump(mode="json"), "result": res.model_dump(mode="json")}


# ---------------------------------------------------------------- human decisions

@app.post("/api/cases/{email_id}/manual-review")
async def manual_review(email_id: str, payload: ManualReviewInput):
    async with _case_lock(email_id):
        if not store.get(email_id):
            raise HTTPException(status_code=404, detail="Case not analysed yet")
        try:
            return store.record_manual_review(email_id, payload).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/cases/{email_id}/decision")
async def case_decision(email_id: str, payload: dict = Body(...)):
    async with _case_lock(email_id):
        action = str(payload.get("action", "")).lower()
        if action not in ("confirm", "escalate", "resolve", "reopen", "approve_revision", "reject_revision"):
            raise HTTPException(status_code=400, detail="Unknown review action")
        current = store.get(email_id)
        if not current:
            raise HTTPException(status_code=404, detail="Case not analysed yet")
        report = current.working_report
        if action in ("approve_revision", "reject_revision"):
            if not report or payload.get("revision_id") != report["revision_id"]:
                raise HTTPException(status_code=409, detail="The report changed; reload before reviewing")
        elif current.processing_status == "PENDING_HUMAN_APPROVAL":
            raise HTTPException(status_code=409, detail="Adopt or reject the pending revision first")
        note = str(payload.get("note") or "")[:1000] or None
        try:
            if action == "approve_revision" and report.get("kind") == "corrected_bl":
                await validate_revision(config.CACHE_DIR, current, report, analyser, inbox, store.policy)
            if action == "reject_revision":
                if current.processing_status != "PENDING_HUMAN_APPROVAL":
                    raise ValueError("There is no pending revision")
                delete_revision(config.CACHE_DIR, email_id, report)
            res = store.record_decision(email_id, action, note, by=str(payload.get("by") or "operator")[:100])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return res.model_dump(mode="json")


def _reviewable(email_id: str) -> CaseResult:
    res = store.get(email_id)
    if not res:
        raise HTTPException(status_code=404, detail="Case not analysed yet")
    if res.manual_review or res.resolved:
        raise HTTPException(status_code=409, detail="Continue human handling without further AI processing")
    if res.category != "BL_COMPARISON":
        raise HTTPException(status_code=400, detail="No BL review is required for this category")
    if res.processing_status == "PENDING_HUMAN_APPROVAL":
        raise HTTPException(status_code=409, detail="Adopt or reject the pending revision first")
    return res


@app.post("/api/cases/{email_id}/revision")
async def create_revision(email_id: str):
    async with _case_lock(email_id):
        res = _reviewable(email_id)
        try:
            report = await build_revision(res, inbox, config.CACHE_DIR, analyser, store.policy)
        except ValueError as exc:
            res.history.append({"event": "revision_generation_failed", "at": now(), "note": str(exc)})
            store.flush(force=True)
            raise HTTPException(status_code=422, detail=str(exc))
        return store.set_working_report(email_id, report).model_dump(mode="json")


@app.get("/api/cases/{email_id}/revision/{revision_id}/file")
async def download_revision(email_id: str, revision_id: str):
    res = store.get(email_id)
    candidates = [res.working_report] if res else []
    if res:
        for event in res.history:
            previous = event.get("report") or event.get("previous", {}).get("working_report")
            if previous and (previous.get("decision") or {}).get("action") == "approve_revision":
                candidates.append(previous)
    report = next((r for r in candidates if r and r["revision_id"] == revision_id), None)
    if not report or not report.get("file_available"):
        raise HTTPException(status_code=404, detail="Revision file is unavailable or has been deleted")
    path = revision_path(config.CACHE_DIR, email_id, report)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Revision file is missing")
    return FileResponse(path, filename=report["filename"])


@app.post("/api/cases/{email_id}/readings")
async def review_readings(email_id: str, payload: dict = Body(...)):
    async with _case_lock(email_id):
        original = _reviewable(email_id)
        source = original
        # Let a person review newly supplied documents instead of the original missing file.
        if original.working_report and original.working_report.get("docs"):
            source = original.model_copy(deep=True)
            from .schemas import DocInfo
            source.docs = [DocInfo.model_validate(d) for d in original.working_report["docs"]]
        try:
            report = await human_report(source, payload.get("fields", {}), str(payload.get("note") or "")[:1000], analyser, store.policy)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return store.set_working_report(email_id, report).model_dump(mode="json")


@app.post("/api/cases/{email_id}/attachments")
async def replace_attachments(email_id: str, payload: dict = Body(...)):
    async with _case_lock(email_id):
        _reviewable(email_id)
        files, note = payload.get("files"), str(payload.get("note") or "").strip()[:1000]
        if not isinstance(files, list) or len(files) != 2 or not note:
            raise HTTPException(status_code=422, detail="Supply one SI and one draft BL plus a reason")
        data = {}
        for item in files:
            if not isinstance(item, dict):
                raise HTTPException(status_code=422, detail="Invalid file data")
            name = str(item.get("name", ""))
            encoded = item.get("base64", "")
            if Path(name).name != name or Path(name).suffix.lower() not in (".txt", ".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg"):
                raise HTTPException(status_code=422, detail="Use TXT, PDF, DOCX, XLSX, PNG or JPG attachments")
            if not isinstance(encoded, str) or len(encoded) > 14_000_000:
                raise HTTPException(status_code=413, detail="Each attachment must be at most 10 MB")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                raise HTTPException(status_code=422, detail="Invalid file encoding")
            if not content or len(content) > 10_000_000 or name in data:
                raise HTTPException(status_code=422, detail="Files must be nonempty, distinct, and at most 10 MB each")
            data[name] = content
        class UploadedInbox:
            def read_bytes(self, path): return data[path]
        email = dict(_email_or_404(email_id), attachments=list(data))
        # The known BL category is held for the human-supplied replacement pair.
        email["subject"] = "Draft BL for checking"
        email["body"] = "Please compare the SI and draft BL. Attached are the SI and draft BL."
        check = await Analyser(UploadedInbox(), ai, senior_ai).analyse(email, policy=store.policy)
        report = attachment_report(check, note)
        folder = config.CACHE_DIR / 'review-inputs' / email_id / report['revision_id']
        folder.mkdir(parents=True, exist_ok=False)
        for name, content in data.items():
            (folder / name).write_bytes(content)
        return store.set_working_report(email_id, report).model_dump(mode="json")


@app.post("/api/cases/{email_id}/correction-draft")
async def correction_draft(email_id: str):
    email = _email_or_404(email_id)
    res = store.get(email_id)
    if not res:
        raise HTTPException(status_code=404, detail="case not analysed yet")
    if res.category != "BL_COMPARISON":
        raise HTTPException(status_code=400, detail="No BL correction is required for this category")
    return {"email_id": email_id, "draft": build_correction_draft(res, email), "editable": True, "sends_email": False}


# ---------------------------------------------------------------- dashboard / submission / settings

@app.get("/api/dashboard")
async def dashboard():
    summary = store.summary(len(inbox))
    open_cases = [r for r in store.all() if r.automation == "review_required" and not r.resolved]
    open_cases.sort(key=lambda r: (RISK_ORDER.get(r.risk, 9), -len(r.defect_fields), r.email_id))
    priority = [_summary_row(inbox.get(r.email_id) or {"email_id": r.email_id}, r) for r in open_cases[:12]]
    # Emails that only ask for the draft BL to be sent: a business action for a person,
    # not a case the AI failed to decide. Kept out of the review queue on purpose.
    awaiting = sorted((r for r in store.all()
                       if r.ui_status == DRAFT_REQUESTED_UI and not r.resolved),
                      key=lambda r: r.email_id)
    actions = [{"email_id": r.email_id, "subject": r.subject, "from": r.sender,
                "suggested_action": r.suggested_action, "explanation": r.explanation}
               for r in awaiting[:12]]
    runs = store.runs_list()
    return {
        "summary": summary,
        "priority": priority,
        "actions": actions,
        "actions_total": len(awaiting),
        "policy": {
            "name": store.policy,
            "decision_method": "ai",
            "description": "AI decides all seven comparisons. Uncertainty is reviewed once by the configured senior AI, then handed to a person if unresolved. Human handling is final. Strict policy asks AI to refer uncertain equivalences for review.",
        },
        "last_run": runs[0].model_dump(mode="json") if runs else None,
        "ai": ai.describe(),
        "ai_senior": senior_ai.describe() if senior_ai else {"enabled": False, "provider": config.AI_SENIOR_PROVIDER, "model": config.AI_SENIOR_MODEL or None},
    }


@app.get("/api/submission")
async def submission(download: bool = Query(default=False)):
    ids = [e["email_id"] for e in inbox.emails()]
    sub, missing = build_submission(ids, store.results)
    headers = {}
    if download:
        headers["Content-Disposition"] = 'attachment; filename="submission.json"'
    if missing:
        raise HTTPException(status_code=409, detail=f"Analyse or manually classify the remaining {len(missing)} emails before exporting the submission")
    return JSONResponse(content=sub, headers=headers)


@app.get("/api/export.csv")
async def export_csv(download: bool = Query(default=True)):
    """The operations report.

    The submission JSON answers the grader's question - one record per email, in the
    shape the organisers specified. It does not answer the operator's question, which is
    "what do I have to fix, and where does the document say so". That needs one row per
    differing field, not per email, so a person can work the list from the top and see
    both readings side by side without opening the app.

    A case with three differing fields is three rows. A case with nothing to fix is one
    row with the field columns empty, so the file still accounts for every email.
    """
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Email ID", "SI file", "BL file", "Mismatch field",
                "SI value", "BL value", "Explanation", "Final status"])
    for r in store.all():
        si = next((d.filename for d in r.docs if d.detected_type == "SI"), "")
        bl = next((d.filename for d in r.docs if d.detected_type == "BL"), "")
        status = r.status if not r.review_reason else f"{r.status} ({r.review_reason})"
        differing = [f for f in r.fields if f.match is False]
        if differing:
            for f in differing:
                w.writerow([r.email_id, si, bl, f.label, f.si_value or "", f.bl_value or "",
                            f.reason or r.headline, status])
        else:
            w.writerow([r.email_id, si, bl, "", "", "",
                        r.headline or r.explanation, status])
    # Excel reads a UTF-8 CSV as the local code page unless the file starts with a BOM,
    # which turns every non-ASCII port and party name into mojibake for the person this
    # file is actually for.
    body = "\ufeff" + buf.getvalue()
    headers = {}
    if download:
        headers["Content-Disposition"] = 'attachment; filename="freightsentinel-report.csv"'
    return Response(content=body, media_type="text/csv; charset=utf-8", headers=headers)


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
