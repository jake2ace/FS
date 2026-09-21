"""Business outcomes must come from AI, never from production rule helpers."""
import copy
import pytest
from app.ai import AIClient
from app.pipeline import Analyser, AIUnavailable
from tests.fakes import FixtureAI
from tests.test_workflow import EMAIL, inputs, MemoryInbox, client
from app.parsers import parse_attachment


class ResponseAI(FixtureAI):
    def __init__(self, response):
        super().__init__(); self.response=response
    async def verify_documents(self, email, documents, policy='standard'):
        return copy.deepcopy(self.response)
    async def classify_email(self, email):
        return dict(category='BL_COMPARISON',confidence=.9,reason='Compare the documents',intent='verify_documents',
                    evidence=[dict(source='body',quote=email['body'])])


async def response_for(data):
    docs=[]
    for i,(path,raw) in enumerate(data.items()):
        d=parse_attachment(path,raw.encode())
        docs.append(dict(index=i,filename=d.filename,text=d.text,readable=True,error=None,file_missing=False))
    return await FixtureAI().verify_documents(EMAIL,docs)


async def test_disabled_ai_fails_instead_of_using_rules():
    r = await Analyser(MemoryInbox(inputs()),AIClient(provider='none',mode='off')).analyse(EMAIL)
    assert r.category is None and r.status == 'NEEDS_REVIEW'
    assert r.automation == 'review_required'


async def test_ai_classification_has_no_keyword_override():
    ai=ResponseAI(None)
    async def classify(email):
        return dict(category='GENERAL',confidence=.4,reason='AI says operational notice',intent='other',
                    evidence=[dict(source='body',quote=email['body'])])
    ai.classify_email=classify
    r=await Analyser(MemoryInbox(inputs()),ai).analyse(EMAIL)
    assert r.category=='GENERAL' and r.category_method=='ai'


async def test_production_classify_extract_compare_helpers_are_not_called(monkeypatch):
    from app import classify,extract,compare
    data=inputs(); payload=await response_for(data)
    def forbidden(*a,**kw): raise AssertionError('Production rules were called')
    monkeypatch.setattr(classify,'classify_rules',forbidden)
    monkeypatch.setattr(extract,'extract_fields',forbidden)
    monkeypatch.setattr(compare,'compare_fields',forbidden)
    r=await Analyser(MemoryInbox(data),ResponseAI(payload)).analyse(EMAIL)
    assert r.status=='OK' and r.decision_method=='ai'
    assert all(v.source=='ai' for d in r.docs for v in d.fields.values())


async def test_ai_semantic_match_is_not_replaced_by_string_or_confidence_rules():
    data=inputs(); data[EMAIL['attachments'][1]]=data[EMAIL['attachments'][1]].replace('ACME EXPORTS','ACME EXPORTS TRADING AS ACME')
    payload=await response_for(data)
    payload.update(status='OK',defect_fields=[],confidence=.5)
    payload['comparisons']['shipper']=dict(match=True,reason='AI judges these names refer to the same party.')
    r=await Analyser(MemoryInbox(data),ResponseAI(payload)).analyse(EMAIL)
    assert r.status=='OK' and r.confidence==.5
    assert r.fields[0].match is True


@pytest.mark.parametrize('bad', ['evidence','missing_field','contradictory_status','invalid_match','missing_doc','null_value'])
async def test_invalid_ai_outputs_are_rejected_not_repaired(bad):
    data=inputs(); payload=await response_for(data)
    if bad=='evidence': payload['documents'][0]['fields']['shipper']['evidence']='invented evidence'
    if bad=='missing_field': payload['comparisons'].pop('shipper')
    if bad=='contradictory_status': payload['comparisons']['shipper']['match']=False
    if bad=='invalid_match': payload['comparisons']['shipper']['match']='true'
    if bad=='missing_doc': payload['documents'].pop()
    if bad=='null_value': payload['documents'][0]['fields']['shipper']['value']=None
    r=await Analyser(MemoryInbox(data),ResponseAI(payload)).analyse(EMAIL)
    assert r.status=='NEEDS_REVIEW' and r.decision_method=='response_validation'
    assert r.automation=='review_required'


async def test_model_unavailable_is_a_failure_not_a_rule_result():
    r = await Analyser(MemoryInbox(inputs()),ResponseAI(None)).analyse(EMAIL)
    assert r.category == 'BL_COMPARISON' and r.status == 'NEEDS_REVIEW'
    assert not r.defect_fields and r.fields == []


async def test_ai_explicit_null_reading_is_preserved_as_missing():
    data=inputs(); payload=await response_for(data)
    payload['documents'][0]['fields']['gross_weight_kg']=None
    payload['comparisons']['gross_weight_kg']={'match':None, 'reason':'AI could not read SI weight.'}
    payload.update(status='NEEDS_REVIEW', review_reason='missing_value', defect_fields=[])
    r=await Analyser(MemoryInbox(data),ResponseAI(payload)).analyse(EMAIL)
    assert r.decision_method=='ai' and r.review_reason=='missing_value'
    assert r.docs[0].fields['gross_weight_kg'].value is None


def test_failed_classification_enters_human_queue_without_fake_category(client,monkeypatch):
    c,main,_=client
    async def failed(email): return None
    monkeypatch.setattr(main.ai,'classify_email',failed)
    response=c.post('/api/analyse/email_test')
    assert response.status_code == 200
    assert response.json()['category'] is None
    assert response.json()['status'] == 'NEEDS_REVIEW'
    assert c.get('/api/dashboard').json()['summary']['open_review_queue'] == 1
    assert c.get('/api/submission').status_code == 409
