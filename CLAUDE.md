# CLAUDE.md - working notes for AI coding assistants on this repo

FreightSentinel = hackathon prototype (Averis x Monash Hackathon 2026, "Shipping document verification").
Team of three beginners; the code is AI-written and human-verified. Preliminary submission deadline:
**22 Sep 2026 12:00 MYT**. Keep changes small, keep the app runnable at every step.

## What exists (verified)
- `backend/` FastAPI. `app/pipeline.py` is the heart: classify -> parse attachments -> extract 7 fields ->
  compare -> OK / MISMATCH / NEEDS_REVIEW -> explain. Rule engine works with **no AI key**; AI (OpenAI /
  Anthropic / Gemini via plain HTTPS in `app/ai.py`) is layered on top and cross-checked by the rules.
- Verified on the official bundle (520 emails): category mix matches the bundle README exactly
  (200 / 125 / 75 / 60 / 40), all 109 main-set SI+BL pairs extract all seven fields (txt / pdf / docx /
  xlsx), the 20 edge cases (email_501-520) return the documented review_reason (5 x 4). `backend/tests/`
  pins this - run `pytest -q` before every push.
- `frontend/` Next.js 14 App Router, TypeScript, plain CSS (`app/globals.css`). Pages: `/` Today Work
  Centre, `/inbox` Smart Inbox, `/cases/[id]` Case Detail, `/review` Review Queue, `/runs` Batch Run.
  All pages are client components calling same-origin `/api/*`; `next.config.mjs` rewrites them to
  `BACKEND_URL`. The frontend was type-checked but has **not yet been built with `next build`** - do that
  first and fix whatever the compiler reports.
- `data/sdoc-hackathon-bundle.zip` is the official participant bundle; the backend extracts it to
  `backend/.data/` at startup. Results are cached in `backend/.cache/results.json`.

## Rules that must not change
- Categories, statuses, review reasons and the submission shape are fixed by the organisers
  (see `backend/app/schemas.py`, `backend/app/submission.py`, and `data/.../README.md`).
- The SI is the reference. A blank value is NOT a mismatch (-> NEEDS_REVIEW / missing_value). A mismatch
  is never auto-corrected. The correction email is a draft only; nothing is ever sent.
- Any mismatch / missing / unreadable / uncertain case must end in human review; only complete, matching,
  high-confidence cases may auto-complete (see `Analyser._finish`).
- API keys live only in backend environment variables (Render). Never in the frontend, README, logs or git.
- Never read or use the organisers' answer key (`ground_truth.json` in the Docker package) or its generator.
  Only `POST /submit` of the local Docker server may be used to score `GET /api/submission`.

## Conventions
- Python 3.11, type hints, Pydantic models in `schemas.py`; keep `main.py` thin (routes call pipeline/store).
- Deterministic behaviour first; every AI call must have a rule-based fallback and a timeout.
- UI language is English, formal, navy/white/grey; red = real risk only, amber = needs attention,
  green = safe completion. No chat-bot styling.
- Commit messages: short imperative English.

## Next steps (in order)
1. `cd frontend && npm install && npm run build` - fix build errors, then `npm run dev` against a local backend.
2. Local smoke test: `uvicorn app.main:app --port 8000` + open http://localhost:3000, analyse email_004
   (MISMATCH), email_001 (OK), email_507 (NEEDS_REVIEW), run the full inbox, download the submission JSON.
3. Push to GitHub (`jake2ace/FS`), deploy backend on Render (render.yaml) and frontend on Vercel
   (root dir `frontend`, env `BACKEND_URL`).
4. Set `AI_PROVIDER` / `AI_API_KEY` on Render and confirm `GET /health` reports `ai.enabled: true`;
   compare batch results with and without AI.
5. Optional: Supabase persistence for decisions/run history; keep-alive ping for the Render free tier.
