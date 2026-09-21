# FreightSentinel — Development Challenges and How We Solved Them

> Compiled 2026-09-21. Covers every substantive problem hit between project start and the
> preliminary-round submission, how it was diagnosed, and what was changed.

---

## 1. Judgement quality

### 1.1 Too much escalation: 91 emails sent to a human for no reason

**Symptom.** After a full 520-email run, precision was fine, but 91 emails came back as
`NEEDS_REVIEW / missing_attachment` and went to the human queue. The queue was drowned in them,
and the cases that genuinely needed a person were buried.

**Diagnosis.** We grouped the 91 bodies by template and found they were all one kind of request:
"please send us the draft BL so we can check it." Re-reading the prompt sentence by sentence, we
found the definition of "a document that should be here is absent" was written too widely, so the
model treated "the comparison has not started yet" as "the comparison failed."

**Root cause.** These emails have nothing to compare. The sender is asking us to *send* a draft BL,
not reporting a lost attachment. The email is neither a successful comparison nor a failed one — the
process simply has not reached the comparison step. The prompt gave the model no third option, so it
reached for the nearest label.

**Fix.** The prompt in `backend/app/ai.py` now draws the line explicitly: an email that asks us to
*compare* an SI against a draft BL when a file is missing is `missing_attachment`; an email that asks
us to *send* a draft BL for later checking has lost nothing, is reported as `OK` with a null
`review_reason`, and the action the recipient should take goes into `suggested_action`.

**Lesson.** When a prompt defines a category, it must also say what does *not* belong in it.
Otherwise the model files every ambiguous case under the closest available label.

### 1.2 The prompt was fixed but the result got worse: all 91 became `unreadable`

**Symptom.** After the fix above, the 91 emails did not become `OK`. They became
`NEEDS_REVIEW / unreadable` — worse than before.

**Diagnosis.** Two fields in the run record gave it away. `decision_method` was
`response_validation`, meaning the verdict was overridden by our own code, not produced by the model.
And the model's own `unconfirmed_ai_assessment` was the correct `OK`. The AI had judged it right and
the program had thrown the judgement away.

**Root cause.** `_validate_response` in `pipeline.py` enforced a hard rule: any `OK` or `MISMATCH`
must be backed by one readable SI and one readable BL, otherwise the model is assumed to be
hallucinating. The rule is correct in general — it stops the model from deciding without having seen
the documents — but it had no way of knowing that a "please send the draft" email is not supposed to
have documents at all.

**Fix.** The email's `intent` is now threaded into `_validate_response`, with one bypass:

```python
awaiting_draft = v.status == 'OK' and not docs and intent == 'request_draft'
if not awaiting_draft and v.status in ('OK','MISMATCH') and (...):
    raise ValueError('AI successful comparison requires one readable SI and one readable BL.')
```

**Lesson.** After changing a prompt, check whether the validation layer needs to change with it.
A correct AI verdict that the validator rejects looks exactly like a wrong AI verdict in the final
output, which makes it very easy to misdiagnose and keep "fixing" the wrong thing.

### 1.3 Comparing the printed label instead of the value

A handful of cases were reported as `MISMATCH` although the two documents agreed. `To the Order of:`
and `Consignee:` are two printed wordings of the same field, and the model was treating the label
text as part of the value. The prompt now states that the printed label is not part of the value:
compare only what follows the label, and never report a difference that rests on label wording alone.

### 1.4 Iterating the classification prompt

The classification prompt went through seven versions. Each one was run against a pre-check set, a
supplementary set and then the full 520, with the per-email comparison written to `docs/`. The main
problems solved along the way:

- A misleading subject line overriding the real intent in the body.
- The boundary between a bulk "submit your SI" reminder (`GENERAL`) and a shipment-specific SI
  request (`SI_REQUEST`).
- Forcing the model to emit evidence first, then the category, then the reason — so it cannot decide
  first and look for justification afterwards.
- Requiring evidence to be exact, contiguous quotations from the body, with no paraphrase and no
  ellipses.

**Result.** Two consecutive full runs over all 520 emails agreed on the category distribution, the
number of emails entering comparison, and the mismatch and escalation counts. Both runs are recorded
email by email and can be re-checked.

---

## 2. Usability

**A status word the brief never used.** The UI had invented `High risk`, while the official closed
vocabulary is only `OK / MISMATCH / NEEDS_REVIEW`. Renamed to `Mismatch`.

**A label pointing the wrong way.** "Awaiting draft BL" implied we were waiting for the counterparty,
when in reality *we* have to send the BL. Anyone reading the screen would have waited for the wrong
thing. Renamed to `Draft BL requested`, with the required action on the card.

