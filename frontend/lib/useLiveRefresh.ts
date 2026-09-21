'use client';

import { useEffect, useRef } from 'react';
import { api } from '@/lib/api';

/**
 * Keeps a page in step with a batch run happening underneath it.
 *
 * The obvious approach - re-fetch the page's own data every couple of seconds - is the
 * wrong one here. The list endpoints build 520 rows per call, and during a run the
 * backend is already spending its single CPU on document parsing and model calls. A
 * short timer on the heavy endpoint would slow down the very run it is reporting on.
 *
 * So every page watches one cheap number instead: /api/health reports how many results
 * are cached, which is exactly what a run increments. When that number moves, the page
 * reloads once. When it stops moving, the watch eases off so an idle tab left open
 * during judging is not polling twice a second all afternoon.
 */
export function useLiveRefresh(reload: () => void) {
  const seen = useRef<number | null>(null);
  const still = useRef(0);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      try {
        const h = await api<{ results_cached: number }>('/api/health');
        if (stopped) return;
        if (seen.current === null) {
          seen.current = h.results_cached;          // first reading is the baseline
        } else if (h.results_cached !== seen.current) {
          seen.current = h.results_cached;
          still.current = 0;
          reload();
        } else {
          still.current += 1;
        }
      } catch {
        // The page shows its own connection error; a missed poll needs no second one.
      }
      if (!stopped) timer = setTimeout(tick, still.current > 30 ? 10000 : 2000);
    };

    timer = setTimeout(tick, 2000);
    return () => { stopped = true; clearTimeout(timer); };
    // reload closes over stable setState functions, so the first one stays correct.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
