'use client';

import { createContext, useContext, useEffect, useRef, useState } from 'react';

export type Locale = 'en' | 'zh';

const LanguageContext = createContext<{
  locale: Locale;
  setLocale: (locale: Locale) => void;
}>({ locale: 'en', setLocale: () => undefined });

const ZH: Record<string, string> = {
  'Shipping Document Verification': '航运单据核验',
  'backend offline': '后端离线',
  'connecting…': '连接中…',
  'AI is unavailable; analysis requires a working provider': 'AI 不可用；分析需要有效的 AI 服务',
  unavailable: '不可用',
  'Policy:': '策略：',
  'Click to switch the automation policy': '点击切换自动化策略',
  analysed: '已分析',
  of: '／',
  'analysed emails': '封已分析邮件',
  'mismatch between SI and draft BL': 'SI 与草稿 BL 不一致',
  'missing / unreadable / blank': '缺失／无法读取／空值',
  'auto-completed under': '按照',
  policy: '策略自动完成',
  'rechecked revisions awaiting a person': '复查后的更正内容等待人工批准',
  'emails in the inbox': '封收件箱邮件',
  Today: '今日工作台',
  'Smart Inbox': '智能收件箱',
  'Review Queue': '复核队列',
  'Batch Run': '批量运行',
  'Today Work Centre': '今日工作中心',
  'What needs attention in the shared inbox right now.': '查看共享收件箱中当前需要处理的事项。',
  'Open Smart Inbox': '打开智能收件箱',
  'Analyse the full inbox': '分析全部邮件',
  'Analyse remaining emails': '分析剩余邮件',
  'Batch run in progress…': '正在批量运行…',
  'Comparison requests': '核对请求',
  'High risk': '高风险',
  'Needs review': '需要复核',
  'Safe completed': '安全完成',
  'Pending approval': '等待批准',
  'Not analysed': '尚未分析',
  'Risk Radar - priority cases': '风险雷达——优先案件',
  'Open the full review queue →': '打开完整复核队列 →',
  'Nothing analysed yet. Start with the Smart Inbox or run the full inbox.': '尚未分析任何邮件。请从智能收件箱开始，或运行完整收件箱分析。',
  'No open risk cases. Everything is either safe or already handled.': '没有待处理的风险案件。所有项目均已安全完成或处理。',
  Email: '邮件',
  Finding: '发现',
  Risk: '风险',
  Status: '状态',
  Open: '打开',
  'Automation policy': '自动化策略',
  Strict: '严格',
  Standard: '标准',
  strict: '严格',
  standard: '标准',
  'AI decides; source evidence checked': '由 AI 判断，并校验来源证据',
  'AI decides all seven comparisons. Uncertainty is reviewed once by the configured senior AI, then handed to a person if unresolved. Human handling is final. Strict policy asks AI to refer uncertain equivalences for review.': 'AI 负责全部七项比对。不确定结果会由配置的复核 AI 再检查一次；若仍无法确定，则转交人工。人工处理是最终结论。严格策略会要求 AI 将不确定的等价关系提交复核。',
  'Switch the policy from the top bar. Mismatches and uncertain cases are never auto-completed.': '可在顶栏切换策略。不一致或不确定的案件绝不会自动完成。',
  'Last batch run': '最近一次批量运行',
  Progress: '进度',
  Outcome: '结果',
  Failed: '失败',
  Started: '开始时间',
  'No batch run yet.': '尚未进行批量运行。',
  'Batch run & submission →': '批量运行与提交 →',
  'AI status': 'AI 状态',
  'AI is unavailable. Configure the provider before analysis; no rule-based fallback is used.': 'AI 当前不可用。请先配置供应商；系统不会使用规则结果冒充 AI 分析。',
  'The official shared inbox - {count} emails. Comparison requests are the ones that continue to the checking step.': '官方共享收件箱——共 {count} 封邮件。只有核对请求会进入文件检查步骤。',
  'The official shared inbox -': '官方共享收件箱——共',
  'emails. Comparison requests are the ones that continue to the checking step.': '封邮件。只有核对请求会进入文件检查步骤。',
  'Search subject, sender or id…': '搜索主题、发件人或编号…',
  'All categories': '全部类别',
  'BL comparison': 'BL 核对',
  'SI request': 'SI 请求',
  'Invoice query': '发票查询',
  General: '普通邮件',
  Spam: '垃圾邮件',
  'All statuses': '全部状态',
  'Safe to complete': '可以安全完成',
  'No action': '无需操作',
  'with attachments': '有附件',
  'not analysed': '尚未分析',
  Subject: '主题',
  From: '发件人',
  'Att.': '附件',
  Category: '类别',
  'Conf.': '置信度',
  Analyse: '分析',
  'Re-analyse': '重新分析',
  'Analysing…': '正在分析…',
  'No emails match the current filters.': '没有符合当前筛选条件的邮件。',
  'shown · page': '项 · 第',
  'Every mismatch and every case the system could not decide on its own. A person confirms, escalates or resolves - nothing is released automatically.': '这里包含所有不一致和系统无法自行判断的案件。由人工确认、升级或解决，不会自动放行。',
  Resolved: '已解决',
  'Auto-completed': '自动完成',
  'No results yet - analyse emails from the Smart Inbox or run the full inbox.': '尚无结果——请在智能收件箱中分析邮件，或运行完整收件箱分析。',
  'Open (': '待处理（',
  'Resolved (': '已解决（',
  'Auto-completed (': '自动完成（',
  ')': '）',
  'Nothing here.': '这里没有内容。',
  'Fields / reason': '字段／原因',
  'Needs classification': '需要分类',
  'decision:': '决定：',
  Escalate: '升级处理',
  Reopen: '重新打开',
  'Process the complete inbox, watch progress, retry failures and export the submission JSON.': '处理完整收件箱、查看进度、重试失败项并导出提交 JSON。',
  're-analyse already analysed emails': '重新分析已处理的邮件',
  'Running…': '运行中…',
  'Run full inbox': '运行完整收件箱',
  'No run yet': '尚未运行',
  Mismatch: '不一致',
  'Other categories': '其他类别',
  Finished: '完成时间',
  'Cancel run': '取消运行',
  'Failed items': '失败项目',
  Error: '错误',
  Retry: '重试',
  'Start a run to process all emails. Already analysed emails are skipped unless you tick re-analyse.': '启动运行以处理全部邮件。除非勾选重新分析，否则已分析的邮件会被跳过。',
  'Submission JSON': '提交 JSON',
  'emails analysed': '封邮件已分析',
  'still need analysis before export.': '封邮件仍需分析才能导出。',
  'Download submission.json': '下载 submission.json',
  'Analyse all emails to enable export': '分析全部邮件后才能导出',
  'Shape follows sample_submission.json exactly (category, status, review_reason, defect_fields, has_defect for every email_id).': '输出格式与 sample_submission.json 完全一致（每个 email_id 均含 category、status、review_reason、defect_fields 和 has_defect）。',
  'Previous runs': '历史运行',
  'None.': '无。',
  'Results live in the backend cache;': '结果保存在后端缓存中；',
  'open the review queue': '批量运行结束后打开复核队列',
  'once the run finishes.': '。',
  Run: '运行',
  Done: '完成',
  Review: '复核',
  None: '无',
  'This email has not been analysed yet. Click Analyse this email to classify it and, for comparison requests, check the SI against the draft BL.': '这封邮件尚未分析。点击“分析这封邮件”进行分类；若为核对请求，系统会比较 SI 与草稿 BL。',
  'This email has not been analysed yet. Click': '这封邮件尚未分析。点击“',
  'to classify it and, for comparison requests, check the SI against the draft BL.': '”进行分类；若为核对请求，系统会比较 SI 与草稿 BL。',
  attachment: '个附件',
  s: '',
  'Analyse this email': '分析这封邮件',
  'Working…': '处理中…',
  'Human conclusion': '人工结论',
  'Original attachment check': '原始附件检查',
  confidence: '置信度',
  evidence: '证据',
  available: '可用',
  incomplete: '不完整',
  'Human decision': '人工决定',
  'AI decision': 'AI 决定',
  'AI response needs review': 'AI 结果需要复核',
  resolved: '已解决',
  'Suggested action:': '建议操作：',
  'Review reason': '复核原因',
  'Seven-field comparison (SI is the reference)': '七字段核对（以 SI 为准）',
  'show source lines': '显示来源文本',
  'Processing steps': '处理步骤',
  'Primary AI': '初审 AI',
  'Senior AI': '复核 AI',
  'Human handling': '人工处理',
  'Not configured / unavailable; handed to a person': '未配置或不可用，已转交人工',
  'Unconfirmed AI observation:': '未经确认的 AI 观察：',
  'Source evidence': '来源证据',
  'Email body': '邮件正文',
  readable: '可读取',
  unreadable: '无法读取',
  'Correction email draft': '更正邮件草稿',
  'Generate draft': '生成草稿',
  'Copy to clipboard': '复制到剪贴板',
  Discard: '丢弃',
  'Sending stays a human step in your mail client.': '发送仍需由人工在邮件客户端中完成。',
  'No field comparison available for this case.': '该案件没有可用的字段核对结果。',
  Field: '字段',
  'SI (reference)': 'SI（基准）',
  'Draft BL': '草稿 BL',
  Match: '匹配',
  Reason: '原因',
  '— missing —': '— 缺失 —',
  Shipper: '托运人',
  Consignee: '收货人',
  'Notify party': '通知方',
  'Port of loading': '装货港',
  'Port of discharge': '卸货港',
  'Container count': '集装箱数量',
  'Gross weight (kg)': '毛重（千克）',
  'Human review & corrected BL': '人工复核与更正 BL',
  'No further action': '无需进一步操作',
  'Human review required': '需要人工复核',
  'Pending human approval': '等待人工批准',
  'Resolved by a person': '已由人工解决',
  'Human review': '人工复核',
  'Generate corrected BL copy': '生成更正版 BL 副本',
  'Uses the verified SI values. Keeps the original file format where fields can be safely located; otherwise explains why manual editing is needed.': '使用经核验的 SI 值。在能够安全定位字段时保留原文件格式，否则会说明需要人工编辑的原因。',
  'Working report': '工作报告',
  '(missing)': '（缺失）',
  'SI evidence:': 'SI 证据：',
  'Seven-field recheck and source evidence': '七字段复查及来源证据',
  'No readable source text': '没有可读取的来源文本',
  Download: '下载',
  'Review note / reason for a correction': '复核备注／更正原因',
  'Optional AI assistance: recheck extracted readings': '可选 AI 辅助：复查提取结果',
  'Optional AI assistance: recheck replacement attachments': '可选 AI 辅助：复查替换附件',
  'SI reading': 'SI 读数',
  'BL reading': 'BL 读数',
  'Recheck confirmed readings': '复查已确认读数',
  'Recheck supplied documents': '复查所提供的文件',
  'Confirm completed check': '确认核对完成',
  'Keep in human review': '保留在人工复核中',
  'Final human handling': '最终人工处理',
  'Confirmed email category': '确认的邮件类别',
  'Choose a category': '选择类别',
  'Confirmed outcome': '确认的结果',
  'Still needs human handling': '仍需人工处理',
  'Original documents confirmed consistent': '确认原始文件一致',
  'Category confirmed; no BL comparison required': '类别已确认，无需核对 BL',
  'Confirmed differences; handled by a person': '确认存在差异，已由人工处理',
  'Confirmed differing fields': '确认存在差异的字段',
  'Save human progress': '保存人工处理进度',
  'Complete human handling': '完成人工处理',
  'Reopen for review': '重新打开以复核',
  'Review history': '复核历史',
  'Download retained copy': '下载保留的副本',
  'Missing attachment': '缺少附件',
  'Wrong document type': '文件类型错误',
  'Unreadable document': '文件无法读取',
  'Missing value': '缺少值',
  none: '无',
  low: '低',
  medium: '中',
  high: '高',
  'Awaiting draft BL': '等待草稿 BL',
  'Human completed': '人工已完成',
};

