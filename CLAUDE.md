# FreightSentinel working instructions

Hackathon project in this folder. Keep changes within the user's confirmed workflow.

## Current user decision (2026-09-20)

**AI owns ALL business judgements**: classification, document identity, seven-field extraction,
semantic/unit comparison and OK/MISMATCH/NEEDS_REVIEW. Primary uncertainty goes once to the
configured senior AI, then to human handling. A human decision is final. Never restore rule-based business judgement.

- `app/pipeline.py` loads files and accepts structured AI verdicts from `app/ai.py`.
- Program validation is limited to schema, supplied document indexes, source excerpt presence,
  complete fields and consistency of the model's own match/status/defect list.
- API failure is a visible failure, not a fabricated category/OK. Invalid returned evidence or
  structure is response_validation/NEEDS_REVIEW. User can retry or review manually.
- Classification failure creates an unclassified NEEDS_REVIEW case, visible in the human queue.
  Never fabricate a category or export an unclassified case. Previous results remain in history.
- Native BL copies use AI SI readings. Recheck the actual generated file with AI before saving,
  then check the file hash at adoption without calling AI. Adopt keeps the copy; reject deletes only that generated copy, not originals.
- Optional AI-assisted readings/replacement attachments are available before human final handling.
- The manual-review form independently records category, outcome, confirmed defect fields and handling note.
  Saving manual handling or adopting a revision prevents further AI runs, even after reopening.
  Original AI results are archived; a person confirms outcomes for original documents, not a corrected copy.
- Category enums and official export shape stay fixed. SI is the reference; blank is uncertainty.
- `docs/确认版流程说明.md` and local HTML/SVG/PNG diagram describe the current flow.

## Runtime and validation

- User chose DeepSeek V4.1 Flash: provider `deepseek`, model `deepseek-flash`, full mode,
  JSON output, primary thinking enabled with high effort (middle of low/high/max). User chose deepseek-flash with max thinking for
  the senior stage, after testing problem cases. OpenAI API code remains optional and unconfigured.
  Keys only in gitignored backend/.env. Never print them or embed them in reports.
- Main app: FastAPI + Next.js. Local backend 8000, frontend 3000. Keys never go to the frontend.
- Cache version 3 archives old results. Current local cache is backend/.cache/deepseek-ai-only.
  Preserve backend/.cache/workflow-preview and backend/.cache/deepseek-live as historical test data.
- Offline checks: `AI_PROVIDER=none AI_MODE=off backend/.venv/bin/pytest -q backend/tests`.
  Tests explicitly inject fixture AI; never run unit tests against paid live credentials.
- `backend/tests/fakes.py` may use old helper functions to produce offline fixture responses;
  production detection and review must not call classify_rules/extract_fields/compare_fields.
- Some numeric/label helpers remain for mechanical native-file editing and legacy parser tests;
  their output must not become a production business verdict.
- Frontend: `cd frontend && npm run build` (type checks enabled).
- Never read organisers' ground_truth.json or data generator. Participant inputs only.
- Record live model usage, validation failures and known limits honestly; integration success is not accuracy.
- Historical hybrid report: docs/DeepSeek-真实测试报告.md. Current AI-only report:
  docs/DeepSeek-全AI测试报告.md. No cloud deployment has been verified.
