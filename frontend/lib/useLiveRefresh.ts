'use client';

import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';

/**
 * One poller, shared by every component on the page, watching the batch run.
 *
 * Two mistakes are already baked out of this, and both are worth keeping written down.
 *
 * The first was watching the cached-result count: re-analysing a complete inbox
 * overwrites 520 results with 520 results, so the count never moves and nothing
 * refreshed. The run's own progress is the signal that actually changes.
 *
 * The second was reloading whenever that signal changed. During a run it changes on
 * almost every poll, so "reload when it changes" quietly became "reload every 1.2
 * seconds" - and the reload is the expensive part: /api/emails builds 520 rows, and the
 * backend is spending its single CPU on parsing and model calls at the same time. The
 * page was slowing down the run it was reporting on. Progress now updates at the poll
 * rate, because that is cheap and it is what makes the app look alive, while the heavy
 * page data is rate-limited - with one exception: a run starting or finishing reloads
 * immediately, so the final numbers land the moment the run ends.
 */
export interface RunPulse {
  runId: string | null;
  status: string | null;
  done: number;
  total: number;
  active: boolean;
  items: any[];
}

const IDLE: RunPulse = { runId: null, status: null, done: 0, total: 0, active: false, items: [] };

let current: RunPulse = IDLE;
let timer: ReturnType<typeof setTimeout> | null = null;
let quiet = 0;
type Listener = (p: RunPulse, statusChanged: boolean) => void;
const listeners = new Set<Listener>();

async function tick() {
  try {
    const d = await api<{ items: any[] }>('/api/runs');
    const items = d.items || [];
    const r = items[0];
    const next: RunPulse = r
      ? { runId: r.run_id, status: r.status, done: r.done ?? 0, total: r.total ?? 0,
          active: r.status === 'running', items }
      : { ...IDLE, items };
    const statusChanged = next.runId !== current.runId || next.status !== current.status;
    const moved = statusChanged || next.done !== current.done || items.length !== current.items.length;
    if (moved) {
      quiet = 0;
      current = next;
      listeners.forEach((fn) => fn(current, statusChanged));
    } else {
      quiet += 1;
    }
  } catch {
    // Each page renders its own connection error; a missed poll needs no second one.
  }
  const wait = current.active ? 1200 : quiet > 20 ? 15000 : 3000;
  if (listeners.size) timer = setTimeout(tick, wait);
  else timer = null;
}

function subscribe(fn: Listener) {
  listeners.add(fn);
  if (!timer) timer = setTimeout(tick, 300);
  return () => {
    listeners.delete(fn);
    if (!listeners.size && timer) { clearTimeout(timer); timer = null; }
  };
}

/** The live run state. Free to read - it comes from the shared poll, not a new request. */
export function useRunPulse(): RunPulse {
  const [pulse, setPulse] = useState<RunPulse>(current);
  useEffect(() => subscribe(setPulse), []);
  return pulse;
}

/**
 * Reload this page's own data as the run moves, at most once every `minGapMs` while it
 * is running, and always at the moment a run starts or finishes.
 */
export function useLiveRefresh(reload: () => void, minGapMs = 6000) {
  const fn = useRef(reload);
  fn.current = reload;
  const last = useRef(0);
  useEffect(() => subscribe((_p, statusChanged) => {
    const now = Date.now();
    if (statusChanged || now - last.current >= minGapMs) {
      last.current = now;
      fn.current();
    }
  }), [minGapMs]);
}