function translateExact(value: string): string {
  return Object.prototype.hasOwnProperty.call(ZH, value) ? ZH[value] : value;
}

function translateText(value: string): string {
  const leading = value.match(/^\s*/)?.[0] || '';
  const trailing = value.match(/\s*$/)?.[0] || '';
  const text = value.trim();
  if (!text) return value;
  if (Object.prototype.hasOwnProperty.call(ZH, text)) return `${leading}${ZH[text]}${trailing}`;

  let match = text.match(/^The official shared inbox - (\d+) emails\. Comparison requests are the ones that continue to the checking step\.$/);
  if (match) return `${leading}${ZH['The official shared inbox - {count} emails. Comparison requests are the ones that continue to the checking step.'].replace('{count}', match[1])}${trailing}`;
  match = text.match(/^(\d+) shown · page (\d+)\/(\d+)$/);
  if (match) return `${leading}显示 ${match[1]} 项 · 第 ${match[2]}/${match[3]} 页${trailing}`;
  match = text.match(/^Open \((\d+)\)$/);
  if (match) return `${leading}待处理（${match[1]}）${trailing}`;
  match = text.match(/^Resolved \((\d+)\)$/);
  if (match) return `${leading}已解决（${match[1]}）${trailing}`;
  match = text.match(/^Auto-completed \((\d+)\)$/);
  if (match) return `${leading}自动完成（${match[1]}）${trailing}`;
  match = text.match(/^Run (.+)$/);
  if (match) return `${leading}运行 ${match[1]}${trailing}`;
  match = text.match(/^From (.+) · (\d+) attachments?$/);
  if (match) return `${leading}发件人 ${match[1]} · ${match[2]} 个附件${trailing}`;
  match = text.match(/^Current outcome: (.+)\. The original SI and BL remain unchanged\. Corrected copies need your approval\.$/);
  if (match) return `${leading}当前结果：${match[1]}。原始 SI 和 BL 保持不变，更正副本需要你的批准。${trailing}`;
  match = text.match(/^Backend not reachable:\s*(.+)$/);
  if (match) return `${leading}无法连接后端：${match[1]}${trailing}`;
  match = text.match(/^Review history \((\d+)\)$/);
  if (match) return `${leading}复核历史（${match[1]}）${trailing}`;
  match = text.match(/^- (\d+) still need analysis before export\.$/);
  if (match) return `${leading}— 还有 ${match[1]} 封邮件需要分析后才能导出。${trailing}`;
  if (text === '- ready for self-evaluation.') return `${leading}— 已可以进行自评。${trailing}`;
  return value;
}

