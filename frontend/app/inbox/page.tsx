'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { CategoryBadge, StatusBadge } from '@/components/StatusBadge';
import { api, post, pct, type EmailRow } from '@/lib/api';
import { useLiveRefresh } from '@/lib/useLiveRefresh';

const PAGE = 50;

export default function SmartInbox() {
  const router = useRouter();
  const [rows, setRows] = useState<EmailRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [category, setCategory] = useState('');
  const [status, setStatus] = useState('');
  const [onlyAttach, setOnlyAttach] = useState(false);
  const [onlyUnanalysed, setOnlyUnanalysed] = useState(false);
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);

  const load = () =>
    api<{ items: EmailRow[] }>('/api/emails?limit=2000')
      .then((d) => {
        setRows(d.items);
        setError(null);   // a recovered request clears the previous failure
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);
  useLiveRefresh(load);

  const filtered = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return rows.filter((r) => {
      if (category && r.category !== category) return false;
      if (status && r.ui_status !== status && r.status !== status) return false;
      if (onlyAttach && r.attachment_count === 0) return false;
      if (onlyUnanalysed && r.analysed) return false;
      if (ql && !(`${r.email_id} ${r.subject} ${r.from}`.toLowerCase().includes(ql))) return false;
      return true;
    });
  }, [rows, q, category, status, onlyAttach, onlyUnanalysed]);

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const visible = filtered.slice(page * PAGE, page * PAGE + PAGE);

  const analyse = async (id: string) => {
    setBusy(id);
    try {
      await post(`/api/analyse/${id}?force=true&explain=true`);
      router.push(`/cases/${id}`);
    } catch (e: any) {
      setError(e.message);
      setBusy(null);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Smart Inbox</h1>
          <div className="sub">The official shared inbox - {rows.length} emails. Comparison requests are the ones that continue to the checking step.</div>
        </div>
      </div>
      {error ? <div className="alert alert-risk" style={{ marginBottom: 12 }}>{error}</div> : null}
      <div className="card">
        <div className="toolbar">
          <input type="text" placeholder="Search subject, sender or id…" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} style={{ minWidth: 260 }} />
          <select value={category} onChange={(e) => { setCategory(e.target.value); setPage(0); }}>
            <option value="">All categories</option>
            <option value="BL_COMPARISON">BL comparison</option>
            <option value="SI_REQUEST">SI request</option>
            <option value="INVOICE_QUERY">Invoice query</option>
            <option value="GENERAL">General</option>
            <option value="SPAM">Spam</option>
          </select>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}>
            <option value="">All statuses</option>
            <option value="Mismatch">Mismatch</option>
            <option value="Needs review">Needs review</option>
            <option value="Safe to complete">Safe to complete</option>
            <option value="No action">No action</option>
          </select>
          <label className="small"><input type="checkbox" checked={onlyAttach} onChange={(e) => { setOnlyAttach(e.target.checked); setPage(0); }} /> with attachments</label>
          <label className="small"><input type="checkbox" checked={onlyUnanalysed} onChange={(e) => { setOnlyUnanalysed(e.target.checked); setPage(0); }} /> not analysed</label>
          <span className="muted small" style={{ marginLeft: 'auto' }}>{filtered.length} shown · page {page + 1}/{pages}</span>
          <button className="btn btn-sm" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>‹</button>
          <button className="btn btn-sm" onClick={() => setPage((p) => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1}>›</button>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Email</th><th>Subject</th><th>From</th><th className="right">Att.</th><th>Category</th><th>Status</th><th className="right">Conf.</th><th></th></tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.email_id}>
                  <td className="mono nowrap">{r.analysed ? <Link href={`/cases/${r.email_id}`}>{r.email_id}</Link> : r.email_id}</td>
                  <td>
                    <div className="truncate" title={r.subject}>{r.subject}</div>
                    {r.headline ? <div className="small muted truncate">{r.headline}</div> : <div className="small muted truncate">{r.body_preview}</div>}
                  </td>
                  <td className="small">{r.from}</td>
                  <td className="right">{r.attachment_count}</td>
                  <td><CategoryBadge category={r.category} /></td>
                  <td><StatusBadge ui={r.ui_status} status={r.status} /></td>
                  <td className="right small">{pct(r.confidence)}</td>
                  <td className="right nowrap">
                    {r.analysed ? <Link href={`/cases/${r.email_id}`} className="btn btn-sm">Open</Link> : null}{' '}
                    <button className="btn btn-sm btn-primary" onClick={() => analyse(r.email_id)} disabled={busy === r.email_id}>
                      {busy === r.email_id ? 'Analysing…' : r.analysed ? 'Re-analyse' : 'Analyse'}
                    </button>
                  </td>
                </tr>
              ))}
              {visible.length === 0 ? (
                <tr><td colSpan={8} className="empty">No emails match the current filters.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
