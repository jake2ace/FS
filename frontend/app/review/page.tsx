'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { StatusBadge } from '@/components/StatusBadge';
import { api, post, pct, REVIEW_LABEL, type EmailRow } from '@/lib/api';

const RISK_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2, none: 3 };

export default function ReviewQueue() {
  const [rows, setRows] = useState<EmailRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'open' | 'resolved' | 'auto'>('open');
  const [busy, setBusy] = useState<string | null>(null);

  const load = () =>
    api<{ items: EmailRow[] }>('/api/results')
      .then((d) => {
        setRows(d.items);
        setError(null);   // a recovered request clears the previous failure
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const list = useMemo(() => {
    const bl = rows;
    let sel: EmailRow[];
    if (tab === 'open') sel = bl.filter((r) => r.automation === 'review_required' && !r.resolved);
    else if (tab === 'resolved') sel = bl.filter((r) => r.resolved);
    else sel = bl.filter((r) => r.automation === 'auto_completed');
    return sel.sort((a, b) => (RISK_ORDER[a.risk || 'none'] - RISK_ORDER[b.risk || 'none']) || ((b.defect_fields?.length || 0) - (a.defect_fields?.length || 0)) || a.email_id.localeCompare(b.email_id));
  }, [rows, tab]);

  const quick = async (id: string, action: string) => {
    setBusy(id);
    try {
      await post(`/api/cases/${id}/decision`, { action });
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const counts = {
    open: rows.filter((r) => r.automation === 'review_required' && !r.resolved).length,
    resolved: rows.filter((r) => r.resolved).length,
    auto: rows.filter((r) => r.category === 'BL_COMPARISON' && r.automation === 'auto_completed').length,
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Review Queue</h1>
          <div className="sub">Every mismatch and every case the system could not decide on its own. A person confirms, escalates or resolves - nothing is released automatically.</div>
        </div>
      </div>
      {error ? <div className="alert alert-risk" style={{ marginBottom: 12 }}>{error}</div> : null}
      <div className="card">
        <div className="tabs">
          <button className={tab === 'open' ? 'active' : ''} onClick={() => setTab('open')}>Open ({counts.open})</button>
          <button className={tab === 'resolved' ? 'active' : ''} onClick={() => setTab('resolved')}>Resolved ({counts.resolved})</button>
          <button className={tab === 'auto' ? 'active' : ''} onClick={() => setTab('auto')}>Auto-completed ({counts.auto})</button>
        </div>
        {list.length === 0 ? (
          <div className="empty">{rows.length === 0 ? 'No results yet - analyse emails from the Smart Inbox or run the full inbox.' : 'Nothing here.'}</div>
        ) : (
          <table>
            <thead><tr><th>Email</th><th>Finding</th><th>Status</th><th>Fields / reason</th><th className="right">Conf.</th><th></th></tr></thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.email_id}>
                  <td className="mono nowrap"><Link href={`/cases/${r.email_id}`}>{r.email_id}</Link></td>
                  <td><div>{r.headline}</div><div className="small muted truncate">{r.subject}</div></td>
                  <td><StatusBadge ui={r.ui_status} status={r.status} /></td>
                  <td className="small">
                    {r.defect_fields && r.defect_fields.length ? r.defect_fields.join(', ') : r.review_reason ? REVIEW_LABEL[r.review_reason] || r.review_reason : '–'}
                    {r.processing_status === 'PENDING_HUMAN_APPROVAL' ? <div className="badge badge-warn">Pending approval</div> : null}
                    {r.decision ? <div className="muted">decision: {r.decision.action}</div> : null}
                  </td>
                  <td className="right small">{pct(r.confidence)}</td>
                  <td className="right nowrap">
                    <Link href={`/cases/${r.email_id}`} className="btn btn-sm">Open</Link>{' '}
                    {tab === 'open' && r.processing_status !== 'PENDING_HUMAN_APPROVAL' ? (
                      <>

                        <button className="btn btn-sm btn-danger" disabled={busy === r.email_id} onClick={() => quick(r.email_id, 'escalate')}>Escalate</button>
                      </>
                    ) : tab === 'resolved' ? (
                      <button className="btn btn-sm" disabled={busy === r.email_id} onClick={() => quick(r.email_id, 'reopen')}>Reopen</button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
