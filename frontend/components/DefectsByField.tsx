'use client';

import { useLanguage } from '@/components/LanguageProvider';

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
 *
 * The sentences carry numbers inside them, so they are written out per language here
 * rather than left to the page-wide dictionary: that translates whole text nodes, and
 * a sentence built around interpolated counts would come out of it in English word
 * order with Chinese words in it.
 */

const GROUPS: { key: string; en: string; zh: string; fields: [string, string, string][] }[] = [
  { key: 'cargo', en: 'Cargo figures', zh: '货量数字',
    fields: [['container_count', 'container count', '集装箱数量'], ['gross_weight_kg', 'gross weight', '毛重']] },
  { key: 'party', en: 'Parties', zh: '相关方',
    fields: [['shipper', 'shipper', '托运人'], ['consignee', 'consignee', '收货人'],
             ['notify_party', 'notify party', '通知方']] },
  { key: 'route', en: 'Route', zh: '航线',
    fields: [['port_of_loading', 'port of loading', '装货港'],
             ['port_of_discharge', 'port of discharge', '卸货港']] },
];

export function DefectsByField(
  { counts, cases, multi }: { counts: Record<string, number>; cases: number; multi: number },
) {
  const { locale } = useLanguage();
  const zh = locale === 'zh';

  const groups = GROUPS.map((g) => {
    const parts = g.fields.map(([key, en, cn]) => ({ label: zh ? cn : en, n: counts?.[key] || 0 }))
      .sort((a, b) => b.n - a.n);
    return { ...g, name: zh ? g.zh : g.en, parts, n: parts.reduce((t, p) => t + p.n, 0) };
  }).sort((a, b) => b.n - a.n);

  const total = groups.reduce((t, g) => t + g.n, 0);
  const top = groups[0];
  const topField = groups.flatMap((g) => g.parts).sort((a, b) => b.n - a.n)[0];
  const share = (n: number) => (total ? Math.round((n / total) * 100) : 0);

  return (
    <div className="card">
      <div className="card-head">
        <h2>{zh ? '差异出现在哪里' : 'Where differences turn up'}</h2>
        <span className="small muted">
          {zh ? `${cases} 份草稿，共 ${total} 处差异` : `${total} across ${cases} drafts`}
        </span>
      </div>

      {total === 0 ? (
        <p className="small muted" style={{ marginTop: 8 }}>
          {zh ? '还没有发现差异 —— 先跑一轮收件箱。' : 'No differences found yet - run the inbox first.'}
        </p>
      ) : (
        <>
          <ul className="finding">
            {multi > 0 && (
              <li>
                <b>{zh
                  ? (multi > cases / 2 ? '大多数坏草稿不止错一处' : '不少坏草稿不止错一处')
                  : `${multi > cases / 2 ? 'Most' : 'Many'} bad drafts are wrong in more than one place`}</b>
                {zh
                  ? ` —— ${cases} 份里有 ${multi} 份差两个或更多字段；只改对方告诉你的那一处，草稿仍然不合格。`
                  : ` - ${multi} of ${cases} differ on two or more fields, so correcting only the difference you were told about will not clear the draft.`}
              </li>
            )}
            <li>
              <b>{zh ? `${top.name}是最薄弱的一块` : `${top.name} are the weak spot`}</b>
              {zh
                ? ` —— 占全部差异的 ${share(top.n)}%，其中${topField.label}最多，${topField.n} 处。`
                : ` - ${share(top.n)}% of all differences, led by ${topField.label} at ${topField.n}.`}
            </li>
          </ul>

          <ul className="dbf">
            {groups.map((g) => (
              <li key={g.key}>
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
            {zh
              ? '一份草稿可能同时差多个字段，所以这里的合计会大于草稿数。'
              : 'One draft can differ on more than one field, so the totals here exceed the number of drafts.'}
          </p>
        </>
      )}
    </div>
  );
}
