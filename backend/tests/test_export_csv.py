"""The operations report.

The submission JSON has one record per email. This file has one row per differing
field, which is a different shape for a different reader: someone working the list
in a spreadsheet needs both readings on the row they are looking at, not a case id
to go and open. These tests pin that shape, and the BOM, which is the difference
between readable and mojibake once a port name is not ASCII.
"""
import csv
import io

from app.schemas import FIELD_LABELS
from tests.test_workflow import client, EMAIL  # noqa: F401  (client is a fixture)


def read_csv(c):
    r = c.get('/api/export.csv')
    assert r.status_code == 200, r.text
    assert r.headers['content-type'].startswith('text/csv')
    body = r.text
    assert body.startswith('﻿'), 'without the BOM Excel reads UTF-8 as the local code page'
    return list(csv.reader(io.StringIO(body.lstrip('﻿'))))


def test_columns_are_the_ones_operations_asked_for(client):
    c, _, _ = client
    assert read_csv(c)[0] == ['Email ID', 'SI file', 'BL file', 'Mismatch field',
                              'SI value', 'BL value', 'Explanation', 'Final status']


def test_one_row_per_differing_field_with_both_readings(client):
    c, _, _ = client
    rows = read_csv(c)[1:]
    # The fixture case differs on exactly one field, so it is exactly one row.
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == 'email_test'
    assert row[1].endswith('SI.txt') and row[2].endswith('BL.txt')
    assert row[3] == FIELD_LABELS['container_count']
    assert (row[4], row[5]) == ('3', '4')     # the SI reading, then the BL reading
    assert row[7] == 'MISMATCH'


def test_a_case_with_nothing_to_fix_still_accounts_for_itself(client):
    c, main, _ = client
    # Put the draft back in step with the instruction: no differing field, but the
    # email must not vanish from a report that claims to cover the mailbox.
    data = main.inbox.docs
    path = EMAIL['attachments'][1]
    data[path] = data[path].replace('Count: 4', 'Count: 3')
    assert c.post('/api/analyse/email_test?force=true&explain=false').status_code == 200
    rows = read_csv(c)[1:]
    assert len(rows) == 1
    assert rows[0][0] == 'email_test'
    assert rows[0][3:6] == ['', '', '']
    assert rows[0][7].startswith('OK')


def test_summary_answers_the_supervisor_question(client):
    """The supervisor's question, not the operator's.

    The case list says what to fix next. These say where the paperwork keeps breaking
    and whether a bad draft is usually one mistake or several - the numbers that can
    change something upstream rather than one case at a time.
    """
    c, _, _ = client
    summary = c.get('/api/dashboard').json()['summary']
    # The fixture case differs on container_count and nothing else.
    assert summary['defects_by_field'] == {'container_count': 1}
    assert summary['defect_cases'] == 1
    assert summary['defect_cases_multi'] == 0, 'one differing field is not a multi-field draft'
