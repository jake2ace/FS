'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { OutcomeBar } from '@/components/OutcomeBar';
import { RunDonut } from '@/components/RunDonut';
import { api, post, del, fmtTime, type RunState } from '@/lib/api';
import { useRunPulse, useLiveRefresh } from '@/lib/useLiveRefresh';
import { useLanguage } from '@/components/LanguageProvider';

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

  // This page used to poll /api/runs on its own timer while the shared poller polled the
  // same endpoint - two requests a second for identical data. It reads that poll instead,
  // and keeps its own load() for the submission status, which the poller does not carry.
  const pulse = useRunPulse();
  // Counts sit inside these sentences, so they are written per language here rather
  // than left to the dictionary, which matches whole text nodes.
  const { locale } = useLanguage();
  const zh = locale === 'zh';
  useEffect(() => {
    load();
  }, []);
  useEffect(() => {
    if (pulse.items.length) setRuns(pulse.items);
  }, [pulse]);
  // load() also refetches the runs the pulse already has, but at most once every
  // six seconds - cheap next to keeping the submission status and summary in step.
  useLiveRefresh(load);
  const active = runs.find((r) => r.status === 'running');

  // Clearing is destructive and permanent, so the button asks once rather than firing on
  // the first click. Without it there is no way to reset the demo: results are keyed by
  // email id and a re-run overwrites them, so the dashboard keeps whatever was there.
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const clearAll = async () => {
    if (!confirmClear) { setConfirmClear(true); return; }
    setClearing(true);
    try {
      await del('/api/results');
      setConfirmClear(false);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setClearing(false);
    }
  };

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
          <button className={confirmClear ? 'btn btn-sm btn-danger' : 'btn btn-sm'}
                  onClick={clearAll} disabled={clearing || !!active}
                  title="Removes every stored analysis result, on disk as well as in memory">
            {clearing ? 'Clearing…' : confirmClear ? 'Confirm — delete all results' : 'Clear results'}
          </button>
          {confirmClear && !clearing ? (
            <button className="btn btn-sm" onClick={() => setConfirmClear(false)}>Cancel</button>
          ) : null}
        </div>
      </div>
      {error ? <div className="alert alert-risk" style={{ marginBottom: 12 }}>{error}</div> : null}

      <div className="grid grid-2">
        <div className="card">
          <h2>{latest ? `Run ${latest.run_id}` : 'No run yet'}</h2>
          {latest ? (
            <>
              <div className="progress" style={{ margin: '8px 0' }}><div style={{ width: `${latest.total ? Math.round((latest.done / latest.total) * 100) : 0}%` }} /></div>
              {/* Clearing removes the results but keeps the run log: those runs did happen,
                  and the record of them is the evidence that the pipeline completes. Without
                  a word here the page reads as broken - a finished 520/520 run sitting next
                  to a counter that says nothing has been analysed. */}
              {latest.status === 'completed' && subStatus && subStatus.analysed === 0 ? (
                <p className="small muted" style={{ margin: '0 0 10px' }}>
                  The results from this run were cleared. The run itself is kept as a record -
                  analyse the inbox again to repopulate the dashboards.
                </p>
              ) : null}
              {latest.status === 'running' ? (
                // The bar spends its last stretch looking stuck, and an unexplained stall
                // reads as a crash. It is not one: the cases still running are the ones the
                // first model would not settle alone, and the senior pass deliberately
                // thinks for longer. Saying so turns dead time into the thing worth watching.
                <p className="small muted" style={{ margin: '0 0 10px' }}>
                  {zh
                    ? `还有 ${latest.total - latest.done} 封在跑。剩下的都是转去资深复核的案件 —— 那一轮是刻意想得更久的，所以最后几封会比前面几百封慢得多。`
                    : `${latest.total - latest.done} still running. The stragglers are the cases that went to senior review - that pass thinks for longer on purpose, so the last few take far longer than the first few hundred.`}
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
            <h2>Export</h2>
            {subStatus ? (
              <>
                <p className="small">{subStatus.analysed} of {subStatus.total} emails analysed{subStatus.ready ? ' - ready to export.' : ` - ${subStatus.missing_count} still need analysis before export.`}</p>
                <div className="toolbar" style={{ marginBottom: 6 }}>
                  {subStatus.ready ? <a className="btn btn-primary" href="/api/submission?download=true">submission.json</a> : <button className="btn" disabled>Analyse all emails to enable export</button>}
                  <a className="btn" href="/api/export.csv">report.csv</a>
                </div>
                {/* Two exports because they answer two different questions, and saying whose
                    question each one answers is the point - an export nobody can name a reader
                    for is a button, not a feature. */}
                <p className="small muted" style={{ marginTop: 8 }}>
                  <b>submission.json</b> follows sample_submission.json exactly - one record per
                  email_id, for machine checking.
                </p>
                <p className="small muted" style={{ marginTop: 4 }}>
                  <b>report.csv</b> is for the operations team: one row per differing field, with
                  both readings side by side, so the list can be worked outside this screen.
                </p>
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
                  {runs.length - 1 > 3
                    ? (zh ? `最近 3 次，共 ${runs.length - 1} 次` : `latest 3 of ${runs.length - 1}`)
                    : (zh ? `另有 ${runs.length - 1} 次` : `${runs.length - 1} earlier`)}
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
                      mismatch={sum.high_risk || 0} review={sum.needs_review || 0}
                      total={sum.comparison_requests || 0} />
          <p className="small muted" style={{ marginTop: 14, marginBottom: 0 }}>
            <span>The rest were classified and closed - SI requests, invoice queries, operational
            notices and spam. They carry no documents to compare.</span>
          </p>
        </div>
      ) : null}
    </>
  );
}
