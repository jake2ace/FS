'use client';

import { useState } from 'react';

/** Composition of one batch run, direct-labelled around the ring.
 *  Values here are far apart (hundreds vs tens), which is the one case a donut
 *  reads well. Every slice carries its own count beside it - no separate legend,
 *  and nothing depends on judging an angle. Label text stays in neutral ink; a
 *  small swatch carries the identity, so colour is never the only cue. */

type Slice = { key: string; label: string; value: number; color: string };

export function RunDonut({ ok, mismatch, review, other, failed }:
  { ok: number; mismatch: number; review: number; other: number; failed: number }) {
  const [hover, setHover] = useState<string | null>(null);

  const slices: Slice[] = [
    { key: 'other',    label: 'Other categories', value: other,    color: '#8d8a83' },
    { key: 'ok',       label: 'OK',               value: ok,       color: '#1f7a4d' },
    { key: 'review',   label: 'Needs review',     value: review,   color: '#cf8b1a' },
    { key: 'mismatch', label: 'Mismatch',         value: mismatch, color: '#c23b2b' },
    { key: 'failed',   label: 'Failed',           value: failed,   color: '#5b5852' },
  ].filter((s) => s.value > 0);

  const total = slices.reduce((a, s) => a + s.value, 0) || 1;
  const W = 520, H = 266, CX = 260, CY = 138, R = 80, SW = 30, GAP = 2.5;
  const C = 2 * Math.PI * R;
  const MID = R + SW / 2;          // ring centre-line radius
  const OUT = MID + 16;            // elbow radius

  // geometry per slice
  let acc = 0;
  const laid = slices.map((s) => {
    const len = (s.value / total) * C;
    const midFrac = (acc + len / 2) / C;
    const ang = midFrac * Math.PI * 2 - Math.PI / 2;
    const right = Math.cos(ang) >= 0;
    const item = {
      ...s,
      dash: Math.max(0.5, len - GAP),
      offset: -acc,
      pct: Math.round((s.value / total) * 100),
      ang, right,
      ex: CX + Math.cos(ang) * MID,
      ey: CY + Math.sin(ang) * MID,
      lx: CX + Math.cos(ang) * OUT,
      ly: CY + Math.sin(ang) * OUT,
      ty: CY + Math.sin(ang) * OUT,
    };
    acc += len;
    return item;
  });

  // keep labels from overlapping: per side, sort by y and push apart
  const MINGAP = 38;
  (['r', 'l'] as const).forEach((side) => {
    const group = laid.filter((d) => (side === 'r' ? d.right : !d.right)).sort((a, b) => a.ty - b.ty);
    for (let i = 1; i < group.length; i++) {
      if (group[i].ty - group[i - 1].ty < MINGAP) group[i].ty = group[i - 1].ty + MINGAP;
    }
    if (group.length) {
      const over = group[group.length - 1].ty - (H - 12);
      if (over > 0) group.forEach((g) => (g.ty -= over));
      const under = 24 - group[0].ty;
      if (under > 0) group.forEach((g) => (g.ty += under));
    }
  });

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="auto" role="img"
         aria-label={`Run composition, ${total} emails`} className="rd">
      <g transform={`translate(${CX},${CY}) rotate(-90)`}>
        {laid.map((d) => (
          <circle key={d.key} r={R} fill="none" stroke={d.color} strokeWidth={SW}
            strokeDasharray={`${d.dash} ${C - d.dash}`} strokeDashoffset={d.offset}
            opacity={hover === null || hover === d.key ? 1 : 0.4}
            onMouseEnter={() => setHover(d.key)} onMouseLeave={() => setHover(null)} />
        ))}
      </g>

      <text x={CX} y={CY + 2} textAnchor="middle" fontSize="34" fontWeight="650" fill="#1f1e1d">{total}</text>
      <text x={CX} y={CY + 22} textAnchor="middle" fontSize="12" fill="#93908a">emails</text>

      {laid.map((d) => {
        const tx = d.right ? d.lx + 10 : d.lx - 10;
        const anchor = d.right ? 'start' : 'end';
        const swX = d.right ? tx : tx - 9;
        return (
          <g key={d.key} opacity={hover === null || hover === d.key ? 1 : 0.45}
             onMouseEnter={() => setHover(d.key)} onMouseLeave={() => setHover(null)}>
            <polyline fill="none" stroke="#c6c1b8" strokeWidth="1"
              points={`${d.ex},${d.ey} ${d.lx},${d.ly} ${d.right ? d.lx + 6 : d.lx - 6},${d.ty}`} />
            <rect x={swX} y={d.ty - 20} width="9" height="9" rx="2.5" fill={d.color} />
            <text x={d.right ? tx + 14 : tx - 14} y={d.ty - 12} textAnchor={anchor}
                  fontSize="12.5" fontWeight="500" fill="#1f1e1d">{d.label}</text>
            <text x={tx} y={d.ty + 5} textAnchor={anchor} fontSize="13.5" fontWeight="650" fill="#1f1e1d">
              {d.value}
              <tspan fontSize="11.5" fontWeight="400" fill="#93908a"> · {d.pct}%</tspan>
            </text>
          </g>
        );
      })}
    </svg>
  );
}
