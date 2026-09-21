"""Bounded escalation and terminal human decisions; all model responses are offline fixtures."""
import copy
import httpx
import pytest
from app.ai import AIClient
from app.pipeline import Analyser
from app.store import Store
from tests.test_ai_only import ResponseAI, response_for
from tests.test_workflow import EMAIL, MemoryInbox, inputs, client

class CountedAI(ResponseAI):
    def __init__(self, response, classification='valid'):
        super().__init__(response)
        self.classification = classification
        self.classifications = self.judgements = 0
    async def classify_email(self, email):
        self.classifications += 1
        if self.classification == 'failed': return None
        r = await super().classify_email(email)
        r['needs_review'] = self.classification == 'uncertain'
        return r
    async def verify_documents(self, *args, **kwargs):
        self.judgements += 1
        return await super().verify_documents(*args, **kwargs)

@pytest.mark.parametrize('mismatch',[False, True])
async def test_clear_primary_never_calls_senior(mismatch):
    data=inputs()
    if mismatch: data[EMAIL['attachments'][1]]=data[EMAIL['attachments'][1]].replace('Count: 3','Count: 4')
    primary=CountedAI(await response_for(data)); senior=CountedAI(None)
    r=await Analyser(MemoryInbox(data),primary,senior).analyse(EMAIL)
    assert r.status == ('MISMATCH' if mismatch else 'OK')
    assert senior.classifications == senior.judgements == 0

@pytest.mark.parametrize('failure',['no_output','bad_evidence','classification','uncertain_classification','missing_reading'])
async def test_primary_uncertainty_is_resolved_once_by_senior(failure):
    data=inputs(); valid=await response_for(data); bad=copy.deepcopy(valid)
    if failure=='bad_evidence': bad['documents'][0]['fields']['shipper']['evidence']='not in the document'
    if failure=='missing_reading':
        bad['documents'][0]['fields']['gross_weight_kg']=None
        bad['comparisons']['gross_weight_kg']={'match':None,'reason':'unclear'}
        bad.update(status='NEEDS_REVIEW',review_reason='missing_value')
    primary=CountedAI(None if failure=='no_output' else bad,
        'failed' if failure=='classification' else 'uncertain' if failure=='uncertain_classification' else 'valid')
    senior=CountedAI(valid)
    r=await Analyser(MemoryInbox(data),primary,senior).analyse(EMAIL)
    assert r.status=='OK' and r.automation=='auto_completed'
    assert [s['tier'] for s in r.decision_chain]==['primary','senior']
    assert senior.classifications==senior.judgements==1

@pytest.mark.parametrize('kind',['unavailable','invalid','uncertain','failed_classification'])
async def test_failed_senior_goes_to_human_without_loop(kind):
    data=inputs(); payload=await response_for(data)
    if kind=='unavailable': payload=None
    elif kind=='invalid': payload['documents'][0]['fields']['shipper']['evidence']='invented'
    else:
        payload['documents'][0]['fields']['gross_weight_kg']=None
        payload['comparisons']['gross_weight_kg']={'match':None,'reason':'unclear'}
        payload.update(status='NEEDS_REVIEW',review_reason='missing_value')
    primary=CountedAI(None); senior=CountedAI(payload,'failed' if kind=='failed_classification' else 'valid')
    r=await Analyser(MemoryInbox(data),primary,senior).analyse(EMAIL)
    assert r.status=='NEEDS_REVIEW' and r.category=='BL_COMPARISON'
    assert r.automation=='review_required'
    assert [s['tier'] for s in r.decision_chain]==['primary','senior','human']
    assert primary.classifications==primary.judgements==senior.classifications==1
    assert senior.judgements==(0 if kind=='failed_classification' else 1)
    assert r.docs

@pytest.mark.parametrize('reason',['missing_value','missing_attachment'])
async def test_failed_senior_keeps_the_primary_review_reason(reason):
    """A technical senior failure is not a business finding: it must not overwrite a precise
    primary review_reason with the generic 'unreadable' handoff."""
    data=inputs(); payload=await response_for(data)
    payload['documents'][0]['fields']['gross_weight_kg']=None
    payload['comparisons']['gross_weight_kg']={'match':None,'reason':'unclear'}
    payload.update(status='NEEDS_REVIEW',review_reason=reason)
    primary=CountedAI(payload); senior=CountedAI(None)
    r=await Analyser(MemoryInbox(data),primary,senior).analyse(EMAIL)
    assert r.status=='NEEDS_REVIEW'
    assert r.review_reason==reason, 'the primary reason must survive a failed senior call'
    assert r.decision_method=='ai'
    assert r.senior_review is not None and r.senior_review.available is False
    assert [s['tier'] for s in r.decision_chain]==['primary','senior','human']
    assert any('Senior review did not complete' in w for w in r.warnings)


async def test_no_senior_configuration_means_human_handoff():
    r=await Analyser(MemoryInbox(inputs()),CountedAI(None)).analyse(EMAIL)
    assert r.decision_chain[-2]['available'] is False
    assert r.decision_chain[-1]==dict(tier='human',status='pending')

