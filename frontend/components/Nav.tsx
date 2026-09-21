'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { api, post } from '@/lib/api';
import { useLanguage } from '@/components/LanguageProvider';
import { useRunPulse, useLiveRefresh } from '@/lib/useLiveRefresh';

const LINKS = [
  { href: '/', label: 'Today' },
  { href: '/inbox', label: 'Smart Inbox' },
  { href: '/review', label: 'Review Queue' },
  { href: '/runs', label: 'Batch Run' },
];

export default function Nav() {
  const pathname = usePathname() || '/';
  const { locale, setLocale } = useLanguage();
  const [languageOpen, setLanguageOpen] = useState(false);
  const [health, setHealth] = useState<any>(null);
  const pulse = useRunPulse();
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
    // These counters only change because a run changed them, so the run itself is the
    // trigger. The slow timer is a backstop for a policy change made in another tab.
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, []);
  useLiveRefresh(load);

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
              {/* During a re-run the cached count stays at its total the whole time, so the
                  chip has to show the run's progress or it reads as a frozen app. */}
              <span className="chip chip-dark">
                {pulse.active && pulse.total
                  ? `${pulse.done}/${pulse.total} analysing…`
                  : `${health.results_cached}/${health.emails} analysed`}
              </span>
            </>
          ) : (
            <span className="chip chip-dark">connecting…</span>
          )}
          <div className="language-menu" data-no-translate>
            <button
              type="button"
              className="language-trigger"
              aria-haspopup="menu"
              aria-expanded={languageOpen}
              onClick={() => setLanguageOpen((open) => !open)}
            >
              <span aria-hidden="true">🌐</span>
              {locale === 'zh' ? '中文' : 'English'}
              <span className="language-chevron" aria-hidden="true">▾</span>
            </button>
            {languageOpen ? (
              <div className="language-options" role="menu" aria-label="Language / 语言">
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={locale === 'en'}
                  className={locale === 'en' ? 'selected' : ''}
                  onClick={() => { setLocale('en'); setLanguageOpen(false); }}
                >
                  <span>English</span><span aria-hidden="true">{locale === 'en' ? '✓' : ''}</span>
                </button>
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={locale === 'zh'}
                  className={locale === 'zh' ? 'selected' : ''}
                  onClick={() => { setLocale('zh'); setLanguageOpen(false); }}
                >
                  <span>中文</span><span aria-hidden="true">{locale === 'zh' ? '✓' : ''}</span>
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </header>
  );
}
