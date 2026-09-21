'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import FieldTable from '@/components/FieldTable';
import ReviewWorkflow from '@/components/ReviewWorkflow';
import { CategoryBadge, StatusBadge } from '@/components/StatusBadge';
import { api, post, pct, fmtTime, REVIEW_LABEL, type CaseResult } from '@/lib/api';

const DOC_TYPE_LABEL: Record<string, string> = {
  SI: 'Shipping Instruction',
  BL: 'Draft Bill of Lading',
  COMMERCIAL_INVOICE: 'Commercial Invoice',
  PACKING_LIST: 'Packing List',
  CERTIFICATE_OF_ORIGIN: 'Certificate of Origin',
  UNKNOWN: 'Unknown document',
};

export default function CaseDetail() {
  const params = useParams<{ id: string }>();
  const id = params?.id as string;
  const [email, setEmail] = useState<any>(null);
  const [result, setResult] = useState<CaseResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [draft, setDraft] = useState<string | null>(null);
  const [showEvidence, setShowEvidence] = useState(false);
  const [docText, setDocText] = useState<Record<number, string>>({});

  const load = () =>
    api(`/api/emails/${id}`)
      .then((d) => {
        setEmail(d);
        setResult(d.result);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    if (id) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const analyse = async () => {
    setBusy(true);
    setDraft(null);
    try {
      const r = await post<CaseResult>(`/api/analyse/${id}?force=true&explain=true`);
      setResult(r);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const decide = async (action: string) => {
    setBusy(true);
    try {
      const r = await post<CaseResult>(`/api/cases/${id}/decision`, { action, note: note || undefined });
      setResult(r);
      setNote('');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const makeDraft = async () => {
    try {
      const d = await post<{ draft: string }>(`/api/cases/${id}/correction-draft`);
      setDraft(d.draft);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const loadDocText = async (index: number) => {
    if (docText[index] !== undefined) return;
    try {
      const d = await api(`/api/emails/${id}/attachments/${index}/text`);
      setDocText((prev) => ({ ...prev, [index]: d.readable ? d.text : `(unreadable: ${d.error})` }));
    } catch (e: any) {
      setDocText((prev) => ({ ...prev, [index]: `(error: ${e.message})` }));
    }
  };

  if (error && !email) return <div className="alert alert-risk">{error}</div>;
  if (!email) return <div className="empty">Loading…</div>;
  const rec = email.email;
  const r = result;
  const alertCls = !r ? 'alert-info' : r.status === 'MISMATCH' ? 'alert-risk' : r.status === 'NEEDS_REVIEW' || r.ui_status === 'Needs review' ? 'alert-warn' : r.ui_status === 'Safe to complete' ? 'alert-safe' : 'alert-info';

  return (
    <>
      <div className="page-head">
        <div>
          <div className="small muted"><Link href="/inbox">Smart Inbox</Link> / <span className="mono">{id}</span></div>
          <h1>{rec.subject}</h1>
          <div className="sub">From {rec.from} · {rec.attachments.length} attachment{rec.attachments.length === 1 ? '' : 's'}</div>
        </div>
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <button className="btn btn-primary" onClick={analyse} disabled={busy || !!r?.manual_review || !!r?.resolved || r?.processing_status === 'PENDING_HUMAN_APPROVAL'}>{busy ? 'Working…' : r ? 'Re-analyse' : 'Analyse this email'}</button>
        </div>
      </div>
      {error ? <div className="alert alert-risk" style={{ marginBottom: 12 }}>{error}</div> : null}

      {!r ? (
        <div className="card empty">This email has not been analysed yet. Click <strong>Analyse this email</strong> to classify it and, for comparison requests, check the SI against the draft BL.</div>
      ) : (
        <>
          <div className={`alert ${alertCls}`} style={{ marginBottom: 14 }}>
            <div className="small muted">{r.manual_review ? 'Human conclusion' : 'Original attachment check'} · {r.status}</div>
            <div className="headline">{r.headline}</div>
            <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <StatusBadge ui={r.ui_status} status={r.status} />
              <CategoryBadge category={r.category} />
              <span className="small">confidence {pct(r.confidence)}</span>
              <span className="small muted">· evidence {r.evidence_available ? 'available' : 'incomplete'}</span>
              <span className="small muted">· {r.decision_method === 'human' ? 'Human decision' : r.decision_method === 'ai' ? 'AI decision' : 'AI response needs review'}{r.ai_model && !r.manual_review ? ` · ${r.ai_model}` : ''}</span>
              {r.decision ? <span className="badge badge-neutral">decision: {r.decision.action}</span> : null}
              {r.resolved ? <span className="badge badge-safe">resolved</span> : null}
            </div>
            <p style={{ marginTop: 10 }}>{r.explanation}</p>
            <p><strong>Suggested action:</strong> {r.suggested_action}</p>
            {r.review_detail ? <p className="small"><strong>{REVIEW_LABEL[r.review_reason || ''] || 'Review reason'}:</strong> {r.review_detail}</p> : null}
          </div>

          {r.category === 'BL_COMPARISON' && r.fields.length > 0 ? (
            <div className="card">
              <div className="card-head">
                <h2>Seven-field comparison (SI is the reference)</h2>
                <label className="small"><input type="checkbox" checked={showEvidence} onChange={(e) => setShowEvidence(e.target.checked)} /> show source lines</label>
              </div>
              <FieldTable rows={r.fields} showEvidence={showEvidence} />
            </div>
          ) : null}

          {!!r.decision_chain?.length && <div className="card" style={{ marginTop: 14 }}>
            <h2>Processing steps</h2>
            <ol>{r.decision_chain.map((step, i) => <li key={i}>
              <strong>{step.tier === 'primary' ? 'Primary AI' : step.tier === 'senior' ? 'Senior AI' : 'Human handling'}</strong>
              {step.model ? ` · ${step.model}` : ''}{step.thinking ? ` · thinking ${step.reasoning_effort}` : ''} · {step.available === false ? 'Not configured / unavailable; handed to a person' : step.status || 'Review'}
              {step.reason && <p className="small">{step.reason}</p>}
              {step.unconfirmed_assessment && <p className="small">Unconfirmed AI observation: {step.unconfirmed_assessment}</p>}
            </li>)}</ol>
          </div>}
          <ReviewWorkflow key={id} result={r} onChange={setResult} />

          <div className="grid grid-2" style={{ marginTop: 14 }}>
            <div className="card">
              <h2>Source evidence</h2>
              <details open={r.category !== 'BL_COMPARISON'}>
                <summary>Email body</summary>
                <pre>{rec.body}</pre>
              </details>
              {r.docs.map((d, i) => (
                <details key={d.path} style={{ marginTop: 8 }} onToggle={(e: any) => { if (e.currentTarget.open && (d.recovery === 'not_needed' || !d.recovery)) loadDocText(i); }}>
                  <summary>
                    {d.filename} · <span className="muted">{DOC_TYPE_LABEL[d.detected_type] || d.detected_type}</span> · {d.format.toUpperCase()} ·{' '}
                    {d.readable ? <span className="match-yes">readable</span> : <span className="match-no">unreadable</span>}
                    {d.read_error ? <span className="muted"> ({d.read_error})</span> : null}
                    {d.readable ? <span className="muted"> · extracted by {d.extraction_method}</span> : null}
                    {d.recovery && d.recovery !== 'not_needed' ? <span className="muted"> · recovery: {d.recovery}</span> : null}
                  </summary>
                  <pre>{docText[i] !== undefined ? docText[i] : d.text_preview || '(loading…)'}</pre>
                </details>
              ))}
              {r.docs.length === 0 && rec.attachments.length === 0 ? <p className="muted small" style={{ marginTop: 8 }}>No attachments on this email.</p> : null}
              <dl className="kv" style={{ marginTop: 12 }}>
                <dt>Classification</dt><dd>{r.category} · {pct(r.category_confidence)} · {r.category_method}</dd>
                <dt>Why</dt><dd className="small">{r.category_reason}</dd>
                <dt>Intent</dt><dd>{r.intent}</dd>
                <dt>Analysed</dt><dd>{fmtTime(r.analysed_at)} · {r.duration_ms} ms</dd>
              </dl>
              {r.warnings.length ? (
                <div className="alert alert-warn small" style={{ marginTop: 10 }}>
                  <strong>Notes</strong>
                  <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>{r.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
                </div>
              ) : null}
            </div>

            <div>
              {r.senior_review ? (
                <div className="card" style={{ marginBottom: 14 }}>
                  <h2>Senior model review</h2>
                  {r.senior_review.available ? (
                    <>
                      <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                        <span className={`badge ${r.senior_review.agrees ? 'badge-safe' : 'badge-warn'}`}>
                          {r.senior_review.outcome === 'NEEDS_REVIEW' ? 'Human review required' : 'Senior assessment validated'}
                        </span>
                        <span className="small muted">
                          {r.senior_review.model} · opinion {r.senior_review.outcome || '–'} · confidence {pct(r.senior_review.confidence)}
                        </span>
                      </div>
                      {r.senior_review.assessment ? <p className="small" style={{ marginTop: 8 }}>{r.senior_review.assessment}</p> : null}
                      {r.senior_review.overrides.length ? (
                        <div className="small" style={{ marginTop: 8 }}>
                          <strong>Applied (shown to a person before release)</strong>
                          <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>{r.senior_review.overrides.map((o, i) => <li key={i}>{o}</li>)}</ul>
                        </div>
                      ) : null}
                      {r.senior_review.rejected.length ? (
                        <div className="small muted" style={{ marginTop: 8 }}>
                          <strong>Ignored - not supported by the documents</strong>
                          <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>{r.senior_review.rejected.map((o, i) => <li key={i}>{o}</li>)}</ul>
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <p className="small muted" style={{ marginTop: 6 }}>The senior model could not be reached; this case was not double-checked and waits for a person.</p>
                  )}
                  <details style={{ marginTop: 8 }}>
                    <summary className="small muted">Why the senior model was consulted</summary>
                    <ul className="small" style={{ margin: '4px 0 0 16px', padding: 0 }}>{r.senior_review.triggers.map((t, i) => <li key={i}>{t}</li>)}</ul>
                  </details>
                </div>
              ) : null}
              {r.category === 'BL_COMPARISON' ? (
                <div className="card">
                  <h2>Correction email</h2>
                  {draft === null ? (
                    <>
                      <p className="small muted">Only if external communication is needed. The draft is editable text; nothing is sent from this workspace.</p>
                      <div className="toolbar" style={{ marginBottom: 0 }}>
                        <button className="btn" onClick={makeDraft}>Generate correction email draft</button>
                        <span className="small muted">or Not now</span>
                      </div>
                    </>
                  ) : (
                    <>
                      <textarea value={draft} onChange={(e) => setDraft(e.target.value)} />
                      <div className="toolbar" style={{ marginBottom: 0, marginTop: 8 }}>
                        <button className="btn btn-sm" onClick={() => navigator.clipboard?.writeText(draft)}>Copy to clipboard</button>
                        <button className="btn btn-sm" onClick={() => setDraft(null)}>Discard</button>
                        <span className="small muted">Sending stays a human step in your mail client.</span>
                      </div>
                    </>
                  )}
                </div>
              ) : null}
            </div>
          </div>
        </>
      )}
    </>
  );
}