**A rename that missed two counters.** After the rename, two count queries still matched the old
string and the dashboard tile showed 0. Fixed by defining `DRAFT_REQUESTED_UI` once in `schemas.py`
and referencing it everywhere, so the string cannot drift apart again.

**Guidance pointing at the wrong action.** The first version told the user where to edit data, but in
this workflow a person *decides*; they do not edit. And if no run has happened yet, the first step is
to run the analysis. The guide strip is now state-aware, and a priority panel marks which case to
handle first. All copy was rewritten around "sorted for you / you decide".

**A legend nobody needed.** The boxed legend beside the donut was replaced with direct labelling on
the chart itself, with leader lines.

**Donut labels clipped at the top.** Invisible when reading the code; obvious the moment the same
geometry was rendered to a PNG and looked at. The collision resolver now clamps at the top as well
as pushing back from the bottom.

**Chrome translating the UI into nonsense.** Chrome's auto-translate turned `Status` into 地位 and
`Draft BL` into 选秀 BL, colliding with the app's own EN/ZH switch. Fixed with `translate="no"`,
`className="notranslate"` and the `google: 'notranslate'` meta tag.

**Duplicate keys in the translation dictionary (twice).** Duplicate keys in `LanguageProvider.tsx`
break the TypeScript build outright. Every dictionary edit now runs a dedupe pass first. Related
finding: a string with a number embedded in it cannot be translated as one node — the number and the
prose have to be separate nodes.

**A batch edit that deleted the wrong block.** A string-slice edit of `page.tsx` matched an anchor
that also appeared inside the JSX being inserted, and removed the wrong region. Now every scripted
edit uses a unique multi-line anchor and is compiled immediately afterwards.

---

## 3. Deployment and operations

**Render never auto-deploys.** `autoDeploy: true` is set in `render.yaml`, but in practice a push has
never triggered a deploy. Every backend change needs a manual *Deploy latest commit*. This is written
into the README so teammates do not assume a push is enough.

**UptimeRobot reported the service as down (405).** UptimeRobot sends `HEAD` by default, and
FastAPI's `@app.get` — unlike Starlette's `Route` — does not add `HEAD` automatically. The free plan
allows neither a different method nor custom accepted status codes, so the fix had to be on our side:
`@app.api_route("/health", methods=["GET", "HEAD"])`, and the same for `/api/health`.

**Free instances sleep.** A free Render instance sleeps after 15 idle minutes and cold-starts slowly,
which is a real risk during a live demo. UptimeRobot now pings every 5 minutes; the free tier's 750
instance-hours per month is enough to cover this.

**`CACHE_DIR` must never reach the cloud.** Locally it is an absolute macOS path; setting it on
Render breaks startup. `render.yaml` pins 19 environment variables and deliberately omits this one,
with a comment explaining why.

**Too many variables for a teammate to configure by hand.** Solved with a Render Blueprint: every
value is pinned in `render.yaml` and only `AI_API_KEY` is marked `sync: false` for manual entry. One
trap is documented in the file itself — `AI_SENIOR_PROVIDER` must equal `AI_PROVIDER`, or the senior
review stage silently disables itself. It does not error; it just stops working.

---

## 4. Git and credentials

**No GitHub access from the development sandbox.** The proxy blocks GitHub (403), so every `push`
and `pull` had to be run in the local terminal. The workflow became: generate the command, run it
locally, confirm from the output.

**A stale `.git/index.lock`.** An interrupted `git add --dry-run` left a lock file that blocked all
subsequent git operations.

**A broken `&&` chain.** `git add -A && git commit && git push` silently stops after `git commit`
when there is nothing to commit, because that returns a non-zero status. Commands are now issued one
at a time.

**An AI listed as a repository contributor.** Commit-message trailers had added it. Removed with
`git filter-branch --msg-filter` and a `--force-with-lease` push.

**Credentials pasted into chat (twice)** — once a GitHub PAT, once a Google Gemini API key. Both were
revoked and regenerated immediately. `.gitignore` covers `.env` and `.env.*`; keys exist only in the
local `.env` and the Render environment panel, are never sent to the frontend, and are never logged.

---

## 5. The Gemini 3.8 Flash attempt (2026-09-21 — unsuccessful)

This was the last technical experiment before submission. **The outcome is: do not switch for the
preliminary round.** The full record is kept here.

**Motivation.** Move to Google `gemini-3.8-flash` while keeping the existing two-stage design —
second-tier thinking for the primary judgement, top tier for the senior review.