@pytest.mark.parametrize('final_status',['OK','MISMATCH'])
def test_human_can_finish_without_any_ai_and_cannot_return_to_ai(client,monkeypatch,final_status):
    c,main,tmp=client
    async def forbidden(*args,**kwargs): raise AssertionError('AI must not be called after human handling')
    monkeypatch.setattr(main.ai,'verify_documents',forbidden)
    monkeypatch.setattr(main.ai,'classify_email',forbidden)
    body=dict(category='BL_COMPARISON',status=final_status,defect_fields=['container_count'] if final_status=='MISMATCH' else [],
              note='Checked source files and contacted the carrier. Handling is complete.',complete=True)
    response=c.post('/api/cases/email_test/manual-review',json=body)
    assert response.status_code==200, response.text
    r=response.json()
    assert r['resolved'] and r['processing_status']=='RESOLVED_BY_HUMAN'
    assert r['decision_method']=='human' and r['history'][-1]['previous']['status']=='MISMATCH'
    assert c.get('/api/dashboard').json()['summary']['open_review_queue']==0
    for route in ['/api/analyse/email_test','/api/cases/email_test/readings','/api/cases/email_test/attachments','/api/cases/email_test/revision']:
        assert c.post(route,json={}).status_code==409
    assert c.post('/api/cases/email_test/decision',json={'action':'reopen'}).status_code==200
    assert c.post('/api/analyse/email_test').status_code==409
    restored=Store(tmp); restored.load()
    assert restored.get('email_test').manual_review


def test_unknown_category_handoff_is_visible_and_manually_resolvable(client,monkeypatch):
    c,main,_=client
    async def unavailable(email): return None
    monkeypatch.setattr(main.ai,'classify_email',unavailable)
    r=c.post('/api/analyse/email_test').json()
    assert r['category'] is None
    assert c.get('/api/dashboard').json()['priority'][0]['email_id']=='email_test'
    assert c.get('/api/submission').status_code==409
    r=c.post('/api/cases/email_test/manual-review',json=dict(category='SI_REQUEST',status='OK',note='Read the current request: new SI.',complete=True))
    assert r.status_code==200
    assert c.get('/api/submission').json()['email_test']['category']=='SI_REQUEST'

@pytest.mark.parametrize('change',[{'note':'  '},{'status':'NEEDS_REVIEW'},{'status':'MISMATCH','defect_fields':[]},
                                  {'status':'MISMATCH','defect_fields':['unknown']},{'category':'GENERAL','status':'MISMATCH'}])
def test_incomplete_or_invalid_human_completion_is_rejected(client,change):
    c,main,_=client
    body=dict(category='BL_COMPARISON',status='OK',note='Reviewed originals.',complete=True)
    body.update(change)
    assert c.post('/api/cases/email_test/manual-review',json=body).status_code==422
    assert not main.store.get('email_test').resolved


def test_copy_adoption_is_final_human_step_without_ai(client,monkeypatch):
    c,main,_=client
    report=c.post('/api/cases/email_test/revision').json()['working_report']
    async def forbidden(*args,**kwargs): raise AssertionError('Human adoption must not call AI')
    monkeypatch.setattr(main.ai,'verify_documents',forbidden)
    r=c.post('/api/cases/email_test/decision',json=dict(action='approve_revision',revision_id=report['revision_id']))
    assert r.status_code==200 and r.json()['resolved']
    assert c.post('/api/cases/email_test/decision',json={'action':'reopen'}).status_code==200
    assert c.post('/api/analyse/email_test').status_code==409


def test_provider_keys_are_not_crossed(monkeypatch):
    from app import config
    monkeypatch.setattr(config,'AI_PROVIDER','deepseek')
    monkeypatch.setattr(config,'AI_API_KEY','primary-secret')
    ai=AIClient(provider='openai',model='test-model',fallback_model='')
    assert not ai.enabled and not ai.api_key

@pytest.mark.parametrize('payload',[
    {'status':'incomplete','output':[{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}]},
    {'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'Cannot assess'}]}]},
    {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'broken JSON'}]}]},
])
async def test_openai_unusable_output_is_not_accepted_or_repeated(monkeypatch,payload):
    real=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw: real(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=payload)),**kw))
    ai=AIClient(provider='openai',api_key='offline',model='test-model',mode='full',fallback_model='',max_rpm=0)
    assert await ai.complete_json('Return JSON','test') is None
    assert ai.calls==1

@pytest.mark.parametrize('effort', ['high', 'max'])
async def test_deepseek_thinking_request_uses_separate_reasoning_budget(monkeypatch,effort):
    import json
    real=httpx.AsyncClient; captured=[]
    def respond(req):
        captured.append(json.loads(req.content))
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'reasoning_content':'not consumed','content':'{"ok":true}'}}]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw: real(transport=httpx.MockTransport(respond),**kw))
    ai=AIClient(provider='deepseek',api_key='offline',model='deepseek-flash',mode='full',thinking=True,reasoning_effort=effort,fallback_model='',max_rpm=0)
    assert await ai.complete_json('Return JSON','test') == {'ok':True}
    assert captured[0]['thinking'] == {'type':'enabled'}
    assert captured[0]['reasoning_effort']==effort and captured[0]['max_tokens']>=32768
    assert 'temperature' not in captured[0]
