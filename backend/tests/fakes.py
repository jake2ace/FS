"""Offline model stand-in for workflow/file tests only; never imported by app code.

Use the existing fixture parser to synthesize responses, so persistence and native
file-edit tests remain independent of network access and model variability.
"""
from app.ai import AIClient
from app.classify import classify_rules
from app.extract import extract_fields, missing_fields
from app.compare import compare_fields
from app.parsers import parse_attachment
from app.schemas import FIELDS


class FixtureAI(AIClient):
    def __init__(self):
        super().__init__(provider='deepseek', api_key='offline-test', model='fixture', mode='full', max_rpm=0, fallback_model='')

    async def classify_email(self, email):
        c=classify_rules(email)
        source = 'body' if email.get('body') else 'subject'
        return dict(category=c.category, confidence=c.confidence, reason=c.reason or 'Fixture', intent=c.intent,
                    evidence=[dict(source=source, quote=email[source])])

    async def verify_documents(self, email, documents, policy='standard'):
        readings=[]; field_sets={}; sources={}
        for item in documents:
            parsed=parse_attachment(item['filename']+'.txt',item['text'].encode())
            role=parsed.detected_type if item['readable'] else 'UNKNOWN'
            fields=extract_fields(parsed) if role in ('SI','BL') else {}
            converted={}
            for f,v in fields.items():
                evidence=v.evidence
                if evidence and evidence not in item['text']:
                    evidence=next((line for line in item['text'].splitlines() if v.label and v.label in line),item['text'])
                converted[f]=dict(value=v.value,evidence=evidence,label=v.label if v.label and v.label in item['text'] else None)
            readings.append(dict(index=item['index'],doc_type=role,fields=converted))
            if role in ('SI','BL'):
                field_sets[role]=fields; sources[role]=item
        comparisons={}; defects=[]; reason=None
        if not documents or any(x['file_missing'] for x in documents): reason='missing_attachment'
        elif any(not x['readable'] for x in documents): reason='unreadable'
        elif any(x['doc_type'] not in ('SI','BL') for x in readings): reason='wrong_doc_type'
        elif len(field_sets)!=2: reason='missing_attachment'
        elif len(readings)!=2: reason='wrong_doc_type'
        else:
            rows,defects=compare_fields(field_sets['SI'],field_sets['BL'])
            comparisons={r.field:dict(match=r.match,reason=r.reason) for r in rows}
            if missing_fields(field_sets['SI']) or missing_fields(field_sets['BL']): reason='missing_value'
        status='NEEDS_REVIEW' if reason else 'MISMATCH' if defects else 'OK'
        return dict(documents=readings,comparisons=comparisons,status=status,review_reason=reason,
                    defect_fields=defects if status=='MISMATCH' else [],confidence=.95,
                    explanation='Offline fixture judgement.',suggested_action='Review the report.')
