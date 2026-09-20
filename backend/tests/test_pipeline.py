"""End-to-end checks against the official participant bundle (rules only, no AI).

The 20 edge cases (email_501-520) are documented in the bundle README: five of
each review_reason.  These tests pin that behaviour so a regression is caught
before a deploy.
"""
import asyncio
from pathlib import Path

import pytest

from app import config
from app.ai import AIClient
from app.data import Inbox
from app.parsers import parse_attachment
from app.extract import extract_fields, missing_fields
from app.pipeline import Analyser
from app.submission import build_submission


@pytest.fixture(scope="module")
def inbox():
    ib = Inbox(config.DATA_DIR, config.DATA_ZIP)
    ib.ensure()
    return ib


@pytest.fixture(scope="module")
def analyser(inbox):
    return Analyser(inbox, AIClient(provider="none", api_key="", mode="off"))


def run(coro):
    return asyncio.run(coro)


def test_bundle_loaded(inbox):
    assert len(inbox) == 520


def test_all_readable_main_set_documents_yield_seven_fields(inbox):
    for email in inbox.emails():
        if int(email["email_id"][-3:]) > 500:
            continue
        for path in email["attachments"]:
            doc = parse_attachment(path, inbox.read_bytes(path))
            assert doc.readable, path
            assert doc.detected_type in ("SI", "BL"), (path, doc.detected_type)
            assert missing_fields(extract_fields(doc)) == [], path


@pytest.mark.parametrize("email_id,reason", [
    ("email_501", "wrong_doc_type"), ("email_505", "wrong_doc_type"),
    ("email_506", "missing_attachment"), ("email_507", "missing_attachment"), ("email_509", "missing_attachment"),
    ("email_511", "unreadable"), ("email_512", "unreadable"), ("email_515", "unreadable"),
    ("email_516", "missing_value"), ("email_517", "missing_value"), ("email_520", "missing_value"),
])
def test_edge_cases_go_to_human_review(inbox, analyser, email_id, reason):
    res = run(analyser.analyse(inbox.get(email_id)))
    assert res.category == "BL_COMPARISON"
    assert res.status == "NEEDS_REVIEW"
    assert res.review_reason == reason
    assert res.automation == "review_required"


def test_known_mismatch_and_clean_case(inbox, analyser):
    mismatch = run(analyser.analyse(inbox.get("email_004")))
    assert mismatch.status == "MISMATCH"
    assert set(mismatch.defect_fields) == {"consignee", "notify_party"}
    clean = run(analyser.analyse(inbox.get("email_001")))
    assert clean.status == "OK" and clean.defect_fields == []
    assert clean.headline == "No mismatch detected"


def test_request_for_draft_without_attachments_is_not_escalated(inbox, analyser):
    res = run(analyser.analyse(inbox.get("email_003")))
    assert res.category == "BL_COMPARISON" and res.status == "OK"
    assert res.ui_status == "Awaiting draft BL"


def test_submission_shape_matches_sample(inbox, analyser):
    results = {}
    for eid in ("email_001", "email_004", "email_007", "email_507"):
        results[eid] = run(analyser.analyse(inbox.get(eid)))
    ids = [e["email_id"] for e in inbox.emails()]
    sub, missing = build_submission(ids, results)
    sample = inbox.sample_submission()
    assert set(sub) == set(sample)
    for k in sub:
        assert list(sub[k].keys()) == list(sample[k].keys())
    assert sub["email_004"]["status"] == "MISMATCH" and sub["email_004"]["has_defect"] is True
    assert sub["email_507"]["review_reason"] == "missing_attachment"
    assert len(missing) == len(ids) - 4
