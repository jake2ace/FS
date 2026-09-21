"""Explicit, paid classification-only evaluation. Never writes the app's case store.

Run from backend: .venv/bin/python scripts/test_classification_live.py --live --all
The previous audit is a review reference, NOT an official answer key.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config
from app.ai import AIClient
from app.data import Inbox


class EvaluationAI(AIClient):
    """Keep rejected model responses for diagnosis, without logging credentials."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.raw_by_task = {}

    async def complete_json(self, *args, **kwargs):
        obj = await super().complete_json(*args, **kwargs)
        self.raw_by_task[asyncio.current_task()] = obj
        return obj


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


async def run(args):
    if not args.live:
        raise SystemExit('Pass --live explicitly to make paid API requests.')
    if not (args.all or args.ids or args.cases):
        raise SystemExit('Choose --all, --ids, or --cases.')
    ai = EvaluationAI(mode='full', fallback_model='')
    if not ai.enabled or ai.provider != 'deepseek':
        raise SystemExit('This evaluation requires the configured DeepSeek provider.')
    inbox = Inbox(config.DATA_DIR, config.DATA_ZIP)
    expected = {}
    if args.cases:
        fixtures = json.loads(Path(args.cases).read_text())
        emails = [x['email'] for x in fixtures]
        expected = {x['email']['email_id']:x['expected'] for x in fixtures}
    else:
        emails = inbox.emails()
        if args.ids:
            requested = set(args.ids.split(','))
            emails = [x for x in emails if x['email_id'] in requested]
            if {x['email_id'] for x in emails} != requested:
                raise SystemExit('One or more requested email IDs were not found.')
    output = Path(args.output)
    if output.exists():
        raise SystemExit('Choose a new output path; previous test evidence will not be overwritten.')
    previous_path = config.CACHE_DIR / 'results.json'
    previous = {x['email_id']:x for x in json.loads(previous_path.read_text()).get('results', [])} if previous_path.is_file() else {}
    report = dict(started_at=now(), prompt_version=ai.CLASSIFY_PROMPT_VERSION,
                  prompt_sha256=hashlib.sha256(ai.CLASSIFY_SYSTEM.encode()).hexdigest(),
                  provider=ai.provider, model=ai.model, scope='classification only; isolated from app results',
                  total=len(emails), results=[])
    gate = asyncio.Semaphore(args.concurrency)

    def save():
        report['finished_at'] = now() if len(report['results']) == len(emails) else None
        report['calls'] = ai.calls
        report['api_failures'] = ai.failures
        report['invalid_results'] = sum(x['result'] is None for x in report['results'])
        report['categories'] = dict(Counter(x['result']['category'] for x in report['results'] if x['result']))
        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_suffix('.tmp')
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        tmp.replace(output)

    async def one(email):
        async with gate:
            result = await ai.classify_email(email)
            raw = ai.raw_by_task.pop(asyncio.current_task(), None)
            old = previous.get(email['email_id'], {})
            report['results'].append(dict(email_id=email['email_id'], subject=email.get('subject',''),
                input_sha256=hashlib.sha256(json.dumps(email,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                old_category=old.get('category'), old_reason=old.get('category_reason'),
                expected=expected.get(email['email_id']), result=result,
                rejected_response=raw if result is None else None))
            if len(report['results']) % 20 == 0 or len(report['results']) == len(emails):
                save()
                print(f"Completed {len(report['results'])}/{len(emails)}; invalid {report['invalid_results']}", flush=True)

    save()
    await asyncio.gather(*(one(email) for email in emails))
    report['results'].sort(key=lambda x:x['email_id'])
    save()
    print(json.dumps({k:report[k] for k in ('total','calls','api_failures','invalid_results','categories')}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--all', action='store_true')
    selection.add_argument('--ids')
    selection.add_argument('--cases')
    parser.add_argument('--concurrency', type=int, choices=range(1,9), default=4)
    parser.add_argument('--output', required=True)
    asyncio.run(run(parser.parse_args()))
