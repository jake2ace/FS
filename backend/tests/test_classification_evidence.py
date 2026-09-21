"""Source validation and persistence, not tests of a model's semantic accuracy."""
import copy

import pytest

from app.ai import AIClient
from app.pipeline import AIUnavailable, Analyser
from app.store import Store
from tests.test_workflow import EMAIL, MemoryInbox, inputs, client
from tests.fakes import FixtureAI


def response():
    return dict(category='GENERAL', confidence=.8, intent='other',
                reason='An operational reminder requests action on pending items.',
                evidence=[dict(source='body', quote='Kindly action the pending items.')])


NOTICE = dict(EMAIL, subject='Billing Process Completed',
              body='Dear Team,\n\nKindly action the pending items.\nRegards, Documentation')


@pytest.mark.parametrize('bad', ['absent', 'empty', 'invented', 'wrong_source', 'whitespace', 'status_as_category'])
async def test_invalid_classification_is_rejected_without_fallback(monkeypatch, bad):
    obj = response()
    if bad == 'absent': obj.pop('evidence')
    elif bad == 'empty': obj['evidence'] = []
    elif bad == 'invented': obj['evidence'][0]['quote'] = 'No action required.'
    elif bad == 'wrong_source': obj['evidence'][0]['source'] = 'subject'
    elif bad == 'whitespace': obj['evidence'][0]['quote'] = '  \n '
    elif bad == 'status_as_category': obj['category'] = 'OK'
    ai = AIClient(provider='deepseek', api_key='offline', fallback_model='')
    async def complete(*args, **kwargs): return copy.deepcopy(obj)
    monkeypatch.setattr(ai, 'complete_json', complete)
    assert await ai.classify_email(NOTICE) is None


async def test_whitespace_changes_do_not_invalidate_real_excerpt(monkeypatch):
    ai = AIClient(provider='deepseek', api_key='offline', fallback_model='')
    async def complete(*args, **kwargs): return response()
    monkeypatch.setattr(ai, 'complete_json', complete)
    out = await ai.classify_email(dict(NOTICE, body='Kindly action\n the pending items.'))
    assert out['evidence'][0]['quote'] == 'Kindly action the pending items.'


async def test_pipeline_rejects_invented_evidence_even_from_another_client():
    ai = FixtureAI()
    async def classify(email):
        obj = response(); obj['evidence'][0]['quote'] = 'Invented source text'
        return obj
    ai.classify_email = classify
    result = await Analyser(MemoryInbox(inputs()), ai).analyse(NOTICE)
    assert result.category is None and result.status == 'NEEDS_REVIEW'
    assert 'source evidence' in result.explanation


async def test_evidence_and_prompt_version_survive_storage(tmp_path):
    ai = FixtureAI()
    async def classify(email): return response()
    ai.classify_email = classify
    result = await Analyser(MemoryInbox(inputs()), ai).analyse(NOTICE)
    store = Store(tmp_path); store.put(result); store.flush(force=True)
    restored = Store(tmp_path); restored.load()
    saved = restored.get(NOTICE['email_id'])
    assert saved.category_evidence[0].quote == 'Kindly action the pending items.'
    assert saved.category_prompt_version == AIClient.CLASSIFY_PROMPT_VERSION
    assert saved.category_reason == response()['reason']


def test_failed_evidence_handoff_preserves_previous_case_in_history(client, monkeypatch):
    api, main, _ = client
    before = api.get('/api/results/email_test').json()
    async def classify(email): return response()  # Quote is not present in EMAIL.
    monkeypatch.setattr(main.ai, 'classify_email', classify)
    failed = api.post('/api/analyse/email_test?force=true')
    assert failed.status_code == 200
    current = api.get('/api/results/email_test').json()
    assert current['category'] is None and current['status'] == 'NEEDS_REVIEW'
    assert current['history'][-1]['previous'] == {k:v for k,v in before.items() if k != 'history'}