**What we found first.** The Gemini branch in `backend/app/ai.py` never wired thinking at all.
`thinking` and `reasoning_effort` only took effect on the DeepSeek path; the Gemini branch was an
early placeholder that sent only `temperature` and `maxOutputTokens`. Switching as-is would have
meant the requested tiers had nowhere to apply, the two-stage review would degrade into running the
same model twice with identical parameters, and truncated output would be swallowed as a valid answer.

**The adapter.** After checking Google's current documentation (the thinking parameter moved from
`thinkingBudget` to `thinkingLevel`), the branch was rewritten:

| Concern | Implementation |
|---|---|
| Thinking depth | `generationConfig.thinkingConfig.thinkingLevel` |
| Tier mapping | project `high` → Gemini `medium`; project `max` → Gemini `high` |
| Thinking off | `low` (`gemini-3.8-flash` rejects `minimal`) |
| Output budget | raised to 32768 when thinking is on — thinking and answer share one budget |
| Sampling | Gemini 3 rejects `temperature`, so it is omitted; older models still receive it |
| Legacy models | `gemini-2.x` falls back to `thinkingBudget` |
| Truncation | `finishReason == "MAX_TOKENS"` raises and the case escalates |
| Thought summaries | parts flagged `thought: true` are skipped |
| Empty replies | raise explicitly instead of returning an empty string |

Six code paths were exercised against synthesised HTTP responses and all behaved as intended.

**Four runs, three distinct failures.**

| Run | Setup | Result |
|---|---|---|
| 1 | 6 emails, concurrency 2 | The test script hard-required DeepSeek and exited |
| 2 | Same, script made provider-agnostic | 12/12 calls `402 Payment Required` — billing not enabled for the project, and `gemini-3.8-flash` is not on the free tier |
| 3 | After enabling billing | 39 calls, 34 × `503 Service Unavailable`. The 5 that succeeded classified correctly, proving the adapter works |
| 4 | 3 emails, concurrency 1 | 21 calls, 20 failures (95%) — concurrency ruled out |

(A `EOF marker not found` warning from pypdf also appeared: a PDF attachment missing its standard
end-of-file marker. It is a warning, not an error, and parsing continued.)

**Conclusion.** The code is correct and billing is active; the failure is capacity on Google's side.
The requests are well-formed — the five successful calls prove it — and the rest were refused.

Given that the DeepSeek configuration has been reproduced on two consecutive full runs, that fewer than
twelve hours remained and the demo video was unrecorded, and that any model change requires another
full 520-email validation run of unknown quality, **the preliminary round stays on DeepSeek.** The
Gemini adapter is merged and kept; the Gemini `.env` is saved as `backend/.env.gemini.bak` and the
switch is one command.

**Next.** If we reach the final, re-evaluate: re-test Google's availability, run the full 520 emails
on both providers, and decide from the numbers rather than from preference.

---

## 6. What actually worked

1. **Group before locating.** The 91 misjudged emails were not found one by one. Grouping the bodies
   by template made it obvious they were one problem, which led straight to the offending sentence.
2. **Know who made the decision.** `decision_method` and `unconfirmed_ai_assessment` saved a whole
   evening. Without them we would have kept editing the prompt and kept making it worse.
3. **Render it and look at it.** A clipped chart label cannot be found by reading code.
4. **One change at a time, verified immediately.** Every frontend change runs `npm run build`; every
   backend change runs the offline tests. Stacked changes cannot be attributed.
5. **Never tune against the answer key.** The organisers' reference labels were never opened. Every
   prompt change was argued from what the email itself says, so the prompt is not overfitted to these
   520 emails.

---

## Appendix — production configuration

| Item | Value |
|---|---|
| Provider | DeepSeek |
| Primary | `deepseek-flash`, `thinking=true`, `reasoning_effort=high` |
| Senior review | `deepseek-flash`, `thinking=true`, `reasoning_effort=max` |
| Escalation trigger | only when `status == NEEDS_REVIEW` |
| Frontend | Next.js 14.2.15 / React 18.3.1 / TypeScript 5.5.4 on Vercel |
| Backend | FastAPI + uvicorn, Python 3.11.9, on Render's free tier |
| Keep-alive | UptimeRobot, 5-minute interval |

Most recent full run: 520 emails analysed, 220 document comparisons, 63 safely auto-completed,
46 mismatches, 20 needing human review, 91 draft-BL requests, 0 failures; 16 min 55 s wall clock;
740 primary calls with 0 failures, 44 senior calls with 4 failures.
