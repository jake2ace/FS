"""Pydantic models shared by the pipeline, the store and the API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]
Status = Literal["OK", "MISMATCH", "NEEDS_REVIEW"]
ReviewReason = Literal["wrong_doc_type", "missing_attachment", "unreadable", "missing_value"]

CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]
FIELDS = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
]
FIELD_LABELS = {
    "shipper": "Shipper",
    "consignee": "Consignee",
    "notify_party": "Notify party",
    "port_of_loading": "Port of loading",
    "port_of_discharge": "Port of discharge",
    "container_count": "Container count",
    "gross_weight_kg": "Gross weight (kg)",
}


class ClassificationEvidence(BaseModel):
    source: Literal['body', 'subject']
    quote: str = Field(min_length=1)


class FieldValue(BaseModel):
    value: Optional[str] = None      # cleaned value (party name / port / number as text)
    evidence: Optional[str] = None   # raw source line or cell
    label: Optional[str] = None      # label as written in the document
    source: str = "rules"            # rules | ai | senior


class DocInfo(BaseModel):
    path: str
    filename: str
    format: str                      # txt | pdf | docx | xlsx | other
    role_hint: Optional[str] = None  # SI / BL guessed from the filename only
    detected_type: str = "UNKNOWN"   # SI | BL | COMMERCIAL_INVOICE | PACKING_LIST | CERTIFICATE_OF_ORIGIN | UNKNOWN
    readable: bool = True
    read_error: Optional[str] = None
    size_bytes: int = 0
    recovery: str = "not_needed"
    recovery_confidence: float = 1.0
    text_chars: int = 0
    text_preview: str = ""
    fields: dict[str, FieldValue] = Field(default_factory=dict)
    extraction_method: str = "none"  # rules | ai | ai+rules | +senior | none


class FieldRow(BaseModel):
    field: str
    label: str
    si_value: Optional[str] = None
    bl_value: Optional[str] = None
    match: Optional[bool] = None     # None when the comparison could not be made
    reason: str = ""
    si_evidence: Optional[str] = None
    bl_evidence: Optional[str] = None


class Decision(BaseModel):
    action: Literal["confirm", "escalate", "resolve", "reopen", "approve_revision", "reject_revision"]
    note: Optional[str] = None
    by: str = "operator"
    at: str


class SeniorReview(BaseModel):
    """Second opinion of the senior (tier-2) model. Only suspicious cases are escalated to it."""
    model: str
    available: bool = True                                   # False when the senior model could not be reached
    triggers: list[str] = Field(default_factory=list)        # why the case was escalated
    category: Optional[str] = None                           # category the senior model would assign
    category_confidence: float = 0.0
    outcome: Optional[str] = None                            # OK | MISMATCH | NEEDS_REVIEW - the senior model's own opinion
    agrees: Optional[bool] = None                            # outcome == deterministic status
    overrides: list[str] = Field(default_factory=list)       # evidence-backed corrections / equivalences that were applied
    rejected: list[str] = Field(default_factory=list)        # suggestions rejected because the documents do not support them
    equivalent_fields: list[str] = Field(default_factory=list)
    assessment: str = ""
    confidence: float = 0.0


class CaseResult(BaseModel):
    pipeline_version: int = 0
    decision_method: str = "legacy"
    ai_model: Optional[str] = None
    email_id: str
    subject: str
    sender: str
    attachments: list[str] = Field(default_factory=list)

    category: Optional[Category] = None  # Unknown until a person classifies a failed AI request.
    category_confidence: float
    category_reason: str = ""
    category_evidence: list[ClassificationEvidence] = Field(default_factory=list)
    category_prompt_version: Optional[str] = None
    category_method: str = "rules"   # rules | ai | ai+rules
    intent: str = "other"            # verify_documents | request_draft | other

    status: Status                   # submission-level outcome
    review_reason: Optional[ReviewReason] = None
    review_detail: Optional[str] = None
    has_defect: bool = False
    defect_fields: list[str] = Field(default_factory=list)

    ui_status: str = "No action"     # Safe to complete | High risk | Needs review | Awaiting draft BL | No action
    risk: str = "none"               # high | medium | low | none
    headline: str = ""
    explanation: str = ""
    suggested_action: str = ""
    confidence: float = 0.0
    evidence_available: bool = False
    automation: str = "none"         # auto_completed | review_required | none

    fields: list[FieldRow] = Field(default_factory=list)
    docs: list[DocInfo] = Field(default_factory=list)
    ai_used: bool = False
    senior_review: Optional[SeniorReview] = None
    warnings: list[str] = Field(default_factory=list)
    unconfirmed_ai_assessment: Optional[str] = None
    manual_review: Optional[dict] = None
    decision_chain: list[dict] = Field(default_factory=list)
    analysed_at: str
    duration_ms: int = 0

    decision: Optional[Decision] = None
    resolved: bool = False
    processing_status: str = "NO_ACTION"
    working_report: Optional[dict] = None
    history: list[dict] = Field(default_factory=list)


class ManualReviewInput(BaseModel):
    category: Category
    status: Status
    defect_fields: list[str] = Field(default_factory=list)
    note: str = Field(min_length=1, max_length=2000)
    by: str = Field(default='operator', min_length=1, max_length=100)
    complete: bool = True


class SubmissionEntry(BaseModel):
    category: Category
    status: Status
    review_reason: Optional[ReviewReason] = None
    defect_fields: list[str] = Field(default_factory=list)
    has_defect: bool = False


class RunState(BaseModel):
    run_id: str
    status: str = "running"          # running | completed | cancelled | failed
    started_at: str
    finished_at: Optional[str] = None
    total: int = 0
    done: int = 0
    ok: int = 0
    mismatch: int = 0
    needs_review: int = 0
    not_applicable: int = 0
    failed: list[dict] = Field(default_factory=list)   # [{email_id, error}]
    current: Optional[str] = None
    force: bool = False
