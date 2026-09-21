'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { StatusBadge } from '@/components/StatusBadge';
import { api, type EmailRow } from '@/lib/api';

const RISK_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2, none: 3 };

/**
 * The rail beside a case is the list the reader came from.
 *
 * It used to always be the review queue, even when the case was opened from the Smart
 * Inbox - so the breadcrumb said one thing, the rail showed another, and Next walked a
 * list the reader had never been looking at. The link that opened the case now says
 * where it came from, and the rail follows it.
 */
export type Source = 'review' | 'inbox';

/** Cases a person still has to decide on, in the same order as the Review Queue page. */
function order(a: EmailRow, b: EmailRow) {
  // Escalated first, matching the Review Queue page: the rail and the list it came from
  // must not disagree about what comes next.
  const escalated = (r: EmailRow) => (r.decision?.action === 'escalate' ? 0 : 1);
  return (
    (escalated(a) - escalated(b)) ||
    (RISK_ORDER[a.risk || 'none'] - RISK_ORDER[b.risk || 'none']) ||
    ((b.defect_fields?.length || 0) - (a.defect_fields?.length || 0)) ||
    a.email_id.localeCompare(b.email_id)
  );
}

export default function CaseQueue({ current, source = 'review' }: { current: string; source?: Source }) {
  const [rows, setRows] = useState<EmailRow[] | null>(null);
  const router = useRouter();

  // Reloaded whenever the open case changes, so a case that was just resolved
  // drops out of the review list while the person moves on to the next one.
  useEffect(() => {
    let live = true;
    const path = source === 'inbox' ? '/api/emails?limit=2000' : '/api/results';
    api<{ items: EmailRow[] }>(path)
      .then((d) => { if (live) setRows(d.items); })
      .catch(() => { if (live) setRows([]); });
    return () => { live = false; };
  }, [current, source]);

  const list = useMemo(() => {
    if (!rows) return [];
    // From the inbox the rail is the inbox: every analysed email, in inbox order, so the
    // arrows walk the list the reader was reading.
    if (source === 'inbox') return rows.filter((r) => r.analysed || r.email_id === current);
    // From the review queue it is the open cases. The case being looked at stays in the
    // list even once it is resolved, so the position indicator and the two arrows do not
    // jump while it is open.
    return rows
      .filter((r) => (r.automation === 'review_required' && !r.resolved) || r.email_id === current)
      .sort(order);
  }, [rows, current, source]);

  const at = list.findIndex((r) => r.email_id === current);
  const prev = at > 0 ? list[at - 1] : null;
  const next = at >= 0 && at < list.length - 1 ? list[at + 1] : null;

  const go = useCallback((row: EmailRow | null) => {
    if (row) router.push(`/cases/${row.email_id}?from=${source}`);
  }, [router, source]);

  // Left / right arrows move through the queue, but never while typing a note.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const el = e.target as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable) return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); go(prev); }
      if (e.key === 'ArrowRight') { e.preventDefault(); go(next); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go, prev, next]);

  return (
    <aside className="cq" aria-label={source === 'inbox' ? 'Emails in the inbox' : 'Cases waiting for a decision'}>
      <div className="cq-head">
        <span className="cq-title">{source === 'inbox' ? 'Smart Inbox' : 'Waiting for you'}</span>
        <span className="cq-count">
          {at >= 0 ? `${at + 1} of ${list.length}` : `${list.length}${source === 'inbox' ? '' : ' open'}`}
        </span>
      </div>

      <div className="cq-nav">
        <button className="btn btn-sm" onClick={() => go(prev)} disabled={!prev} title={prev ? prev.email_id : 'First in the queue'}>
          ← Previous
        </button>
        <button className="btn btn-sm btn-primary" onClick={() => go(next)} disabled={!next} title={next ? next.email_id : 'Last in the queue'}>
          Next →
        </button>
      </div>

      {rows === null ? (
        <div className="cq-empty">Loading…</div>
      ) : list.length === 0 ? (
        <div className="cq-empty">
          {source === 'inbox' ? 'Nothing analysed yet.' : 'Nothing is waiting for a decision.'}
        </div>
      ) : (
        <div className="cq-list">
          {list.map((r) => (
            <Link
              key={r.email_id}
              href={`/cases/${r.email_id}?from=${source}`}
              className={`cq-item${r.email_id === current ? ' is-current' : ''}`}
              aria-current={r.email_id === current ? 'true' : undefined}
            >
              <div className="cq-row">
                <span className="cq-id mono">{r.email_id}</span>
                <StatusBadge ui={r.ui_status} status={r.status} />
              </div>
              <div className="cq-sub">{r.subject}</div>
            </Link>
          ))}
        </div>
      )}

      <div className="cq-hint">
        Use ← and → to move through {source === 'inbox' ? 'the inbox' : 'the queue'}.
      </div>
    </aside>
  );
}
