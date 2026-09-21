'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { StatusBadge } from '@/components/StatusBadge';
import { api, post, fmtTime, REVIEW_LABEL } from '@/lib/api';
import { useLiveRefresh } from '@/lib/useLiveRefresh';
import { DefectsByField } from '@/components/DefectsByField';

export default function TodayWorkCentre() {
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [guide, setGuide] = useState(false);

  useEffect(() => {
    try { setGuide(window.localStorage.getItem('fs-guide-done') !== '1'); } catch { setGuide(true); }
  }, []);
  const closeGuide = () => {
    setGuide(false);
    try { window.localStorage.setItem('fs-guide-done', '1'); } catch {}
  };

  const load = () =>
    api('/api/dashboard')
      .then((d) => {
        setData(d);
        setError(null);   // a recovered request clears the previous failure
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);
  useLiveRefresh(load);

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
  const example = (data.priority || []).find((p: any) => p.status === 'MISMATCH') || (data.priority || [])[0];
  const needPerson = (s.high_risk || 0) + (s.needs_review || 0) + (s.awaiting_draft || 0);
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
            {run?.status === 'running'
              ? `Batch run ${run.done} / ${run.total}…`
              : s.analysed === 0 ? 'Analyse the full inbox' : 'Analyse remaining emails'}
          </button>
        </div>
      </div>

      {guide ? (
        <div className="guide">
          <div className="guide-steps">
            {s.analysed === 0 ? (
              <>
                <div className="guide-step"><span className="guide-num">1</span><div>
                  <b>Run the analysis</b><span>the system reads every email and both attachments</span></div></div>
                <div className="guide-step"><span className="guide-num">2</span><div>
                  <b>See what needs attention</b><span>it sorts the inbox by how urgent each case is</span></div></div>
                <div className="guide-step"><span className="guide-num">3</span><div>
                  <b>You decide</b><span>the system never acts on a case by itself</span></div></div>
              </>
            ) : (
              <>
                <div className="guide-step"><span className="guide-num">1</span><div>
                  <b>Your work is already sorted</b><span>most urgent first - start at the top</span></div></div>
                <div className="guide-step"><span className="guide-num">2</span><div>
                  <b>Open a case to check it</b><span>every reading quotes the line it came from</span></div></div>
                <div className="guide-step"><span className="guide-num">3</span><div>
                  <b>You decide what happens</b><span>confirm, hand it on, or send it back</span></div></div>
              </>
            )}
          </div>
          {s.analysed === 0 ? (
            <button className="btn btn-primary" onClick={startRun} disabled={starting}>Analyse the full inbox</button>
          ) : example ? (
            <Link href={`/cases/${example.email_id}`} className="btn btn-primary">Start with the most urgent →</Link>
          ) : null}
          <button className="guide-x" onClick={closeGuide} title="Hide this guide" aria-label="Hide this guide">✕</button>
        </div>
      ) : null}

      <div className="grid grid-7">
        <div className="card tile"><div className="tile-label">Comparison requests</div><div className="tile-value">{s.comparison_requests}</div><div className="tile-hint">of {s.analysed} analysed emails</div></div>
        <div className="card tile risk"><div className="tile-label">Mismatches</div><div className="tile-value">{s.high_risk}</div><div className="tile-hint">at least one of the seven fields differs</div></div>
        <div className="card tile warn"><div className="tile-label">Needs review</div><div className="tile-value">{s.needs_review}</div><div className="tile-hint">missing / unreadable / blank</div></div>
        <div className="card tile safe"><div className="tile-label">Safe completed</div><div className="tile-value">{s.safe_completed}</div><div className="tile-hint">auto-completed under {s.policy} policy</div></div>
        <div className="card tile"><div className="tile-label">Draft BL requested</div><div className="tile-value">{s.awaiting_draft ?? 0}</div><div className="tile-hint">we have to send the document out first</div></div>
        <div className="card tile"><div className="tile-label">Pending approval</div><div className="tile-value">{s.pending_approval}</div><div className="tile-hint">rechecked revisions awaiting a person</div></div>
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
            <div className="table-wrap">
              <table>
                <thead><tr><th>Email</th><th>Finding</th><th>Status</th><th></th></tr></thead>
                <tbody>
                  {data.priority.map((p: any) => (
                    <tr key={p.email_id}>
                      <td className="mono nowrap">{p.email_id}</td>
                      <td>
                        <div>{p.headline}</div>
                        <div className="muted small truncate">{p.subject}</div>
                      </td>
                      <td><StatusBadge ui={p.ui_status} status={p.status} />{p.review_reason ? <div className="small muted">{REVIEW_LABEL[p.review_reason] || p.review_reason}</div> : null}</td>
                      <td className="right"><Link href={`/cases/${p.email_id}`} className="btn btn-sm">Open</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div>
          <div className="triage" style={{ marginBottom: 12 }}>
            <div className="triage-head">
              <span className="n">{needPerson}</span>
              <span className="t">cases are waiting on you</span>
            </div>
            <div className="triage-sub">Listed most urgent first. The system decided nothing on its own.</div>
            {needPerson > 0 ? (
              <>
                <ul className="triage-list">
                  <li><span className="dot" style={{ background: '#c23b2b' }} /><span className="n">{s.high_risk}</span>
                    <span className="lbl"><b>Mismatch found</b><span>contact the carrier and correct the draft</span></span></li>
                  <li><span className="dot" style={{ background: '#cf8b1a' }} /><span className="n">{s.needs_review}</span>
                    <span className="lbl"><b>The system would not decide</b><span>read the evidence and make the call</span></span></li>
                  <li><span className="dot" style={{ background: '#7a5ea8' }} /><span className="n">{s.awaiting_draft}</span>
                    <span className="lbl"><b>Draft BL requested</b><span>send the document, then it can be compared</span></span></li>
                </ul>
                <Link href="/review" className="btn btn-primary">Open the review queue</Link>
              </>
            ) : (
              <div className="triage-empty">Nothing is waiting on a person right now.</div>
            )}
          </div>
          <DefectsByField counts={s.defects_by_field || {}} cases={s.defect_cases || 0} multi={s.defect_cases_multi || 0} />
          <div className="card" style={{ marginTop: 12 }}>
            <h2>Automation policy</h2>
            <p><span className="badge badge-info">{data.policy.name === 'strict' ? 'Strict' : 'Standard'}</span> <span className="muted small">AI decides; source evidence checked</span></p>
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
              <p className="small muted">AI is unavailable. Configure the provider before analysis; no rule-based fallback is used.</p>
            )}
          </div>
        </div>
      </div>

      {data.actions && data.actions.length > 0 ? (
        <div className="card" style={{ marginTop: 14 }}>
          <div className="card-head">
            <h2>Action list - draft BL requested</h2>
            <span className="small muted">{data.actions_total} emails</span>
          </div>
          <p className="small muted">These emails ask our team to send out a draft BL so the customer can check it. No document is attached yet, so there is nothing for the AI to compare and nothing for a reviewer to decide - the work is to send the document, which is why they stay out of the review queue.</p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Email</th><th>Request</th><th>Action</th><th></th></tr></thead>
              <tbody>
                {data.actions.map((a: any) => (
                  <tr key={a.email_id}>
                    <td className="mono nowrap">{a.email_id}</td>
                    <td className="muted small truncate">{a.subject}</td>
                    <td className="small">{a.suggested_action}</td>
                    <td className="right"><Link href={`/cases/${a.email_id}`} className="btn btn-sm">Open</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.actions_total > data.actions.length ? (
            <p className="small muted">Showing the first {data.actions.length} of {data.actions_total}.</p>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
