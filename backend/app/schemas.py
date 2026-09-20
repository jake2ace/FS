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


class FieldValue(BaseModel):
    value: Optional[str] = None      # cleaned value (party name / port / number as text)
    evidence: Optional[str] = None   # raw source line or cell
    label: Optional[str] = None      # label as written in the document
    source: str = "rules"            # rules | ai


class DocInfo(BaseModel):
    path: str
    filename: str
    format: str                      # txt | pdf | docx | xlsx | other
    role_hint: Optional[str] = None  # SI / BL guessed from the filename only
    detected_type: str = "UNKNOWN"   # SI | BL | COMMERCIAL_INVOICE | PACKING_LIST | CERTIFICATE_OF_ORIGIN | UNKNOWN
    readable: bool = True
    read_error: Optional[str] = None
    size_bytes: int = 0
    text_chars: int = 0
    text_preview: str = ""
    fields: dict[str, FieldValue] = Field(default_factory=dict)
    extraction_method: str = "none"  # rules | ai | ai+rules | none


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
    action: Literal["confirm", "escalate", "resolve", "reopen"]
    note: Optional[str] = None
    by: str = "operator"
    at: str


class CaseResult(BaseModel):
    email_id: str
    subject: str
    sender: str
    attachments: list[str] = Field(default_factory=list)

    category: Category
    category_confidence: float
    category_reason: str = ""
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
    warnings: list[str] = Field(default_factory=list)
    analysed_at: str
    duration_ms: int = 0

    decision: Optional[Decision] = None
    resolved: bool = False


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
