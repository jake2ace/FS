'use client';

import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';

/**
 * One poller, shared by every component on the page, watching the batch run.
 *
 * The first version of this watched the cached-result count on /api/health, which was
 * wrong in a way that only shows up on a second run: re-analysing an inbox that is
 * already complete overwrites 520 results with 520 results. The count never moves, so
 * nothing refreshed and the header sat at "520/520 analysed" for the whole run. The run's
 * own progress is the signal that actually changes, so that is what this watches now.
 *
 * Pages still do not poll their own endpoints on a timer. Each list call builds 520 rows
 * and the backend is spending its single CPU on parsing and model calls during a run, so
 * a short timer on the heavy endpoints would slow the run it is reporting on. They reload
 * once, when the run has actually moved.
 */
export interface RunPulse {
  runId: string | null;
  status: string | null;
  done: number;
  total: number;
  active: boolean;
}

const IDLE: RunPulse = { runId: null, status: null, done: 0, total: 0, active: false };

let current: RunPulse = IDLE;
let timer: ReturnType<typeof setTimeout> | null = null;
let quiet = 0;
const listeners = new Set<(p: RunPulse) => void>();

async function tick() {
  try {
    const d = await api<{ items: any[] }>('/api/runs');
    const r = (d.items || [])[0];
    const next: RunPulse = r
      ? { runId: r.run_id, status: r.status, done: r.done ?? 0, total: r.total ?? 0, active: r.status === 'running' }
      : IDLE;
    const changed =
      next.runId !== current.runId || next.done !== current.done || next.status !== current.status;
    if (changed) {
      quiet = 0;
      current = next;
      listeners.forEach((fn) => fn(current));
    } else {
      quiet += 1;
    }
  } catch {
    // Each page renders its own connection error; a missed poll needs no second one.
  }
  // Close attention while a run is moving, then ease off so a tab left open during
  // judging is not polling every two seconds all afternoon.
  const wait = current.active ? 1200 : quiet > 20 ? 15000 : 3000;
  if (listeners.size) timer = setTimeout(tick, wait);
  else timer = null;
}

function subscribe(fn: (p: RunPulse) => void) {
  listeners.add(fn);
  if (!timer) timer = setTimeout(tick, 300);
  return () => {
    listeners.delete(fn);
    if (!listeners.size && timer) { clearTimeout(timer); timer = null; }
  };
}

/** The live run state, for anything that wants to display it. */
export function useRunPulse(): RunPulse {
  const [pulse, setPulse] = useState<RunPulse>(current);
  useEffect(() => subscribe(setPulse), []);
  return pulse;
}

/** Reload this page's own data whenever the run moves. */
export function useLiveRefresh(reload: () => void) {
  const fn = useRef(reload);
  fn.current = reload;
  useEffect(() => subscribe(() => fn.current()), []);
}
