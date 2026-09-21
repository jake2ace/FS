"""Run the production pipeline against real DeepSeek, without writing case state.

Explicit --live is required. Every model response is retained for diagnosis.
No answer key or generator is used; old cases are a regression reference only.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config
from app.ai import AIClient
from app.data import Inbox
from app.pipeline import Analyser


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def digest(data):
    return hashlib.sha256(data).hexdigest()


class RecordedAI(AIClient):
    def __init__(self, tier='primary', **kwargs):
        super().__init__(mode='full', fallback_model='', **kwargs)
        self.tier = tier
        self.stages = {}

    async def complete_json(self, system, user, max_tokens=900):
        started = time.monotonic()
        response = await super().complete_json(system, user, max_tokens)
        stage = 'classification' if system == self.CLASSIFY_SYSTEM else 'document_verification'
        self.stages.setdefault(asyncio.current_task(), []).append(dict(
            stage=stage, tier=self.tier, thinking=self.thinking, reasoning_effort=self.reasoning_effort,
            seconds=round(time.monotonic()-started, 2), source_input=json.loads(user), response=response,
            last_api_error=self.last_error if response is None else None))
        return response


async def run(args):
    if not args.live:
        raise SystemExit('Pass --live to authorize real API calls.')
    output = Path(args.output)
    if output.exists():
        raise SystemExit('Use a new output path; previous evidence is preserved.')
    ai = RecordedAI()
    if not ai.enabled:
        raise SystemExit('A configured AI provider is required.')
    senior = RecordedAI(tier='senior', provider=config.AI_SENIOR_PROVIDER,
        api_key=config.AI_SENIOR_API_KEY, model=config.AI_SENIOR_MODEL,
        timeout=config.AI_SENIOR_TIMEOUT, max_rpm=config.senior_max_rpm(),
        thinking=config.AI_SENIOR_THINKING, reasoning_effort=config.AI_SENIOR_REASONING_EFFORT
    ) if config.AI_SENIOR_MODEL and config.AI_SENIOR_API_KEY else None
    if args.require_thinking_chain and not (
        ai.thinking and ai.reasoning_effort == 'high' and senior and senior.enabled
        and senior.provider == ai.provider and senior.thinking and senior.reasoning_effort == 'max'
    ):
        raise SystemExit('Expected an enabled primary (high) and senior (max) of the same provider.')
    inbox = Inbox(config.DATA_DIR, config.DATA_ZIP)
    emails = inbox.emails()
    if args.ids:
        ids = set(args.ids.split(','))
        emails = [e for e in emails if e['email_id'] in ids]
        if len(emails) != len(ids):
            raise SystemExit('Requested IDs not found.')
    elif len(emails) != 520:
        raise SystemExit('Expected the 520-email participant input bundle.')
    cache = config.CACHE_DIR / 'results.json'
    before = cache.read_bytes() if cache.exists() else b''
    old = {r['email_id']: r for r in json.loads(before).get('results', [])} if before else {}
    analyser = Analyser(inbox, ai, senior)
    report = dict(started_at=now(), finished_at=None, provider=ai.provider, model=ai.model,
        scope='production classification + attachment parsing + AI verification; isolated case state',
        prompt_version=ai.CLASSIFY_PROMPT_VERSION, total=len(emails),
        concurrency=args.concurrency, primary=ai.describe(), senior=senior.describe() if senior else None,
        prompt_sha256=digest(ai.CLASSIFY_SYSTEM.encode()), verify_prompt_sha256=digest(ai.VERIFY_SYSTEM.encode()),
        case_cache_before_sha256=digest(before),
        code_sha256={name: digest((config.BACKEND_DIR / 'app' / name).read_bytes())
                     for name in ('ai.py','ai_contract.py','pipeline.py','schemas.py','parsers.py','recovery.py')},
        records=[])
    gate = asyncio.Semaphore(args.concurrency)

    def save(finished=False):
        records = report['records']
        cases = [r['result'] for r in records if r['result']]
        bl = [r for r in cases if r['category'] == 'BL_COMPARISON']
        report.update(calls=ai.calls+(senior.calls if senior else 0),
            api_failures=ai.failures+(senior.failures if senior else 0), fallback_calls=ai.fallback_calls,
            primary=ai.describe(), senior=senior.describe() if senior else None,
            escalated=sum(any(s['tier']=='senior' and s.get('available') is not False for s in r.get('decision_chain',[])) for r in cases),
            human_handoffs=sum(any(s['tier']=='human' for s in r.get('decision_chain',[])) for r in cases),
            last_api_error=ai.last_error,
            completed=len(records), failed=sum(r['result'] is None for r in records),
            response_validation=sum(r['decision_method'] == 'response_validation' for r in cases),
            categories=dict(Counter(r['category'] for r in cases)),
            bl_statuses=dict(Counter(r['status'] for r in bl)),
            bl_review_reasons=dict(Counter(r['review_reason'] for r in bl if r['status']=='NEEDS_REVIEW')))
        if finished:
            report.update(finished_at=now(), case_cache_after_sha256=digest(cache.read_bytes() if cache.exists() else b''))
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_suffix('.tmp')
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        tmp.replace(output)

    async def one(email):
        async with gate:
            started = time.monotonic()
            result = None
            error = None
            try:
                result = (await analyser.analyse(email)).model_dump(mode='json')
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}'
            previous = old.get(email['email_id'], {})
            report['records'].append(dict(email_id=email['email_id'],
                email_sha256=digest(json.dumps(email,sort_keys=True,ensure_ascii=False).encode()),
                previous={k:previous.get(k) for k in ('category','status','review_reason','defect_fields')},
                result=result, error=error, stages=ai.stages.pop(asyncio.current_task(), [])))
            report['records'][-1]['seconds'] = round(time.monotonic()-started, 2)
            if senior:
                report['records'][-1]['stages'] += senior.stages.pop(asyncio.current_task(), [])
            if len(report['records']) % 20 == 0 or len(report['records']) == len(emails):
                save()
                print(f"Completed {len(report['records'])}/{len(emails)}; failed={report['failed']}; rejected={report['response_validation']}; escalated={report['escalated']}; human={report['human_handoffs']}", flush=True)

    save()
    await asyncio.gather(*(one(e) for e in emails))
    report['records'].sort(key=lambda x:x['email_id'])
    save(finished=True)
    print(json.dumps({k:report[k] for k in ('completed','calls','api_failures','failed','response_validation','categories','bl_statuses','bl_review_reasons')}, ensure_ascii=False))
    if report['case_cache_before_sha256'] != report['case_cache_after_sha256']:
        raise RuntimeError('Case cache changed externally during this isolated test; review before reporting.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--ids')
    parser.add_argument('--require-thinking-chain', action='store_true')
    parser.add_argument('--concurrency', type=int, choices=range(1,9), default=4)
    parser.add_argument('--output', required=True)
    asyncio.run(run(parser.parse_args()))
