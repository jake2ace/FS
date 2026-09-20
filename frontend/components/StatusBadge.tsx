import { CATEGORY_LABEL } from '@/lib/api';

export function StatusBadge({ ui, status }: { ui?: string; status?: string }) {
  const label = ui || status || 'Not analysed';
  let cls = 'badge-neutral';
  if (label === 'Safe to complete' || status === 'OK') cls = 'badge-safe';
  if (label === 'High risk' || status === 'MISMATCH') cls = 'badge-risk';
  if (label === 'Needs review' || status === 'NEEDS_REVIEW') cls = 'badge-warn';
  if (label === 'Awaiting draft BL' || label === 'No action') cls = 'badge-info';
  if (!ui && !status) cls = 'badge-neutral';
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function CategoryBadge({ category }: { category?: string }) {
  if (!category) return <span className="badge badge-neutral">–</span>;
  const cls = category === 'BL_COMPARISON' ? 'badge-info' : category === 'SPAM' ? 'badge-neutral' : 'badge-neutral';
  return <span className={`badge ${cls}`}>{CATEGORY_LABEL[category] || category}</span>;
}

export function RiskBadge({ risk }: { risk?: string }) {
  if (!risk || risk === 'none') return <span className="badge badge-neutral">none</span>;
  const cls = risk === 'high' ? 'badge-risk' : risk === 'medium' ? 'badge-warn' : 'badge-safe';
  return <span className={`badge ${cls}`}>{risk}</span>;
}
