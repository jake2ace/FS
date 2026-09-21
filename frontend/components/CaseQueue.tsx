'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { StatusBadge } from '@/components/StatusBadge';
import { api, type EmailRow } from '@/lib/api';

const RISK_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2, none: 3 };

/** Cases a person still has to decide on, in the same order as the Review Queue page. */
function order(a: EmailRow, b: EmailRow) {
  return (
    (RISK_ORDER[a.risk || 'none'] - RISK_ORDER[b.risk || 'none']) ||
    ((b.defect_fields?.length || 0) - (a.defect_fields?.length || 0)) ||
    a.email_id.localeCompare(b.email_id)
  );
}

export default function CaseQueue({ current }: { current: string }) {
  const [rows, setRows] = useState<EmailRow[] | null>(null);
  const router = useRouter();

  // Reloaded whenever the open case changes, so a case that was just resolved
  // drops out of the list while the person moves on to the next one.
  useEffect(() => {
    let live = true;
    api<{ items: EmailRow[] }>('/api/results')
      .then((d) => { if (live) setRows(d.items); })
      .catch(() => { if (live) setRows([]); });
    return () => { live = false; };
  }, [current]);

  const list = useMemo(() => {
    if (!rows) return [];
    // The case being looked at stays in the list even once it is resolved, so the
    // position indicator and the two arrows do not jump while it is open.
    return rows
      .filter((r) => (r.automation === 'review_required' && !r.resolved) || r.email_id === current)
      .sort(order);
  }, [rows, current]);

  const at = list.findIndex((r) => r.email_id === current);
  const prev = at > 0 ? list[at - 1] : null;
  const next = at >= 0 && at < list.length - 1 ? list[at + 1] : null;

  const go = useCallback((row: EmailRow | null) => {
    if (row) router.push(`/cases/${row.email_id}`);
  }, [router]);

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
    <aside className="cq" aria-label="Cases waiting for a decision">
      <div className="cq-head">
        <span className="cq-title">Waiting for you</span>
        <span className="cq-count">{at >= 0 ? `${at + 1} of ${list.length}` : `${list.length} open`}</span>
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
        <div className="cq-empty">Nothing is waiting for a decision.</div>
      ) : (
        <div className="cq-list">
          {list.map((r) => (
            <Link
              key={r.email_id}
              href={`/cases/${r.email_id}`}
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

      <div className="cq-hint">Use ← and → to move through the queue.</div>
    </aside>
  );
}
