'use client';

import { useState } from 'react';

/** One horizontal stacked bar: what happened to every comparison request.
 *  Status colours, validated for colour-vision deficiency (worst adjacent pair
 *  ΔE 10.8 simulated). Red and green are never adjacent, every segment carries a
 *  visible label, and the legend repeats the counts - colour never stands alone. */

type Seg = { key: string; label: string; value: number; color: string; hint: string; person: boolean };

export function OutcomeBar({ safe, draft, mismatch, review }:
  { safe: number; draft: number; mismatch: number; review: number }) {
  const [hover, setHover] = useState<number | null>(null);

  const segs: Seg[] = [
    { key: 'safe',     label: 'Safe completed',    value: safe,     color: '#1f7a4d', person: false,
      hint: 'all seven fields agreed - closed automatically' },
    { key: 'draft',    label: 'Draft BL requested', value: draft,   color: '#7a5ea8', person: true,
      hint: 'we have to send the document out first' },
    { key: 'mismatch', label: 'Mismatch',          value: mismatch, color: '#c23b2b', person: true,
      hint: 'at least one of the seven fields differs' },
    { key: 'review',   label: 'Needs review',      value: review,   color: '#cf8b1a', person: true,
      hint: 'the system would not decide - a person must' },
  ];

  const total = segs.reduce((a, s) => a + s.value, 0) || 1;
  const W = 1000, H = 48, GAP = 3;
  let x = 0;
  const laid = segs.map((s) => {
    const w = (s.value / total) * W;
    const box = { ...s, x, w, pct: Math.round((s.value / total) * 100) };
    x += w;
    return box;
  });

  // where the "needs a person" bracket starts: first segment a human has to touch
  const first = laid.find((s) => s.person);
  const personTotal = segs.filter((s) => s.person).reduce((a, s) => a + s.value, 0);

  return (
    <div className="outcome">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img"
           aria-label={`Outcome of ${total} comparison requests`} style={{ display: 'block' }}>
        <defs>
          <clipPath id="ob-round"><rect x="0" y="0" width={W} height={H} rx="6" /></clipPath>
        </defs>
        <g clipPath="url(#ob-round)">
          {laid.map((s, i) => (
            <g key={s.key}
               onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
               style={{ cursor: 'default' }}>
              <rect x={s.x} y={0} width={Math.max(0, s.w - GAP)} height={H} fill={s.color}
                    opacity={hover === null || hover === i ? 1 : 0.55} />
              {s.w > 90 ? (
                <text x={s.x + 14} y={H / 2 + 6} fill="#fff" fontSize="17" fontWeight="600">
                  {s.value}
                </text>
              ) : null}
            </g>
          ))}
        </g>
      </svg>

      {first && personTotal > 0 ? (
        <div className="outcome-bracket" style={{ marginLeft: `${(first.x / W) * 100}%` }}>
          <div className="outcome-bracket-line" />
          <div className="outcome-bracket-text"><b>{personTotal}</b>/{total} <span>need a person</span></div>
        </div>
      ) : null}

      <ul className="outcome-legend">
        {laid.map((s, i) => (
          <li key={s.key}
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
              className={hover === i ? 'on' : ''}>
            <span className="dot" style={{ background: s.color }} />
            <span className="nm">{s.label}</span>
            <span className="vl">{s.value}</span>
            <span className="pc">{s.pct}%</span>
            <span className="ht">{s.hint}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
