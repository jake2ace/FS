"""Rule-based email classification (used on its own when no AI provider is
configured, and as a cross-check / fallback when one is).

Categories follow the official participant bundle:
BL_COMPARISON, SI_REQUEST, INVOICE_QUERY, GENERAL, SPAM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

TRUSTED_DOMAIN_HINTS = ("april", "vitalsolutions", "psabdp", "fujitogrp", "ifpla", "safqa", "algurg", "paperone")

SPAM_BODY = [
    (r"click here", 3), (r"claim (your|now)", 3), (r"gift card", 3), (r"\bprize\b", 3), (r"congratulations", 2),
    (r"limited time offer", 3), (r"buy now", 2), (r"% off", 2), (r"verify (your )?account", 3),
    (r"storage (limit|is full)", 3), (r"mailbox has exceeded", 3), (r"unpaid customs fee", 3),
    (r"parcel will be returned", 3), (r"could not be delivered", 2), (r"deal expires", 2), (r"weird trick", 3),
    (r"undelivered messages", 2), (r"suspension", 2), (r"bit\.ly|track-parcel|webmail-verify|claim-prize", 3),
    (r"dear (valued customer|user)", 2), (r"selected in our .*draw", 3), (r"trusted by [\d,]+\+? companies", 2),
    (r"bank officer|business proposal|next of kin|inheritance", 4), (r"confirm your bank (details|account)", 4),
    (r"hot singles|bitcoin|crypto|investment opportunity", 4), (r"\busd\s?[\d,.]+\s?(million|m)\b", 3), (r"hello dear", 2),
]
INVOICE_BODY = [
    (r"\binvoice\b", 3), (r"\bbilling\b", 2), (r"\bcharges?\b", 2), (r"d\s*&\s*d|detention|demurrage", 3),
    (r"\bthc\b|local charge", 3), (r"\bgr\b.*missing|missing gr", 3), (r"release payment|payment", 2),
    (r"cancel(l)?ation|cancel invoice", 2), (r"breakdown", 1), (r"credit note|debit note", 3), (r"\bfreight (cost|charge|amount|invoice)", 2),
]
SI_BODY = [
    (r"please find (the )?shipping instruction", 4), (r"shipping instruction for", 4), (r"\bsi\b.*(needed|required|request)", 3),
    (r"(new|revised|attached|our) shipping instruction", 3), (r"^pol\s*:", 2), (r"^pod\s*:", 2), (r"^shipper\s*:", 2),
    (r"kindly (prepare|issue|submit) (the )?si\b", 3), (r"\bcust si\b", 3),
]
BL_BODY = [
    (r"draft bl\b|draft b/l|draft bill of lading|bl draft", 4), (r"attached are the si and", 4),
    (r"check the details and confirm", 3), (r"verify the bl matches the si", 4), (r"compare the si and", 4),
    (r"confirm the bl is in order", 4), (r"send the draft bl", 3), (r"for checking", 2), (r"amend(ment)? bl", 3),
    (r"\bsi and (draft )?bl\b", 3), (r"bl comparison|to confirm docs", 3), (r"release to the line", 2),
]
GENERAL_BODY = [
    (r"berthing report", 4), (r"update summary", 4), (r"outstanding bl", 3), (r"kindly action the pending items", 3),
    (r"\breminder\b", 2), (r"submit si\s*&\s*aed", 3), (r"holiday|new year|office resumes|festive", 3),
    (r"\bsla\b", 2), (r"loading completed", 3), (r"documents to follow", 2), (r"happy and prosperous", 3),
    (r"berthed on schedule", 3), (r"wishing everyone", 3), (r"system maintenance|downtime", 2), (r"town ?hall|training session", 2),
    (r"automated notification", 5), (r"no action required", 4), (r"rpa bot|-- rpa", 5), (r"has completed successfully", 3),
    (r"time off|leave request|approval required", 3), (r"delivery planning|miss connection", 3),
]
SUBJECT_HINTS = {
    "SPAM": [(r"weird trick", 3), (r"update your account", 3), (r"storage is full", 3), (r"undelivered messages", 3), (r"prize|winner|lottery", 3), (r"urgent:", 1), (r"customs fee|parcel", 2), (r"dear valued customer", 3)],
    "INVOICE_QUERY": [(r"\binvoice\b", 3), (r"charges", 2), (r"d\s*&\s*d", 3), (r"total freight", 2), (r"billing", 1), (r"missing gr", 3), (r"local charges", 3)],
    "SI_REQUEST": [(r"^(re_?\s*)?si\s*-", 4), (r"\bcust si\b", 4), (r"request si", 4), (r"si needed", 4), (r"\bsi\b", 1)],
    "BL_COMPARISON": [(r"to confirm docs", 3), (r"request bl draft", 3), (r"draft bl", 3), (r"amend bl", 3), (r"bl draft", 2), (r"\b(aie|afrt|afemy|afptme|aiu|afin)\b\s*-", 2)],
    "GENERAL": [(r"update summary", 3), (r"berthing report", 3), (r"_rpa_", 3), (r"reminder", 2), (r"holiday|new year", 2), (r"outstanding", 2),
                (r"pending bl release", 2), (r"miss connection", 2), (r"time off", 2), (r"approval required", 2), (r"delivery planning", 2)],
}
INLINE_SI = re.compile(r"\bpol\s*:.*\bpod\s*:", re.IGNORECASE | re.DOTALL)


@dataclass
class RuleResult:
    category: str
    confidence: float
    reason: str
    intent: str          # verify_documents | request_draft | other
    scores: dict


def _score(text: str, rules: list[tuple[str, int]], flags=re.IGNORECASE | re.MULTILINE) -> tuple[int, list[str]]:
    total, hits = 0, []
    for pattern, weight in rules:
        if re.search(pattern, text, flags):
            total += weight
            hits.append(pattern)
    return total, hits


def detect_intent(subject: str, body: str) -> str:
    b = body.lower()
    if re.search(r"please (assist to )?send (the |us )?(draft )?bl|send the draft|kindly send|please provide the draft|share the draft", b):
        return "request_draft"
    if re.search(r"attached|attach(ed)? (are|is)|find attached|enclosed|please compare|verify the bl|check the details|confirm the bl|for checking|for your confirmation|kindly verify|kindly confirm", b):
        return "verify_documents"
    return "other"


def classify_rules(email: dict) -> RuleResult:
    subject = email.get("subject", "") or ""
    body = email.get("body", "") or ""
    sender = (email.get("from", "") or "").lower()
    body_l = body.lower()
    # ignore the corporate warning banner some emails carry
    body_l = re.sub(r"warning: this email originated outside.*?attachments\.", " ", body_l, flags=re.DOTALL)

    scores = {"BL_COMPARISON": 0, "SI_REQUEST": 0, "INVOICE_QUERY": 0, "GENERAL": 0, "SPAM": 0}
    hits: dict[str, list[str]] = {k: [] for k in scores}

    for cat, rules in (("SPAM", SPAM_BODY), ("INVOICE_QUERY", INVOICE_BODY), ("SI_REQUEST", SI_BODY),
                       ("BL_COMPARISON", BL_BODY), ("GENERAL", GENERAL_BODY)):
        s, h = _score(body_l, rules)
        scores[cat] += 2 * s          # body counts double: subjects are often coded or misleading
        hits[cat] += h
    for cat, rules in SUBJECT_HINTS.items():
        s, h = _score(subject.lower(), rules)
        scores[cat] += s
        hits[cat] += [f"subject:{x}" for x in h]

    # an inline shipping instruction in the body is a strong SI signal
    if INLINE_SI.search(body_l):
        scores["SI_REQUEST"] += 4
        hits["SI_REQUEST"].append("inline SI (POL/POD block)")

    domain = sender.split("@")[-1]
    if domain and not any(h in domain for h in TRUSTED_DOMAIN_HINTS):
        if any(x in domain for x in ("deals", "prize", "verify", "secure", "crypto", "offers", "winner", "claims", "promo", "free")):
            scores["SPAM"] += 4
            hits["SPAM"].append(f"sender domain {domain}")
        else:
            scores["SPAM"] += 1
    if scores["SPAM"] >= 6:
        # spam signals dominate anything else
        scores["SPAM"] += 4

    # attachments named _SI/_BL are a BL comparison signal
    atts = email.get("attachments") or []
    if any(re.search(r"_(si|bl)\.", a, re.IGNORECASE) for a in atts):
        scores["BL_COMPARISON"] += 3
        hits["BL_COMPARISON"].append("SI/BL attachments present")

    best = max(scores, key=scores.get)
    ranked = sorted(scores.values(), reverse=True)
    top, second = ranked[0], ranked[1] if len(ranked) > 1 else 0
    if top <= 0:
        best, confidence = "GENERAL", 0.35
        reason = "no category signals found; defaulted to GENERAL"
    else:
        margin = top - second
        confidence = min(0.97, 0.5 + 0.06 * margin + 0.02 * min(top, 10))
        reason = "signals: " + ", ".join(hits[best][:4]) if hits[best] else "weak signals"
    intent = detect_intent(subject, body_l) if best == "BL_COMPARISON" else "other"
    return RuleResult(category=best, confidence=round(confidence, 2), reason=reason, intent=intent, scores=scores)