const originalText = new WeakMap<Text, string>();
const lastAppliedText = new WeakMap<Text, string>();
const originalAttributes = new WeakMap<Element, Map<string, string>>();
const lastAppliedAttributes = new WeakMap<Element, Map<string, string>>();
const ATTRIBUTES = ['placeholder', 'title', 'aria-label'];

function shouldSkip(node: Node): boolean {
  const element = node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement;
  return !!element?.closest('pre, code, textarea, .evidence, [data-no-translate]');
}

function localizeTextNode(node: Text, locale: Locale) {
  if (shouldSkip(node)) return;
  const current = node.data;
  const previousApplied = lastAppliedText.get(node);
  let original = originalText.get(node);
  if (original === undefined || (previousApplied !== undefined && current !== previousApplied && current !== original)) {
    original = current;
    originalText.set(node, original);
  }
  const next = locale === 'zh' ? translateText(original) : original;
  if (current !== next) node.data = next;
  lastAppliedText.set(node, next);
}

function localizeElement(element: Element, locale: Locale) {
  if (shouldSkip(element)) return;
  let originals = originalAttributes.get(element);
  let applied = lastAppliedAttributes.get(element);
  if (!originals) {
    originals = new Map();
    originalAttributes.set(element, originals);
  }
  if (!applied) {
    applied = new Map();
    lastAppliedAttributes.set(element, applied);
  }
  for (const attr of ATTRIBUTES) {
    const current = element.getAttribute(attr);
    if (current === null) continue;
    const previousApplied = applied.get(attr);
    let original = originals.get(attr);
    if (original === undefined || (previousApplied !== undefined && current !== previousApplied && current !== original)) {
      original = current;
      originals.set(attr, original);
    }
    const next = locale === 'zh' ? translateExact(original) : original;
    if (current !== next) element.setAttribute(attr, next);
    applied.set(attr, next);
  }
}

