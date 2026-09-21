'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { OutcomeBar } from '@/components/OutcomeBar';
import { RunDonut } from '@/components/RunDonut';
import { api, post, fmtTime, type RunState } from '@/lib/api';

export default function BatchRun() {
  const [runs, setRuns] = useState<RunState[]>([]);
  const [subStatus, setSubStatus] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sum, setSum] = useState<any>(null);

  const load = () =>
    Promise.all([api<{ items: RunState[] }>('/api/runs'), api('/api/submission/status'), api<any>('/api/dashboard')])
      .then(([r, s, d]) => {
        setRuns(r.items);
        setSubStatus(s);
        setSum(d.summary);
        setError(null);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);
  const active = runs.find((r) => r.status === 'running');
  useEffect(() => {
    if (!active) return;
    // Fast while something is moving, relaxed once it is not: this page is often the
    // one left open on a second screen during judging.
    const t = setInterval(load, active ? 1500 : 6000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!active]);

  const start = async () => {
    setBusy(true);
    try {
      await post('/api/runs/full-inbox', { force });
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const cancel = async (id: string) => {
    try {
      await post(`/api/runs/${id}/cancel`);
      await load();
    } catch (e: any) {
      setError(e.message);
    }
  };
  const retry = async (runId: string, emailId: string) => {
    try {
      await post(`/api/runs/${runId}/retry/${emailId}`);
      await load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const latest = runs[0];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Batch Run</h1>
          <div className="sub">Process the complete inbox, watch progress, retry failures and export the submission JSON.</div>
        </div>
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <label className="small"><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> re-analyse already analysed emails</label>
          <button className="btn btn-primary" onClick={start} disabled={busy || !!active}>{active ? 'Running…' : 'Run full inbox'}</button>
        </div>
      </div>
      {error ? <div className="alert alert-risk" style={{ marginBottom: 12 }}>{error}</div> : null}

      <div className="grid grid-2">
        <div className="card">
          <h2>{latest ? `Run ${latest.run_id}` : 'No run yet'}</h2>
          {latest ? (
            <>
              <div className="progress" style={{ margin: '8px 0' }}><div style={{ width: `${latest.total ? Math.round((latest.done / latest.total) * 100) : 0}%` }} /></div>
              {latest.status === 'running' ? (
                // The bar spends its last stretch looking stuck, and an unexplained stall
                // reads as a crash. It is not one: the cases still running are the ones the
                // first model would not settle alone, and the senior pass deliberately
                // thinks for longer. Saying so turns dead time into the thing worth watching.
                <p className="small muted" style={{ margin: '0 0 10px' }}>
                  {latest.total - latest.done} still running. The stragglers are the cases that
                  went to senior review - that pass thinks for longer on purpose, so the last
                  few take far longer than the first few hundred.
                </p>
              ) : null}
              <div className="run-split">
                <dl className="kv">
                  <dt>Status</dt><dd>{latest.status}{latest.current ? ` · analysing ${latest.current}` : ''}</dd>
                  <dt>Progress</dt><dd>{latest.done} / {latest.total}</dd>
                  <dt>OK</dt><dd>{latest.ok}</dd>
                  <dt>Mismatch</dt><dd>{latest.mismatch}</dd>
                  <dt>Needs review</dt><dd>{latest.needs_review}</dd>
                  <dt>Other categories</dt><dd>{latest.not_applicable}</dd>
                  <dt>Failed</dt><dd>{latest.failed.length}</dd>
                  <dt>Started</dt><dd>{fmtTime(latest.started_at)}</dd>
                  <dt>Finished</dt><dd>{fmtTime(latest.finished_at)}</dd>
                </dl>
                <RunDonut ok={latest.ok} mismatch={latest.mismatch} review={latest.needs_review}
                          other={latest.not_applicable} failed={latest.failed.length} />
              </div>
              {latest.status === 'running' ? <button className="btn btn-sm" style={{ marginTop: 8 }} onClick={() => cancel(latest.run_id)}>Cancel run</button> : null}
              {latest.failed.length ? (
                <div style={{ marginTop: 12 }}>
                  <h3>Failed items</h3>
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>Email</th><th>Error</th><th></th></tr></thead>
                      <tbody>
                        {latest.failed.map((f) => (
                          <tr key={f.email_id}>
                            <td className="mono">{f.email_id}</td>
                            <td className="small">{f.error}</td>
                            <td className="right"><button className="btn btn-sm" onClick={() => retry(latest.run_id, f.email_id)}>Retry</button></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}
            </>
          ) : (
            <p className="muted">Start a run to process all emails. Already analysed emails are skipped unless you tick re-analyse.</p>
          )}
        </div>
        <div>
          <div className="card">
            <h2>Submission JSON</h2>
            {subStatus ? (
              <>
                <p className="small">{subStatus.analysed} of {subStatus.total} emails analysed{subStatus.ready ? ' - ready to export.' : ` - ${subStatus.missing_count} still need analysis before export.`}</p>
                {subStatus.ready ? <a className="btn btn-primary" href="/api/submission?download=true">Download submission.json</a> : <button className="btn" disabled>Analyse all emails to enable export</button>}
                <p className="small muted" style={{ marginTop: 8 }}>Shape follows sample_submission.json exactly (category, status, review_reason, defect_fields, has_defect for every email_id).</p>
              </>
            ) : (
              <p className="muted small">…</p>
            )}
          </div>
          <div className="card">
            <div className="card-head">
              <h2>Previous runs</h2>
              {runs.length > 1 ? (
                <span className="small muted">
                  {runs.length - 1 > 3 ? `latest 3 of ${runs.length - 1}` : `${runs.length - 1} earlier`}
                </span>
              ) : null}
            </div>
            {runs.length <= 1 ? <p className="muted small">None.</p> : (
              // Only the three most recent runs are shown. The history grows with every run,
              // and a card that either stretches down the page or scrolls inside itself reads as
              // clutter next to the run it belongs to. The count in the header says how many exist.
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Run</th><th>Status</th><th className="right">Done</th><th className="right">Mismatch</th><th className="right">Review</th></tr></thead>
                  <tbody>
                    {runs.slice(1, 4).map((r) => (
                      <tr key={r.run_id}><td className="mono">{r.run_id}</td><td>{r.status}</td><td className="right">{r.done}/{r.total}</td><td className="right">{r.mismatch}</td><td className="right">{r.needs_review}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <p className="footer-note">Results live in the backend cache; <Link href="/review">open the review queue</Link> once the run finishes.</p>
        </div>
      </div>

      {sum && sum.comparison_requests > 0 ? (
        <div className="card" style={{ marginTop: 14 }}>
          <div className="card-head">
            <h2>Where the work landed</h2>
            <span className="small muted">{sum.comparison_requests} / {sum.analysed} emails</span>
          </div>
          <p className="small muted" style={{ marginTop: -2, marginBottom: 16 }}>
            <b>{sum.comparison_requests}</b> of the <b>{sum.analysed}</b> emails{' '}
            <span>asked for a Shipping Instruction and a draft Bill of Lading to be checked against
            each other - those are the only ones that reach the document comparison. This is what
            happened to them.</span>
          </p>
          <OutcomeBar safe={sum.safe_completed || 0} draft={sum.awaiting_draft || 0}
                      mismatch={sum.high_risk || 0} review={sum.needs_review || 0} />
          <p className="small muted" style={{ marginTop: 14, marginBottom: 0 }}>
            <span>The rest were classified and closed - SI requests, invoice queries, operational
            notices and spam. They carry no documents to compare.</span>
          </p>
        </div>
      ) : null}
    </>
  );
}
