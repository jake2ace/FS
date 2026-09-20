"""Thin provider-agnostic client for structured (JSON) completions.

Supports OpenAI, Anthropic and Gemini through their plain HTTPS APIs so the
backend has no vendor SDK dependency.  The API key never leaves this module
and is only ever read from the environment.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Optional

import httpx

from . import config
from .schemas import CATEGORIES, FIELDS


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    # strip ```json fences
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


class AIClient:
    def __init__(self, provider: str = "", api_key: str = "", model: str = "", timeout: float = 60.0,
                 mode: str = "full"):
        self.provider = (provider or config.AI_PROVIDER or "none").lower()
        self.api_key = api_key or config.AI_API_KEY
        self.model = model or config.resolved_model()
        self.timeout = timeout or config.AI_TIMEOUT
        self.mode = (mode or config.AI_MODE or "full").lower()
        self.calls = 0
        self.failures = 0
        self.last_error: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self.provider in ("openai", "anthropic", "gemini") and bool(self.api_key) and self.mode != "off"

    def describe(self) -> dict:
        return {
            "provider": self.provider if self.enabled else "none",
            "model": self.model if self.enabled else None,
            "mode": self.mode,
            "enabled": self.enabled,
            "calls": self.calls,
            "failures": self.failures,
            "last_error": self.last_error,
        }

    # -- low level -----------------------------------------------------------
    async def complete_json(self, system: str, user: str, max_tokens: int = 900) -> Optional[dict]:
        if not self.enabled:
            return None
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                self.calls += 1
                text = await self._call(system, user, max_tokens)
                obj = _extract_json(text)
                if obj is None:
                    raise ValueError("model did not return a JSON object")
                return obj
            except Exception as exc:  # network, 429, 5xx, bad JSON
                last_exc = exc
                self.failures += 1
                self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                retryable = isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)) or (
                    isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (408, 409, 429, 500, 502, 503, 504)
                ) or isinstance(exc, ValueError)
                if not retryable or attempt == 2:
                    break
                await asyncio.sleep(1.5 * (attempt + 1))
        return None

    async def _call(self, system: str, user: str, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if self.provider == "openai":
                r = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": self.model,
                        "temperature": 0,
                        "max_tokens": max_tokens,
                        "response_format": {"type": "json_object"},
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    },
                )
                r.raise_for_status()
                data = r.json()
                return data["choices"][0]["message"]["content"]
            if self.provider == "anthropic":
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                    json={
                        "model": self.model,
                        "max_tokens": max_tokens,
                        "temperature": 0,
                        "system": system + "\nRespond with a single JSON object and nothing else.",
                        "messages": [{"role": "user", "content": user}],
                    },
                )
                r.raise_for_status()
                data = r.json()
                return "".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")
            if self.provider == "gemini":
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json={
                        "systemInstruction": {"parts": [{"text": system}]},
                        "contents": [{"role": "user", "parts": [{"text": user}]}],
                        "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"},
                    },
                )
                r.raise_for_status()
                data = r.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
        raise RuntimeError(f"unsupported provider {self.provider}")

    # -- tasks ---------------------------------------------------------------
    CLASSIFY_SYSTEM = (
        "You are the triage assistant of a shipping documentation team. Classify ONE email from the shared inbox "
        "into exactly one category:\n"
        "- BL_COMPARISON: a request to check / confirm / compare a Shipping Instruction (SI) against a draft Bill of Lading (BL), "
        "including 'please send the draft BL for checking', 'to confirm docs', 'amend BL', 'request BL draft'.\n"
        "- SI_REQUEST: a new shipping instruction is requested or provided (subjects like 'SI - ...', 'CUST SI', 'REQUEST SI', 'SI NEEDED'; "
        "bodies that contain an inline SI with POL / POD / Shipper).\n"
        "- INVOICE_QUERY: invoices, billing, charges, D&D / detention, missing GR, cancel invoice, freight cost questions.\n"
        "- GENERAL: operational notices - update summaries, berthing reports, outstanding lists, SLA reminders, RPA bot notifications "
        "('automated notification ... no action required'), HR / holiday notices.\n"
        "- SPAM: phishing, prizes, parcel fees, mailbox warnings, unsolicited offers, scams.\n"
        "Subjects can be coded or misleading; the body is the primary evidence. "
        "Also report the intent for BL_COMPARISON emails: 'verify_documents' when documents are (said to be) attached for checking or a comparison is requested, "
        "'request_draft' when the sender asks someone to send the draft BL, otherwise 'other'.\n"
        'Return JSON: {"category": "...", "confidence": 0.0-1.0, "reason": "one short sentence", "intent": "verify_documents|request_draft|other"}'
    )

    async def classify_email(self, email: dict) -> Optional[dict]:
        body = (email.get("body") or "")[:3000]
        user = (
            f"From: {email.get('from','')}\nSubject: {email.get('subject','')}\n"
            f"Attachments: {', '.join(email.get('attachments') or []) or '(none)'}\n\nBody:\n{body}"
        )
        obj = await self.complete_json(self.CLASSIFY_SYSTEM, user, max_tokens=300)
        if not obj:
            return None
        cat = str(obj.get("category", "")).strip().upper()
        if cat not in CATEGORIES:
            return None
        try:
            conf = float(obj.get("confidence", 0.7))
        except Exception:
            conf = 0.7
        intent = str(obj.get("intent", "other")).strip().lower()
        if intent not in ("verify_documents", "request_draft", "other"):
            intent = "other"
        return {"category": cat, "confidence": max(0.0, min(1.0, conf)), "reason": str(obj.get("reason", ""))[:300], "intent": intent}

    EXTRACT_SYSTEM = (
        "You extract shipment data from ONE shipping document (plain text rendering of a TXT, PDF, DOCX or XLSX file).\n"
        "First decide the document type: SI (shipping instruction / BL instruction), BL (bill of lading, usually a draft), "
        "COMMERCIAL_INVOICE, PACKING_LIST, CERTIFICATE_OF_ORIGIN or OTHER.\n"
        "Then extract these seven fields, aligning labels by MEANING (e.g. 'Port of Loading' = 'Load Port' = 'POL'; "
        "'Consignee' = 'To the Order of'; 'Gross Wt (kgs)' = 'Gross Weight (KG)'):\n"
        "shipper, consignee, notify_party (party NAME only, no address lines), port_of_loading, port_of_discharge (as written), "
        "container_count (total number of containers as an integer), gross_weight_kg (total gross weight in kilograms as a number; convert MT to kg).\n"
        "Rules: copy values exactly from the document; never guess. If a field is absent, blank or a placeholder such as '???', '____', 'TBA', 'N/A', "
        "set its value to null. Give the source line as evidence.\n"
        'Return JSON: {"doc_type": "...", "fields": {"shipper": {"value": "...", "evidence": "..."}, ... all seven ...}, "confidence": 0.0-1.0, "notes": "..."}'
    )

    async def extract_document(self, text: str, filename: str = "") -> Optional[dict]:
        user = f"File name: {filename}\n\nDocument text:\n{text[:7000]}"
        obj = await self.complete_json(self.EXTRACT_SYSTEM, user, max_tokens=900)
        if not obj or not isinstance(obj.get("fields"), dict):
            return None
        fields: dict[str, dict] = {}
        for fld in FIELDS:
            raw = obj["fields"].get(fld)
            if isinstance(raw, dict):
                val = raw.get("value")
                ev = raw.get("evidence")
            else:
                val, ev = raw, None
            if val is not None:
                val = str(val).strip()
                if val.lower() in ("", "null", "none", "n/a", "na", "tba", "tbd", "???"):
                    val = None
            fields[fld] = {"value": val, "evidence": (str(ev)[:300] if ev else None)}
        doc_type = str(obj.get("doc_type", "OTHER")).strip().upper().replace(" ", "_")
        if doc_type not in ("SI", "BL", "COMMERCIAL_INVOICE", "PACKING_LIST", "CERTIFICATE_OF_ORIGIN"):
            doc_type = "UNKNOWN"
        try:
            conf = float(obj.get("confidence", 0.8))
        except Exception:
            conf = 0.8
        return {"doc_type": doc_type, "fields": fields, "confidence": max(0.0, min(1.0, conf)), "notes": str(obj.get("notes", ""))[:300]}

    EXPLAIN_SYSTEM = (
        "You write the one-paragraph explanation shown to a logistics operations officer in a document verification workspace. "
        "Tone: concise, formal, factual English. Never overstate certainty; if the case is uncertain say what is unknown. "
        'Return JSON: {"explanation": "2-3 sentences", "suggested_action": "one imperative sentence"}'
    )

    async def explain_case(self, summary: str) -> Optional[dict]:
        obj = await self.complete_json(self.EXPLAIN_SYSTEM, summary, max_tokens=300)
        if not obj:
            return None
        return {"explanation": str(obj.get("explanation", ""))[:800], "suggested_action": str(obj.get("suggested_action", ""))[:300]}
