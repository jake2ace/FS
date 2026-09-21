// Small fetch helper + shared types for the FreightSentinel API.
// All calls go to same-origin /api/* which next.config.mjs proxies to the backend.

export type Category = 'BL_COMPARISON' | 'SI_REQUEST' | 'INVOICE_QUERY' | 'GENERAL' | 'SPAM';
export type Status = 'OK' | 'MISMATCH' | 'NEEDS_REVIEW';

export interface FieldRow {
  field: string;
  label: string;
  si_value: string | null;
  bl_value: string | null;
  match: boolean | null;
  reason: string;
  si_evidence: string | null;
  bl_evidence: string | null;
}

export interface DocInfo {
  path: string;
  filename: string;
  format: string;
  role_hint: string | null;
  detected_type: string;
  readable: boolean;
  read_error: string | null;
  size_bytes: number;
  recovery: string;
  recovery_confidence: number;
  text_chars: number;
  text_preview: string;
  fields: Record<string, { value: string | null; evidence: string | null; label: string | null; source: string }>;
  extraction_method: string;
}

export interface Decision {
  action: 'confirm' | 'escalate' | 'resolve' | 'reopen' | 'approve_revision' | 'reject_revision';
  note: string | null;
  by: string;
  at: string;
}

export interface SeniorReview {
  model: string;
  available: boolean;
  triggers: string[];
  category: string | null;
  category_confidence: number;
  outcome: string | null;
  agrees: boolean | null;
  overrides: string[];
  rejected: string[];
  equivalent_fields: string[];
  assessment: string;
  confidence: number;
}

export interface CaseResult {
  decision_method: string;
  ai_model: string | null;
  email_id: string;
  subject: string;
  sender: string;
  attachments: string[];
  category: Category | null;
  category_confidence: number;
  category_reason: string;
  category_method: string;
  intent: string;
  status: Status;
  review_reason: string | null;
  review_detail: string | null;
  has_defect: boolean;
  defect_fields: string[];
  ui_status: string;
  risk: 'high' | 'medium' | 'low' | 'none';
  headline: string;
  explanation: string;
  suggested_action: string;
  confidence: number;
  evidence_available: boolean;
  automation: 'auto_completed' | 'review_required' | 'none';
  fields: FieldRow[];
  docs: DocInfo[];
  ai_used: boolean;
  senior_review: SeniorReview | null;
  manual_review?: { category: Category; status: Status; note: string; by: string; complete: boolean; at: string } | null;
  decision_chain?: { tier: string; thinking?: boolean; reasoning_effort?: string; provider?: string; model?: string; status?: string; reason?: string; available?: boolean; unconfirmed_assessment?: string }[];
  unconfirmed_ai_assessment?: string | null;
  warnings: string[];
  analysed_at: string;
  duration_ms: number;
  decision: Decision | null;
  resolved: boolean;
  processing_status: string;
  working_report: any | null;
  history: any[];
}

export interface EmailRow {
  email_id: string;
  subject: string;
  from: string;
  attachment_count: number;
  attachments: string[];
  body_preview: string;
  analysed: boolean;
  category?: Category | null;
  category_confidence?: number;
  status?: Status;
  ui_status?: string;
  risk?: string;
  review_reason?: string | null;
  defect_fields?: string[];
  headline?: string;
  confidence?: number;
  automation?: string;
  resolved?: boolean;
  processing_status?: string;
  decision?: Decision | null;
  analysed_at?: string;
  ai_used?: boolean;
}

export interface RunState {
  run_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  total: number;
  done: number;
  ok: number;
  mismatch: number;
  needs_review: number;
  not_applicable: number;
  failed: { email_id: string; error: string }[];
  current: string | null;
  force: boolean;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    cache: 'no-store',
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ? (typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)) : detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export const post = <T = any>(path: string, body?: any) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });

export const CATEGORY_LABEL: Record<string, string> = {
  BL_COMPARISON: 'BL comparison',
  SI_REQUEST: 'SI request',
  INVOICE_QUERY: 'Invoice query',
  GENERAL: 'General',
  SPAM: 'Spam',
};

export const REVIEW_LABEL: Record<string, string> = {
  missing_attachment: 'Missing attachment',
  wrong_doc_type: 'Wrong document type',
  unreadable: 'Unreadable document',
  missing_value: 'Missing value',
};

export function pct(x?: number | null): string {
  if (x === undefined || x === null || Number.isNaN(x)) return '–';
  return `${Math.round(x * 100)}%`;
}

export function fmtTime(iso?: string | null): string {
  if (!iso) return '–';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