function localizeTree(root: Node, locale: Locale) {
  if (root.nodeType === Node.TEXT_NODE) {
    localizeTextNode(root as Text, locale);
    return;
  }
  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
  if (root.nodeType === Node.ELEMENT_NODE) localizeElement(root as Element, locale);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  let node: Node | null = walker.nextNode();
  while (node) {
    if (node.nodeType === Node.TEXT_NODE) localizeTextNode(node as Text, locale);
    else localizeElement(node as Element, locale);
    node = walker.nextNode();
  }
}

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>('en');
  const localeRef = useRef<Locale>('en');

  useEffect(() => {
    const stored = window.localStorage.getItem('freightsentinel-locale');
    if (stored === 'zh' || stored === 'en') setLocaleState(stored);
  }, []);

  useEffect(() => {
    localeRef.current = locale;
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
    localizeTree(document.body, locale);
    let applying = false;
    const observer = new MutationObserver((mutations) => {
      if (applying) return;
      applying = true;
      try {
        for (const mutation of mutations) {
          if (mutation.type === 'characterData') localizeTextNode(mutation.target as Text, localeRef.current);
          for (const node of Array.from(mutation.addedNodes)) localizeTree(node, localeRef.current);
          if (mutation.type === 'attributes') localizeElement(mutation.target as Element, localeRef.current);
        }
      } finally {
        applying = false;
      }
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRIBUTES });
    return () => observer.disconnect();
  }, [locale]);

  const setLocale = (next: Locale) => {
    window.localStorage.setItem('freightsentinel-locale', next);
    setLocaleState(next);
  };

  return <LanguageContext.Provider value={{ locale, setLocale }}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  return useContext(LanguageContext);
}
