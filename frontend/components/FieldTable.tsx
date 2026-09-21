import type { FieldRow } from '@/lib/api';

export default function FieldTable({ rows, showEvidence }: { rows: FieldRow[]; showEvidence?: boolean }) {
  if (!rows || rows.length === 0) return <p className="muted">No field comparison available for this case.</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th style={{ width: 160 }}>Field</th>
            <th>SI (reference)</th>
            <th>Draft BL</th>
            <th style={{ width: 70 }}>Match</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const cls = r.match === false ? 'row-mismatch' : r.match === null ? 'row-missing' : '';
            const mark = r.match === true ? <span className="match-yes">✓</span> : r.match === false ? <span className="match-no">✕</span> : <span className="match-na">?</span>;
            return (
              <tr key={r.field} className={cls}>
                <td>
                  <strong>{r.label}</strong>
                </td>
                <td>
                  {r.si_value ?? <span className="muted">— missing —</span>}
                  {showEvidence && r.si_evidence ? <div className="evidence">{r.si_evidence}</div> : null}
                </td>
                <td>
                  {r.bl_value ?? <span className="muted">— missing —</span>}
                  {showEvidence && r.bl_evidence ? <div className="evidence">{r.bl_evidence}</div> : null}
                </td>
                <td>{mark}</td>
                <td className="small">{r.reason}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
