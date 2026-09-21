'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api, post } from '@/lib/api';

const LINKS = [
  { href: '/', label: 'Today' },
  { href: '/inbox', label: 'Smart Inbox' },
  { href: '/review', label: 'Review Queue' },
  { href: '/runs', label: 'Batch Run' },
];

export default function Nav() {
  const pathname = usePathname() || '/';
  const [health, setHealth] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api('/api/health')
      .then((h) => {
        setHealth(h);
        setError(null);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  const togglePolicy = async () => {
    if (!health) return;
    const next = health.policy === 'strict' ? 'standard' : 'strict';
    try {
      await post('/api/settings/policy', { policy: next });
      load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const aiOn = !!health?.ai?.enabled;
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link href="/" className="brand">
          FreightSentinel
          <small>Shipping Document Verification</small>
        </Link>
        <nav className="nav">
          {LINKS.map((l) => {
            const active = l.href === '/' ? pathname === '/' : pathname.startsWith(l.href);
            return (
              <Link key={l.href} href={l.href} className={active ? 'active' : ''}>
                {l.label}
              </Link>
            );
          })}
        </nav>
        <div className="topbar-right">
          {error ? (
            <span className="chip chip-dark" title={error}>
              <span className="chip-dot off" /> backend offline
            </span>
          ) : health ? (
            <>
              <span
                className="chip chip-dark"
                title={
                  aiOn
                    ? `${health.ai.provider} / ${health.ai.model}` +
                      (health.ai.fallback_model ? ` (fallback ${health.ai.fallback_model})` : '') +
                      (health.ai_senior?.enabled ? ` · senior review: ${health.ai_senior.model}` : ' · senior review off')
                    : 'AI is unavailable; analysis requires a working provider'
                }
              >
                <span className={`chip-dot ${aiOn ? '' : 'off'}`} /> AI {aiOn ? health.ai.provider : 'unavailable'}
                {aiOn && health.ai_senior?.enabled ? ' + senior' : ''}
              </span>
              <button className="chip chip-dark" onClick={togglePolicy} title="Click to switch the automation policy" style={{ cursor: 'pointer' }}>
                Policy: {health.policy === 'strict' ? 'Strict' : 'Standard'}
              </button>
              <span className="chip chip-dark">{health.results_cached}/{health.emails} analysed</span>
            </>
          ) : (
            <span className="chip chip-dark">connecting…</span>
          )}
        </div>
      </div>
    </header>
  );
}
