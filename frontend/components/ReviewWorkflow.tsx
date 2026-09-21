'use client';

import { useEffect, useState } from 'react';
import FieldTable from './FieldTable';
import { post, fmtTime, CATEGORY_LABEL, type Category, type Status, type CaseResult, type FieldRow } from '@/lib/api';

const FIELDS = [
  ['shipper', 'Shipper'], ['consignee', 'Consignee'], ['notify_party', 'Notify party'],
  ['port_of_loading', 'Port of loading'], ['port_of_discharge', 'Port of discharge'],
  ['container_count', 'Container count'], ['gross_weight_kg', 'Gross weight (kg)'],
];
const LABELS: Record<string, string> = {
  NO_ACTION: 'No further action', REVIEW_REQUIRED: 'Human review required',
  PENDING_HUMAN_APPROVAL: 'Pending human approval', RESOLVED_BY_HUMAN: 'Resolved by a person',
};

export default function ReviewWorkflow({ result: r, onChange }: { result: CaseResult; onChange: (r: CaseResult) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');
  const [values, setValues] = useState<Record<string, { si_value: string; bl_value: string }>>({});
  const [files, setFiles] = useState<File[]>([]);
  const [category, setCategory] = useState<Category | ''>(r.category || '');
  const [outcome, setOutcome] = useState<Status>('NEEDS_REVIEW');
  const [defects, setDefects] = useState<string[]>([]);
  const report = r.working_report;
  const pending = r.processing_status === 'PENDING_HUMAN_APPROVAL';

  useEffect(() => {
    const rows: FieldRow[] = report?.fields?.length ? report.fields : r.fields;
    setValues(Object.fromEntries(FIELDS.map(([f]) => {
      const row = rows.find((row) => row.field === f);
      return [f, { si_value: row?.si_value || '', bl_value: row?.bl_value || '' }];
    })));
  }, [r.analysed_at, report?.revision_id]);

  async function submit(path: string, body?: any) {
    setBusy(true); setError('');
    try { onChange(await post<CaseResult>(`/api/cases/${r.email_id}/${path}`, body)); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }
  async function upload() {
    setBusy(true); setError('');
    try {
      if (files.length !== 2 || files.some((f) => f.size > 10_000_000)) throw new Error('Choose one SI and one BL, at most 10 MB each.');
      const encoded = await Promise.all(files.map((f) => new Promise<{ name: string; base64: string }>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve({ name: f.name, base64: String(reader.result).split(',')[1] });
        reader.onerror = () => reject(new Error(`Cannot read ${f.name}`));
        reader.readAsDataURL(f);
      })));
      onChange(await post<CaseResult>(`/api/cases/${r.email_id}/attachments`, { files: encoded, note }));
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }
  if (r.category !== 'BL_COMPARISON' && r.automation !== 'review_required' && !r.manual_review) return null;
  return <div className="card" style={{ marginTop: 14 }}>
    <h2>Human review & corrected BL</h2>
    <p><strong>{LABELS[r.processing_status] || 'Human review'}</strong></p>
    <p className="small muted">Current outcome: {r.status}. The original SI and BL remain unchanged. Corrected copies need your approval.</p>
    {error && <div role="alert" className="alert alert-warn" style={{ marginBottom: 12 }}>{error}</div>}
    {r.status === 'MISMATCH' && !pending && !r.resolved && !r.manual_review && <div style={{ marginBottom: 12 }}>
      <button className="btn btn-primary" disabled={busy} onClick={() => submit('revision')}>Generate corrected BL copy</button>
      <p className="small muted">Uses the verified SI values. Keeps the original file format where fields can be safely located; otherwise explains why manual editing is needed.</p>
    </div>}
    {report && <div className="card" style={{ background: '#f8fafc' }}>
      <h3>Working report · {report.status}</h3>
      <p className="small muted">{report.kind.replaceAll('_', ' ')} · {fmtTime(report.created_at)} · {report.note}</p>
      {report.explanation && <p className="small">{report.explanation}</p>}
      {report.changes?.length > 0 && <ul className="small">{report.changes.map((c: any, i: number) => <li key={i}>
        {c.side} {FIELDS.find(([f]) => f === c.field)?.[1]}: <strong>{c.before || '(missing)'} → {c.after || '(missing)'}</strong>
        {c.evidence && <div className="evidence">SI evidence: {c.evidence}</div>}
      </li>)}</ul>}
      {report.fields?.length > 0 && <details style={{ margin: '12px 0' }}><summary>Seven-field recheck and source evidence</summary><div style={{ overflowX: 'auto' }}><FieldTable rows={report.fields} showEvidence /></div></details>}
      {report.docs?.map((doc: any, i: number) => <details key={i}><summary>{doc.filename} · {doc.detected_type}</summary><pre>{doc.text_preview || doc.read_error || 'No readable source text'}</pre></details>)}
      {report.file_available && <p><a className="btn" href={`/api/cases/${r.email_id}/revision/${report.revision_id}/file`}>Download {report.filename}</a></p>}
      {report.deleted_at && <p className="small">Rejected copy deleted at {fmtTime(report.deleted_at)}. The review record is retained.</p>}
      {pending && <>
        <p className="small">Review the changes and the seven-field recheck before adopting. Adopting keeps the corrected file. Rejecting deletes the server copy.</p>
        <div className="toolbar">
          <button className="btn btn-safe" disabled={busy} onClick={() => submit('decision', { action: 'approve_revision', revision_id: report.revision_id, note })}>Adopt revision{report.file_available ? ' & keep copy' : ''}</button>
          <button className="btn btn-danger" disabled={busy} onClick={() => submit('decision', { action: 'reject_revision', revision_id: report.revision_id, note })}>Reject{report.file_available ? ' & delete copy' : ''}</button>
        </div>
      </>}
      {report.decision && <p className="small">{report.decision.action} by {report.decision.by} · {fmtTime(report.decision.at)}</p>}
    </div>}
    <label className="small" htmlFor="review-note">Review note / reason for a correction</label>
    <textarea id="review-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} style={{ minHeight: 70 }} />
    {!pending && !r.resolved && !r.manual_review && r.category === 'BL_COMPARISON' && <>
      <details style={{ marginTop: 12 }}>
        <summary>Optional AI assistance: recheck extracted readings</summary>
        <p className="small muted">Use this when the system read a document incorrectly. Check all seven values against the actual sources. This updates a working report; it does not edit a BL file.</p>
        <div style={{ overflowX: 'auto' }}><table><thead><tr><th>Field</th><th>SI reading</th><th>BL reading</th></tr></thead><tbody>
          {FIELDS.map(([f, label]) => <tr key={f}><td>{label}</td>{(['si_value', 'bl_value'] as const).map((side) => <td key={side}>
            <input aria-label={`${label} ${side === 'si_value' ? 'SI' : 'BL'}`} value={values[f]?.[side] || ''} onChange={(e) => setValues((v) => ({ ...v, [f]: { ...v[f], [side]: e.target.value } }))} style={{ width: '100%', minWidth: 180 }} />
          </td>)}</tr>)}
        </tbody></table></div>
        <button className="btn" disabled={busy || !note.trim()} onClick={() => submit('readings', { fields: values, note })}>Recheck confirmed readings</button>
      </details>
      <details style={{ marginTop: 12 }}>
        <summary>Optional AI assistance: recheck replacement attachments</summary>
        <p className="small muted">Choose both documents. They are stored separately and rechecked; the original inbox files remain unchanged.</p>
        <input aria-label="Replacement SI and BL" type="file" multiple accept=".txt,.pdf,.docx,.xlsx,.png,.jpg,.jpeg" onChange={(e) => setFiles(Array.from(e.target.files || []))} />
        <button className="btn" disabled={busy || files.length !== 2 || !note.trim()} onClick={upload}>Recheck supplied documents</button>
      </details>
      <div className="toolbar" style={{ marginTop: 12 }}>
        {r.status === 'OK' && r.automation !== 'review_required' && <button className="btn btn-safe" disabled={busy} onClick={() => submit('decision', { action: 'confirm', note })}>Confirm completed check</button>}
        <button className="btn" disabled={busy} onClick={() => submit('decision', { action: 'escalate', note })}>Keep in human review</button>
      </div>
    </>}
    {!pending && !r.resolved && <div style={{ marginTop: 20 }}>
      <h3>Final human handling</h3>
      <p className="small muted">Record what you confirmed from the original documents or completed outside the system. Completing this form ends processing; it does not call AI.</p>
      <div className="toolbar">
        <label>Confirmed email category <select aria-label="Confirmed email category" value={category} onChange={(e) => { setCategory(e.target.value as Category); setOutcome('NEEDS_REVIEW'); setDefects([]); }}>
          <option value="">Choose a category</option>
          {Object.entries(CATEGORY_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <label>Confirmed outcome <select aria-label="Confirmed outcome" value={outcome} onChange={(e) => { setOutcome(e.target.value as Status); setDefects([]); }}>
          <option value="NEEDS_REVIEW">Still needs human handling</option>
          <option value="OK">{category === 'BL_COMPARISON' ? 'Original documents confirmed consistent' : 'Category confirmed; no BL comparison required'}</option>
          {category === 'BL_COMPARISON' && <option value="MISMATCH">Confirmed differences; handled by a person</option>}
        </select></label>
      </div>
      {outcome === 'MISMATCH' && <fieldset><legend>Confirmed differing fields</legend>{FIELDS.map(([f, label]) => <label key={f} style={{ display: 'block' }}><input type="checkbox" checked={defects.includes(f)} onChange={(e) => setDefects((prev) => e.target.checked ? [...prev, f] : prev.filter((x) => x !== f))} /> {label}</label>)}</fieldset>}
      <p className="small">The outcome describes the original email and attachments. Use the review note above to record your evidence and how the issue was handled.</p>
      <div className="toolbar">
        <button className="btn" disabled={busy || !category || !note.trim() || (outcome === 'MISMATCH' && !defects.length)} onClick={() => submit('manual-review', { category, status: outcome, defect_fields: defects, note, complete: false })}>Save human progress</button>
        <button className="btn btn-safe" disabled={busy || !category || !note.trim() || outcome === 'NEEDS_REVIEW' || (outcome === 'MISMATCH' && !defects.length)} onClick={() => submit('manual-review', { category, status: outcome, defect_fields: defects, note, complete: true })}>Complete human handling</button>
      </div>
    </div>}
    {r.manual_review && <p className="small">Human record: {r.manual_review.note} · {r.manual_review.by} · {fmtTime(r.manual_review.at)}. Further handling stays with a person.</p>}
    {r.resolved && <button className="btn" disabled={busy} onClick={() => submit('decision', { action: 'reopen', note })}>Reopen for review</button>}
    {r.history?.length > 0 && <details style={{ marginTop: 12 }}><summary>Review history ({r.history.length})</summary>
      <ul className="small">{r.history.map((event: any, i: number) => {
        const previous = event.report || event.previous?.working_report;
        return <li key={i}>{fmtTime(event.at)} · {event.event}{event.action ? ` · ${event.action}` : ''}{event.note ? ` · ${event.note}` : ''}
          {previous?.file_available && previous?.decision?.action === 'approve_revision' && <> · <a href={`/api/cases/${r.email_id}/revision/${previous.revision_id}/file`}>Download retained copy</a></>}
        </li>;
      })}</ul>
    </details>}
  </div>;
}
