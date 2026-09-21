"""Audit a finished isolated thinking run without API calls or private answer keys."""
import argparse
from collections import Counter
from datetime import datetime
import csv
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config
from app.ai_contract import source_excerpt
from app.data import Inbox
from app.schemas import CaseResult, FIELDS
from app.submission import build_submission

def digest(data): return hashlib.sha256(data).hexdigest()

def audit(path):
    data=json.loads(path.read_text())
    if not data.get('finished_at'): raise SystemExit('The batch is not finished.')
    inbox=Inbox(config.DATA_DIR,config.DATA_ZIP)
    emails={e['email_id']:e for e in inbox.emails()}
    records=data['records']; errors=[]; changes=[]; stage_issues=[]; rejected_steps=[]; cases={}; csv_rows=[]
    def check(ok,message):
        if not ok: errors.append(message)
    check(len(records)==len(emails)==520,'Expected all 520 emails')
    check(len({r['email_id'] for r in records})==520,'Missing or duplicate IDs')
    check({r['email_id'] for r in records}==set(emails),'ID coverage differs from inbox')
    check(data['case_cache_before_sha256']==data['case_cache_after_sha256'],'Existing case cache changed')
    check(all(digest((config.BACKEND_DIR/'app'/name).read_bytes())==sha for name,sha in data['code_sha256'].items()),'Production code changed during the run')
    evidence=0
    for record in records:
        eid=record['email_id']; email=emails[eid]
        check(record['email_sha256']==digest(json.dumps(email,sort_keys=True,ensure_ascii=False).encode()),f'{eid}: input email changed')
        if not record['result']:
            errors.append(f'{eid}: no recorded case result: {record["error"]}')
            continue
        result=CaseResult.model_validate(record['result']); cases[eid]=result
        chain=result.decision_chain; tiers=[s['tier'] for s in chain]
        check(tiers in (['primary'],['primary','senior'],['primary','senior','human']),f'{eid}: invalid route {tiers}')
        check(chain[0].get('reasoning_effort')=='high' and chain[0].get('thinking') is True,f'{eid}: primary is not high thinking')
        if 'senior' in tiers:
            check(chain[0]['status']=='NEEDS_REVIEW',f'{eid}: senior invoked for a clear primary result')
            check(chain[1].get('reasoning_effort')=='max' and chain[1].get('thinking') is True,f'{eid}: senior is not max thinking')
        check(('human' in tiers)==(result.status=='NEEDS_REVIEW'),f'{eid}: unresolved case did not reach human')
        check(not result.resolved and result.manual_review is None,f'{eid}: test fabricated human completion')
        if result.category is None:
            check(result.status=='NEEDS_REVIEW',f'{eid}: unknown category was treated as complete')
        for quote in result.category_evidence:
            check(source_excerpt(quote.quote,email.get(quote.source,'')),f'{eid}: invalid category source')
            evidence+=1
        if result.category=='BL_COMPARISON' and result.status in ('OK','MISMATCH'):
            check({f.field for f in result.fields}==set(FIELDS),f'{eid}: incomplete field comparison')
            check(all(f.match is not None and f.si_value is not None and f.bl_value is not None for f in result.fields),f'{eid}: uncertain field accepted')
            false_fields={f.field for f in result.fields if f.match is False}
            check(false_fields==set(result.defect_fields),f'{eid}: defects disagree with comparison rows')
            check((result.status=='MISMATCH')==bool(false_fields),f'{eid}: final status contradicts fields')
        final_tier = 'senior' if 'senior' in tiers else 'primary'
        verification=[s for s in record['stages'] if s['stage']=='document_verification' and s['tier']==final_tier]
        for step in chain:
            if step.get('method') in ('ai_unavailable','response_validation'):
                rejected_steps.append(dict(email_id=eid,tier=step['tier'],method=step['method'],reason=step['reason'],final_status=result.status))
        if result.decision_method=='ai' and verification:
            raw=verification[-1]['response']
            check(raw is not None and raw['status']==result.status,f'{eid}: final result differs from final AI response')
            if raw:
                sources=verification[-1]['source_input']['documents']
                for doc in raw['documents']:
                    for field,reading in doc['fields'].items():
                        if reading and reading.get('value') is not None:
                            check(source_excerpt(reading.get('evidence'),sources[doc['index']]['text']),f'{eid}: unsupported {field} excerpt')
                            evidence+=1
        for stage in record['stages']:
            check(stage['thinking'] is True and stage['reasoning_effort']==('high' if stage['tier']=='primary' else 'max'),f'{eid}: incorrect request effort')
            if stage['response'] is None:
                stage_issues.append(dict(email_id=eid,tier=stage['tier'],stage=stage['stage'],error=stage['last_api_error'],final_status=result.status))
        previous=record['previous']; current=result.model_dump()
        changed={k:dict(previous=previous[k],current=current[k]) for k in previous
                 if (sorted(previous[k] or []) if k=='defect_fields' else previous[k]) != (sorted(current[k] or []) if k=='defect_fields' else current[k])}
        if changed: changes.append(dict(email_id=eid,changes=changed))
        csv_rows.append([eid,result.category or 'UNCLASSIFIED',result.status,','.join(result.defect_fields),result.review_reason or '',
            chain[0]['status'],chain[1]['status'] if 'senior' in tiers else '', 'yes' if 'human' in tiers else 'no',
            record['seconds'], 'yes' if changed else 'no',result.explanation])
    submission,missing=build_submission(list(emails),cases)
    check(not missing,'Unclassified or missing cases prevent a complete submission')
    out=path.parent; prefix=path.stem
    with (out/(prefix+'-逐封结果.csv')).open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file);writer.writerow(['email_id','category','status','defect_fields','review_reason','primary_high','review_max','human_queue','seconds','changed_vs_previous','explanation']);writer.writerows(csv_rows)
    elapsed=(datetime.fromisoformat(data['finished_at'])-datetime.fromisoformat(data['started_at'])).total_seconds()
    bl=[r for r in cases.values() if r.category=='BL_COMPARISON']
    review=[r for r in cases.values() if r.status=='NEEDS_REVIEW']
    upgraded=[r for r in cases.values() if len(r.decision_chain)>1]
    result=dict(coverage=len(records),elapsed_seconds=elapsed,primary_calls=data['primary']['calls'],senior_calls=data['senior']['calls'],
        total_calls=data['calls'],api_failures=data['api_failures'],categories=dict(Counter(r.category for r in cases.values())),
        bl_statuses=dict(Counter(r.status for r in bl)),review_reasons=dict(Counter(r.review_reason for r in review)),
        escalated=len(upgraded),senior_resolved=sum(r.status!='NEEDS_REVIEW' for r in upgraded),human_handoffs=len(review),
        final_methods=dict(Counter(r.decision_method for r in cases.values())),source_excerpts_checked=evidence,
        stage_issues=stage_issues,rejected_steps=rejected_steps,changed_cases=changes,checks_passed=not errors,errors=errors,missing_submission_ids=missing,
        source_report_sha256=digest(path.read_bytes()),cache_unchanged=data['case_cache_before_sha256']==data['case_cache_after_sha256'],
        accuracy_measured=False, checks_scope='coverage, configuration, routing, response consistency and source presence; not semantic accuracy',
        requires_semantic_review=bool(changes), ready_to_activate=not errors and not changes)
    (out/(prefix+'-验收核对.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    if not errors:(out/(prefix+'-官方格式候选.json')).write_text(json.dumps(submission,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in ('stage_issues','changed_cases')},ensure_ascii=False,indent=2))
    print('Changed cases:',json.dumps(changes,ensure_ascii=False))
    print('Stage issues:',json.dumps(stage_issues,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('report',type=Path)
    audit(parser.parse_args().report)
