# FreightSentinel

**Shipping document verification - from a shared inbox to a discrepancy report.**
Built for the Averis x Monash Hackathon 2026 (Shipping Document Verification use case).

> 中文版说明见 **[README.zh-CN.md](README.zh-CN.md)**（部署步骤与环境变量中文对照）。

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
                                                            │                 ──> AI provider (DeepSeek / OpenAI / Anthropic / Gemini)
                                                            │                 ──> AI verdict + response/source validation
                                                            └──> results cache (JSON)
```

The browser never talks to the AI provider and never sees the API key. The frontend proxies `/api/*`
server-side to the backend; the key exists only as an environment variable on the backend host.

| Layer | Technology | Responsibility |
|---|---|---|
| Frontend | React + Next.js 14 (TypeScript) | Today Work Centre, Smart Inbox, Case Detail, Review Queue, Batch Run |
| Backend | Python 3.11 + FastAPI + Pydantic | inbox access, analysis pipeline, batch runs, human decisions, submission export |
| Parsing | pdfplumber, python-docx, openpyxl | attachment text with a layout-aware PDF reader (bold label / regular value) |
| AI | one provider with JSON output, via plain HTTPS | email intent + category, document type + seven fields with evidence |
| Comparison | AI structured response | semantic comparison, unit interpretation, seven match flags and final status |
| Validation | Python / Pydantic | response shape, complete fields, source excerpts and consistency of AI status |

**AI owns business decisions.** The configured model classifies emails, identifies documents, extracts all
seven fields, interprets equivalent names/units, compares values and returns the final status with evidence.
Python reads files and validates response structure, source excerpts and internal consistency; it does not
compute its own business verdict or override AI readings. Invalid AI output goes to review. Missing AI
configuration or API failure is a visible technical failure with retry, never a rules-only success.
`AI_MODE=full` is the normal configuration; `off` disables analysis.

## Repository layout

```
backend/    FastAPI service  (app/main.py = routes, app/pipeline.py = the analysis, tests/ = pytest)
frontend/   Next.js app      (app/ = pages, components/, lib/api.ts)
data/       official participant bundle (sdoc-hackathon-bundle.zip) - extracted at backend startup
docs/       confirmed workflow diagram + workflow contract
render.yaml Render blueprint for the backend
```

Development test records (per-email JSON/CSV runs and their reports) are kept on the working machine and
are deliberately not committed - see `.gitignore`.

## Environment variables

Every value below is read from the process environment. Locally they come from `backend/.env`
(gitignored, created from `backend/.env.example`); in the cloud they are set in the host's dashboard.
**No key is ever committed, logged, or sent to the browser.**

### Backend (Render → Service → Environment)

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `AI_PROVIDER` | yes | `none` | `deepseek` \| `openai` \| `anthropic` \| `gemini` \| `none` |
| `AI_API_KEY` | yes | – | provider key. Backend only. Set it in the host dashboard, never in the repo |
| `AI_MODEL` | no | provider default | competition config: `deepseek-flash`. Defaults per provider in `app/config.py` |
| `AI_MODE` | no | `full` | `full` = AI decides every case; `off` = analysis disabled |
| `AI_THINKING` | no | `false` | extended thinking on the primary model (`true` in the competition config) |
| `AI_REASONING_EFFORT` | no | `high` | `low` \| `high` \| `max` (`medium` maps to `high`) |
| `AI_TIMEOUT` | no | `60` | seconds before a single AI call is abandoned (`240` recommended) |
| `AI_FALLBACK_MODEL` | no | – | same-provider backup used while the primary returns 429/503; `none` disables |
| `AI_MAX_RPM` | no | provider default | requests per minute per model; `0` = no pacing (paid tier) |
| `BATCH_CONCURRENCY` | no | `4` | parallel analyses during a full-inbox run |
| `AUTOMATION_POLICY` | no | `standard` | `standard` \| `strict`; review guidance for the AI, not a program threshold |
| `CORS_ORIGINS` | no | `*` | browsers allowed to call the API directly; the frontend proxies server-side |
| `AI_SENIOR_PROVIDER` | no | `openai` | provider for the second-pass review stage |
| `AI_SENIOR_MODEL` | no | – | second-pass model; **blank disables the senior stage** |
| `AI_SENIOR_API_KEY` | no | reuses `AI_API_KEY` | only needed when the senior provider differs from the primary |
| `AI_SENIOR_THINKING` | no | `false` | extended thinking on the senior model |
| `AI_SENIOR_REASONING_EFFORT` | no | `high` | competition config: `max` |
| `AI_SENIOR_TIMEOUT` | no | `120` | seconds before a senior call is abandoned |
| `AI_SENIOR_MAX_RPM` | no | derived | `0` = no pacing |
| `PYTHON_VERSION` | Render only | `3.11.9` | already set in `render.yaml` |

### Frontend (Vercel → Project → Settings → Environment Variables)

| Variable | Required | Example | Meaning |
|---|---|---|---|
| `BACKEND_URL` | yes | `https://freightsentinel-api.onrender.com` | FastAPI base URL, no trailing slash |

The frontend has **no** AI variables. Anything given to the frontend is readable by any visitor, so the
provider key never appears there.

### Competition configuration (DeepSeek V4.1 Flash)

```
AI_PROVIDER=deepseek
AI_MODEL=deepseek-flash
AI_MODE=full
AI_THINKING=true
AI_REASONING_EFFORT=high
AI_FALLBACK_MODEL=none
AI_SENIOR_PROVIDER=deepseek
AI_SENIOR_MODEL=deepseek-flash
AI_SENIOR_REASONING_EFFORT=max
AI_TIMEOUT=240
AI_SENIOR_TIMEOUT=240
```

The client calls `https://api.deepseek.com/chat/completions` with JSON output. Model naming follows the
[official DeepSeek API guide](https://api-docs.deepseek.com/zh-cn/). An enabled provider is configuration
evidence only; live verification requires successful calls and per-case `ai_used` / document
`extraction_method` results.

## Run locally

Backend (Python 3.11):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then fill AI_API_KEY in .env
uvicorn app.main:app --reload --port 8000
# http://localhost:8000/health   http://localhost:8000/docs
```

`backend/.env` is loaded automatically by `app/config.py`; real environment variables always win, so the
same code runs unchanged on Render.

Frontend (Node 18+):

```bash
cd frontend
npm install
BACKEND_URL=http://localhost:8000 npm run dev
# http://localhost:3000
```

Tests (no paid API calls - fixtures only):

```bash
cd backend && AI_PROVIDER=none AI_MODE=off .venv/bin/pytest -q tests
```

## Deploy

### 1. Backend on Render

1. Render → **New +** → **Blueprint** → select this repository (it reads `render.yaml`).
2. Render asks for **one** value: `AI_API_KEY`. Paste the provider key. Every other variable -
   provider, both models, thinking effort, timeouts, rate limits, concurrency - is pinned in
   `render.yaml`, so the cloud run matches the tested local configuration.
3. Deploy, then check `https://<service>.onrender.com/health` - it reports service, data and AI status.

The free plan sleeps after 15 minutes without traffic; keep it warm during judging with an uptime monitor
pinging `/health` every 5 minutes. The blueprint does not install Tesseract/Poppler, so local OCR recovery
is unavailable on that host.

### 2. Frontend on Vercel

1. Vercel → **Add New** → **Project** → import this repository.
2. **Root Directory = `frontend`**.
3. Environment Variables: `BACKEND_URL = https://<service>.onrender.com`.
4. Deploy. The rewrite in `next.config.mjs` proxies `/api/*` to the backend server-side, so the browser
   needs no CORS and receives no backend URL or key in its bundle.

### 3. Key rotation

The key exists only in the Render dashboard and in the local gitignored `backend/.env`. To rotate it,
change the value in Render and redeploy; nothing in the repository or the frontend has to change.

## API

| Route | Purpose |
|---|---|
| `GET /health` · `GET /api/health` | service, data and AI status |
| `GET /api/emails` · `GET /api/emails/{id}` | inbox list / one email with attachment metadata and result |
| `GET /api/emails/{id}/attachments/{index}/text` | extracted attachment text |
| `POST /api/analyse/{id}` · `GET /api/results` · `GET /api/results/{id}` | analyse one email / stored cases |
| `POST /api/runs/full-inbox` · `GET /api/runs` · `GET /api/runs/{id}` · `POST /api/runs/{id}/cancel` · `POST /api/runs/{id}/retry/{email_id}` | batch processing with visible failures and retry |
| `POST /api/cases/{id}/decision` | confirm · escalate · resolve · reopen (human in the loop) |
| `POST /api/cases/{id}/manual-review` | human category, outcome, defect fields, handling note |
| `POST /api/cases/{id}/revision` · `GET /api/cases/{id}/revision/{revision_id}/file` | generate / download a corrected BL copy |
| `POST /api/cases/{id}/readings` · `POST /api/cases/{id}/attachments` | corrected readings / replacement attachments |
| `POST /api/cases/{id}/correction-draft` | editable correction email text - never sent by the system |
| `GET /api/submission` · `GET /api/submission/status` | output in the official `sample_submission.json` shape (all 520 email ids) |
| `GET /api/dashboard` · `GET/POST /api/settings/policy` · `GET /api/categories` | Today Work Centre data · automation policy · category enum |

## Outcome contract

| Situation | status | review_reason | UI |
|---|---|---|---|
| all seven fields agree | `OK` | – | *No mismatch detected* -> Safe to complete (auto under policy) |
| at least one field differs | `MISMATCH` | – | High risk, `defect_fields` listed with SI / BL values |
| comparison requested but no attachment / only the SI | `NEEDS_REVIEW` | `missing_attachment` | Needs review |
| second attachment is an invoice / packing list / certificate | `NEEDS_REVIEW` | `wrong_doc_type` | Needs review |
| empty, corrupt or image-only file | `NEEDS_REVIEW` | `unreadable` | Needs review |
| a required field is blank or a placeholder | `NEEDS_REVIEW` | `missing_value` | Needs review |
| request to *send* the draft BL (nothing attached yet) | `NEEDS_REVIEW` | `missing_attachment` | Needs review |
| other categories | `OK` | – | No action |

A blank or invalid value is not a discrepancy. All seven comparisons must complete reliably before an
OK or MISMATCH is returned. Unknown document roles are never inferred from filenames alone.

The confirmed workflow is in [the flowchart](docs/FreightSentinel-确认版流程图.html), with a
[scalable SVG](docs/FreightSentinel-确认版流程图.svg) and the
[workflow contract](docs/确认版流程说明.md).

## Corrected BL copies and human review

For a verified mismatch, **Generate corrected BL copy** changes only the differing fields in a separate
TXT / DOCX / XLSX / PDF file, using AI-extracted SI values. AI must re-read the actual generated file and
confirm all seven fields. PDF editing is conservative: ambiguous positions, unsupported fonts, overlaps or
insufficient space are reported as requiring manual editing; no unverified copy is saved.

- `PENDING_HUMAN_APPROVAL`: a rechecked copy or human-reviewed report awaits adoption.
- **Adopt revision & keep copy** verifies the saved file hash and retains it; adoption makes no new AI call.
- **Reject & delete copy** deletes the generated backend copy and returns the case to human review. The
  audit record remains. Files already downloaded elsewhere are outside backend control.
- Human reviewers can supply replacement SI/BL attachments or correct all seven extracted readings. The
  final human-review form can complete handling independently of AI.
- Original attachment detection and official export remain unchanged by later corrections. Reanalysis is
  blocked after human handling; reopening stays with a person.
- Unknown categories remain in the human queue and block complete submission export until classified.
- Uncertain primary results are reviewed once by the configured senior model; unresolved cases go to a
  person. No second provider is required.

Generated files live under `backend/.cache/revisions/<email_id>/<revision_id>/`. Results, human review
history and batch history are persisted under `CACHE_DIR` (gitignored).

### Local OCR recovery

Install Tesseract (English data) and Poppler (`pdftoppm`) on the backend host to enable OCR. The pipeline
first tries another PDF reader, then bounded local OCR for existing PDFs/images. Missing or wrong documents
are never synthesized. Recovery failure is visible in document evidence. The Render blueprint does not
install these OS binaries.

## Evaluation boundary

Only the participant bundle is used as input. The organisers' self-evaluation endpoint (`POST /submit` of
the local Docker server) may be used to score `GET /api/submission`; the private reference labels are never
read.

Offline workflow tests use an explicit fake model in `backend/tests/fakes.py`; they do not call paid APIs
and do not prove model accuracy. Full-inbox live-run records are kept on the development machine and are
not part of this repository.
