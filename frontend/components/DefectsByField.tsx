'use client';

/**
 * Where the drafts go wrong.
 *
 * The first version of this was seven bars of raw counts, which is not a summary -
 * it hands the reader the arithmetic and calls it an insight. A supervisor opening
 * this wants two things answered before they read any bar: is a bad draft usually
 * one mistake or several, and which part of the document is the weak one.
 *
 * So the seven fields collapse into the three groups a shipping person already
 * thinks in, and the two findings are stated as sentences, computed from the same
 * numbers shown underneath rather than written in.
 */

const GROUPS: { name: string; blurb: string; fields: [string, string][] }[] = [
  { name: 'Cargo figures', blurb: 'counted or weighed, so a difference is measurable',
    fields: [['container_count', 'container count'], ['gross_weight_kg', 'gross weight']] },
  { name: 'Parties', blurb: 'names and addresses, often running across lines',
    fields: [['shipper', 'shipper'], ['consignee', 'consignee'], ['notify_party', 'notify party']] },
  { name: 'Route', blurb: 'load and discharge ports',
    fields: [['port_of_loading', 'port of loading'], ['port_of_discharge', 'port of discharge']] },
];

export function DefectsByField(
  { counts, cases, multi }: { counts: Record<string, number>; cases: number; multi: number },
) {
  const groups = GROUPS.map((g) => {
    const parts = g.fields.map(([key, label]) => ({ label, n: counts?.[key] || 0 }))
      .sort((a, b) => b.n - a.n);
    return { ...g, parts, n: parts.reduce((t, p) => t + p.n, 0) };
  }).sort((a, b) => b.n - a.n);

  const total = groups.reduce((t, g) => t + g.n, 0);
  const top = groups[0];
  const topField = groups.flatMap((g) => g.parts).sort((a, b) => b.n - a.n)[0];
  const share = (n: number) => (total ? Math.round((n / total) * 100) : 0);

  return (
    <div className="card">
      <div className="card-head">
        <h2>Where differences turn up</h2>
        <span className="small muted">{total} across {cases} drafts</span>
      </div>

      {total === 0 ? (
        <p className="small muted" style={{ marginTop: 8 }}>
          No differences found yet - run the inbox first.
        </p>
      ) : (
        <>
          <ul className="finding">
            {multi > 0 && (
              <li>
                <b>{multi > cases / 2 ? 'Most' : 'Many'} bad drafts are wrong in more than one
                place</b> - {multi} of {cases} differ on two or more fields, so correcting only
                the difference you were told about will not clear the draft.
              </li>
            )}
            <li>
              <b>{top.name} are the weak spot</b> - {share(top.n)}% of all differences, led by{' '}
              {topField.label} at {topField.n}.
            </li>
          </ul>

          <ul className="dbf">
            {groups.map((g) => (
              <li key={g.name}>
                <div className="dbf-row">
                  <span className="dbf-label">{g.name}</span>
                  <span className="dbf-track">
                    <span className="dbf-bar" style={{ width: `${(g.n / (top.n || 1)) * 100}%` }} />
                  </span>
                  <span className="dbf-n">{g.n}</span>
                  <span className="dbf-pc">{share(g.n)}%</span>
                </div>
                <div className="dbf-parts">
                  {g.parts.map((p) => `${p.label} ${p.n}`).join(' · ')}
                </div>
              </li>
            ))}
          </ul>
          <p className="small muted" style={{ marginTop: 10, marginBottom: 0 }}>
            One draft can differ on more than one field, so the totals here exceed the
            number of drafts.
          </p>
        </>
      )}
    </div>
  );
}
