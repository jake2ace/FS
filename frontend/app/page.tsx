'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { StatusBadge, RiskBadge } from '@/components/StatusBadge';
import { api, post, fmtTime, REVIEW_LABEL } from '@/lib/api';

export default function TodayWorkCentre() {
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const load = () => api('/api/dashboard').then(setData).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);

  const startRun = async () => {
    setStarting(true);
    try {
      await post('/api/runs/full-inbox', { force: false });
      router.push('/runs');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setStarting(false);
    }
  };

  if (error) return <div className="alert alert-risk">Backend not reachable: {error}</div>;
  if (!data) return <div className="empty">Loading…</div>;
  const s = data.summary;
  const run = data.last_run;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Today Work Centre</h1>
          <div className="sub">What needs attention in the shared inbox right now.</div>
        </div>
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <Link href="/inbox" className="btn">Open Smart Inbox</Link>
          <button className="btn btn-primary" onClick={startRun} disabled={starting || run?.status === 'running'}>
            {run?.status === 'running' ? 'Batch run in progress…' : s.analysed === 0 ? 'Analyse the full inbox' : 'Analyse remaining emails'}
          </button>
        </div>
      </div>

      <div className="grid grid-6">
        <div className="card tile"><div className="tile-label">Comparison requests</div><div className="tile-value">{s.comparison_requests}</div><div className="tile-hint">of {s.analysed} analysed emails</div></div>
        <div className="card tile risk"><div className="tile-label">High risk</div><div className="tile-value">{s.high_risk}</div><div className="tile-hint">mismatch between SI and draft BL</div></div>
        <div className="card tile warn"><div className="tile-label">Needs review</div><div className="tile-value">{s.needs_review}</div><div className="tile-hint">missing / unreadable / blank</div></div>
        <div className="card tile safe"><div className="tile-label">Safe completed</div><div className="tile-value">{s.safe_completed}</div><div className="tile-hint">auto-completed under {s.policy} policy</div></div>
        <div className="card tile"><div className="tile-label">Awaiting draft BL</div><div className="tile-value">{s.awaiting_draft}</div><div className="tile-hint">requests with nothing to compare yet</div></div>
        <div className="card tile"><div className="tile-label">Not analysed</div><div className="tile-value">{s.not_analysed}</div><div className="tile-hint">of {s.total_emails} emails in the inbox</div></div>
      </div>

      <div className="grid grid-2" style={{ marginTop: 14 }}>
        <div className="card">
          <div className="card-head">
            <h2>Risk Radar - priority cases</h2>
            <Link href="/review" className="small">Open the full review queue →</Link>
          </div>
          {data.priority.length === 0 ? (
            <div className="empty">{s.analysed === 0 ? 'Nothing analysed yet. Start with the Smart Inbox or run the full inbox.' : 'No open risk cases. Everything is either safe or already handled.'}</div>
          ) : (
            <table>
              <thead><tr><th>Email</th><th>Finding</th><th>Risk</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {data.priority.map((p: any) => (
                  <tr key={p.email_id}>
                    <td className="mono nowrap">{p.email_id}</td>
                    <td>
                      <div>{p.headline}</div>
                      <div className="muted small truncate">{p.subject}</div>
                    </td>
                    <td><RiskBadge risk={p.risk} /></td>
                    <td><StatusBadge ui={p.ui_status} status={p.status} />{p.review_reason ? <div className="small muted">{REVIEW_LABEL[p.review_reason] || p.review_reason}</div> : null}</td>
                    <td className="right"><Link href={`/cases/${p.email_id}`} className="btn btn-sm">Open</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div>
          <div className="card">
            <h2>Automation policy</h2>
            <p><span className="badge badge-info">{data.policy.name === 'strict' ? 'Strict' : 'Standard'}</span> <span className="muted small">auto-complete threshold {Math.round(data.policy.auto_complete_threshold * 100)}%</span></p>
            <p className="small muted">{data.policy.description}</p>
            <p className="small">Switch the policy from the top bar. Mismatches and uncertain cases are never auto-completed.</p>
          </div>
          <div className="card">
            <h2>Last batch run</h2>
            {run ? (
              <dl className="kv">
                <dt>Status</dt><dd>{run.status}</dd>
                <dt>Progress</dt><dd>{run.done} / {run.total}</dd>
                <dt>Outcome</dt><dd>{run.ok} OK · {run.mismatch} mismatch · {run.needs_review} review · {run.not_applicable} other</dd>
                <dt>Failed</dt><dd>{run.failed?.length || 0}</dd>
                <dt>Started</dt><dd>{fmtTime(run.started_at)}</dd>
              </dl>
            ) : (
              <p className="muted">No batch run yet.</p>
            )}
            <p style={{ marginTop: 8 }}><Link href="/runs" className="small">Batch run & submission →</Link></p>
          </div>
          <div className="card">
            <h2>AI status</h2>
            {data.ai?.enabled ? (
              <p className="small">Provider <strong>{data.ai.provider}</strong> ({data.ai.model}) · {data.ai.calls} calls · {data.ai.failures} failures</p>
            ) : (
              <p className="small muted">No AI provider configured on the backend - the deterministic rule engine is doing classification and extraction on its own.</p>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
