"""Validate AI response structure. No shipping-value comparisons live here."""
import re
from typing import Literal
from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator
from .schemas import Category, ClassificationEvidence, Status, ReviewReason


def source_excerpt(evidence: str | None, text: str) -> bool:
    """Only verify source presence, never the business meaning of a quotation."""
    normalize = lambda s: re.sub(r'\s+', ' ', s).strip()
    return bool(evidence and normalize(evidence) and normalize(evidence) in normalize(text))


class Classification(BaseModel):
    category: Category
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason: str = Field(min_length=1)
    intent: Literal['verify_documents', 'request_draft', 'other']
    needs_review: StrictBool = False
    evidence: list[ClassificationEvidence] = Field(min_length=1, max_length=3)

    def validate_sources(self, email: dict) -> None:
        for item in self.evidence:
            if not source_excerpt(item.quote, email.get(item.source) or ''):
                raise ValueError('Classification evidence is absent from the stated email source.')


class Reading(BaseModel):
    value: str | None
    evidence: str | None
    label: str | None = None


class DocumentReading(BaseModel):
    index: StrictInt = Field(ge=0)
    doc_type: Literal['SI', 'BL', 'COMMERCIAL_INVOICE', 'PACKING_LIST', 'CERTIFICATE_OF_ORIGIN', 'UNKNOWN']
    fields: dict[str, Reading]

    @field_validator('fields', mode='before')
    @classmethod
    def explicit_null_readings(cls, value):
        # Both {field: null} and {field: {value: null, evidence: null}} express
        # the model's same missing reading. Only normalize its JSON representation.
        if isinstance(value, dict):
            return {key: {'value': None, 'evidence': None, 'label': None} if item is None else item
                    for key, item in value.items()}
        return value


class Comparison(BaseModel):
    match: StrictBool | None
    reason: str


class Verdict(BaseModel):
    documents: list[DocumentReading]
    comparisons: dict[str, Comparison]
    status: Status
    review_reason: ReviewReason | None
    defect_fields: list[str]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    explanation: str = Field(min_length=1)
    suggested_action: str = Field(min_length=1)
