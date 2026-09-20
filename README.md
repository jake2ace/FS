# FreightSentinel

**Shipping document verification - from a shared inbox to a discrepancy report.**
Built for the Averis x Monash Hackathon 2026 (Shipping Document Verification use case).

FreightSentinel reads the shared operations inbox, tells the five kinds of emails apart, and for every
BL-comparison request it reads the Shipping Instruction (SI) and the draft Bill of Lading (BL), aligns the
seven shipment fields by meaning, and reports **exactly** what differs - with the source evidence next to
it. Anything the system cannot decide safely (missing attachment, wrong document, unreadable file, blank
value) goes to a person with the reason, never a guess.

```
Official Inbox -> Smart Inbox (classify) -> Analyse (extract + compare) -> Risk Radar -> Review or Safe Completion
```

## Architecture

```
Browser ──> Next.js frontend (Vercel) ──/api/*──> FastAPI backend (Render) ──> parsers (txt/pdf/docx/xlsx)
                                                            │                 ──> AI provider (OpenAI / Anthropic / Gemini) for classification + document reading
                                                            │                 ──> deterministic comparator + safety rules
                                                            └──> results cache (JSON) ── optional Supabase later
```

| Layer | Technology | Responsibility |
|---|---|---|
| Frontend | React + Next.js 14 (TypeScript) | Today Work Centre, Smart Inbox, Case Detail, Review Queue, Batch Run |
| Backend | Python 3.11 + FastAPI + Pydantic | inbox access, analysis pipeline, batch runs, human decisions, submission export |
| Parsing | pdfplumber, python-docx, openpyxl | attachment text with a layout-aware PDF reader (bold label / regular value) |
| AI | one provider with JSON output, via plain HTTPS | email intent + category, document type + seven fields with evidence |
| Comparison | deterministic Python rules | normalisation (labels, ports, legal suffixes, units) and mismatch detection |
| Safety | automation policy (standard / strict) | only complete, matching, high-confidence cases auto-complete |

**AI vs rules.** The model is used for *understanding* (what the email wants, what a document says); code
owns the *decision* (normalise, compare, decide, explain). Every AI result is cross-checked by the rule
engine and the case is downgraded to human review when they disagree. With no API key configured the rule
engine runs alone, so the workflow always works end-to-end.

## Repository layout

```
backend/    FastAPI service  (app/main.py = routes, app/pipeline.py = the analysis, tests/ = pytest)
frontend/   Next.js app      (app/ = pages, components/, lib/api.ts)
data/       official participant bundle (sdoc-hackathon-bundle.zip) - extracted at backend startup
render.yaml Render blueprint for the backend
```

## Run locally

Backend (Python 3.11):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # optional: add AI_PROVIDER / AI_API_KEY
export $(grep -v '^#' .env | xargs)                     # or set the variables in your shell
uvicorn app.main:app --reload --port 8000
# http://localhost:8000/health   http://localhost:8000/docs
```

Frontend (Node 18+):

```bash
cd frontend
npm install
BACKEND_URL=http://localhost:8000 npm run dev
# http://localhost:3000
```

Tests:

```bash
cd backend && pytest -q
```

## Deploy

**Backend on Render** - New + -> Blueprint -> select this repository (uses `render.yaml`). When prompted set
`AI_PROVIDER` (`openai` | `anthropic` | `gemini` | `none`) and `AI_API_KEY`. The service exposes
`https://<name>.onrender.com/health`. The free plan sleeps after 15 minutes without traffic; keep it warm
during judging with an uptime monitor that pings `/health` every 5 minutes.

**Frontend on Vercel** - Import the repository, set **Root Directory = `frontend`**, add the environment
variable `BACKEND_URL=https://<name>.onrender.com`, deploy. The Next.js rewrite in `next.config.mjs`
proxies `/api/*` to the backend, so the browser never needs CORS and no backend URL or key is shipped in
the client bundle.

Environment variables (backend):

| Variable | Default | Meaning |
|---|---|---|
| `AI_PROVIDER` | `none` | `openai`, `anthropic`, `gemini` or `none` |
| `AI_API_KEY` | – | provider key (backend only, never in the frontend) |
| `AI_MODEL` | provider default | e.g. `gpt-4.1-mini`, `claude-3-5-haiku-latest`, `gemini-2.5-flash` |
| `AI_MODE` | `full` | `full` = AI on every email/document, `assist` = only when rules are unsure, `off` |
| `BATCH_CONCURRENCY` | `4` | parallel analyses during a batch run |
| `AUTOMATION_POLICY` | `standard` | `standard` (80% threshold) or `strict` (90%) |

## API

| Route | Purpose |
|---|---|
| `GET /health` | service, data and AI status |
| `GET /api/emails` · `GET /api/emails/{id}` | inbox list / one email with attachment metadata and result |
| `POST /api/analyse/{id}` · `GET /api/results/{id}` | analyse one email / read the stored case |
| `POST /api/runs/full-inbox` · `GET /api/runs/{id}` · `POST /api/runs/{id}/retry/{email_id}` | batch processing with visible failures and retry |
| `POST /api/cases/{id}/decision` | confirm · escalate · resolve · reopen (human in the loop) |
| `POST /api/cases/{id}/correction-draft` | editable correction email text - never sent by the system |
| `GET /api/submission` | output in the official `sample_submission.json` shape (all 520 email ids) |
| `GET /api/dashboard` · `GET/POST /api/settings/policy` | Today Work Centre data · automation policy |

## Outcome contract

| Situation | status | review_reason | UI |
|---|---|---|---|
| all seven fields agree | `OK` | – | *No mismatch detected* -> Safe to complete (auto under policy) |
| at least one field differs | `MISMATCH` | – | High risk, `defect_fields` listed with SI / BL values |
| comparison requested but no attachment / only the SI | `NEEDS_REVIEW` | `missing_attachment` | Needs review |
| second attachment is an invoice / packing list / certificate | `NEEDS_REVIEW` | `wrong_doc_type` | Needs review |
| empty, corrupt or image-only file | `NEEDS_REVIEW` | `unreadable` | Needs review |
| a required field is blank or a placeholder | `NEEDS_REVIEW` | `missing_value` | Needs review |
| request to *send* the draft BL (nothing attached yet) | `OK` | – | Awaiting draft BL |
| other categories | `OK` | – | No action |

A blank value is not a discrepancy, and a mismatch is never auto-corrected: the correction email is a draft a
person edits and sends.

## Evaluation boundary

Only the participant bundle is used as input. The organisers' self-evaluation endpoint (`POST /submit` of
the local Docker server) may be used to score `GET /api/submission`; the private reference labels are never
read.
