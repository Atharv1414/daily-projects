"""Guardrails: prompt-injection detection, PII redaction and output (commitment) checks.

These are heuristic, deterministic layers that sit *around* the model. They are not a
complete defence on their own; the stronger guarantee comes from policy.py, which enforces
limits in code regardless of what the model is persuaded to try.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from broadband_support_agent.state import SessionState

INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "override",
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all)\b"
            r".{0,20}\b(instructions?|rules?|prompts?)\b",
            re.I | re.S,
        ),
    ),
    (
        "role_spoof",
        re.compile(
            r"\b(system|developer|admin(istrator)?)\s*(override|mode|prompt|"
            r"message)\s*[:\-]",
            re.I,
        ),
    ),
    (
        "role_play",
        re.compile(
            r"\byou are (now|no longer)\b|\bact as (an? )?(admin|manager|"
            r"supervisor|system)\b",
            re.I,
        ),
    ),
    (
        "exfiltrate",
        re.compile(
            r"\b(reveal|print|show|repeat)\b.{0,30}\b(system prompt|your "
            r"instructions|hidden rules)\b",
            re.I,
        ),
    ),
    (
        "fake_auth",
        re.compile(
            r"\b(pre-?approved|already approved|authori[sz]ed) by (a |the )?"
            r"(manager|supervisor|admin|team leader)\b",
            re.I,
        ),
    ),
    (
        "tool_coercion",
        re.compile(
            r"\b(call|run|execute|use) (the )?(apply_bill_credit|"
            r"book_engineer_visit|tool)\b.{0,40}\b(now|immediately|"
            r"without)\b",
            re.I,
        ),
    ),
    ("delimiter", re.compile(r"</?(untrusted_data|system|tool_result|instructions)>", re.I)),
]

CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
SORT_CODE_RE = re.compile(r"\b\d{2}-\d{2}-\d{2}\b")
PHONE_RE = re.compile(r"\b07\d{3}\s?\d{6}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")


@dataclass(frozen=True)
class InjectionFinding:
    rule: str
    excerpt: str


def detect_injection(text: str) -> list[InjectionFinding]:
    findings = []
    for rule, pattern in INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(InjectionFinding(rule, match.group(0)[:80]))
    return findings


def neutralise(text: str) -> tuple[str, list[InjectionFinding]]:
    """Remove sentences that look like injected instructions from untrusted tool output."""
    findings = detect_injection(text)
    if not findings:
        return text, []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = [s for s in sentences if not detect_injection(s)]
    cleaned = " ".join(kept).strip()
    marker = "[removed: suspected prompt injection]"
    return (f"{cleaned} {marker}".strip() if cleaned else marker), findings


def redact_pii(text: str) -> str:
    """Mask card numbers, sort codes, phones and emails before anything is logged."""
    text = CARD_RE.sub(lambda m: "[CARD ****" + re.sub(r"\D", "", m.group(0))[-4:] + "]", text)
    text = SORT_CODE_RE.sub("[SORT CODE]", text)
    text = PHONE_RE.sub("[PHONE]", text)
    return EMAIL_RE.sub("[EMAIL]", text)


def contains_card_number(text: str) -> bool:
    for match in CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return True
    return False


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


MONEY_RE = re.compile(r"£\s?(\d+(?:\.\d{1,2})?)")
CREDIT_CLAIM_RE = re.compile(r"(credit|refund)", re.I)
BOOKING_CLAIM_RE = re.compile(
    r"\b(engineer|visit|appointment)\b.{0,40}\b(booked|confirmed|scheduled)\b|"
    r"\b(booked|scheduled)\b.{0,30}\b(engineer|visit|appointment)\b",
    re.I,
)
NEGATION_RE = re.compile(r"\b(not|no|never|unable|cannot)\b|n['’]t\b", re.I)


def _clauses(text: str) -> list[str]:
    """Split into clauses so a negation in one clause ("No problem, ...") does not mask a claim
    in another, and a negated clause ("I haven't booked one") is not read as a claim."""
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        out.extend(c.strip() for c in re.split(r"[,;:]|\b(?:but|so)\b", sentence) if c.strip())
    return out


def check_commitments(answer: str, state: SessionState) -> list[str]:
    """Flag promises in the final reply that the harness state does not back up.

    The classic support-bot failure is *saying* "I've applied a £20 credit" without calling the
    tool. We compare money amounts in clauses that claim a credit/refund was applied with the
    credits actually written, and engineer-booking claims with actual bookings.
    """
    problems: list[str] = []
    applied = {round(c["amount_gbp"], 2) for c in state.credits_applied}
    applied.add(state.total_credited)
    clauses = _clauses(answer)
    for clause in clauses:
        if not CREDIT_CLAIM_RE.search(clause) or NEGATION_RE.search(clause):
            continue
        if re.search(r"\b(applied|added|issued|processed|refunded)\b", clause, re.I) is None:
            continue
        for amount in MONEY_RE.findall(clause):
            if round(float(amount), 2) not in applied:
                problems.append(f"Reply claims a £{float(amount):.2f} credit that was not applied.")
    if not state.bookings:
        for clause in clauses:
            if BOOKING_CLAIM_RE.search(clause) and not NEGATION_RE.search(clause):
                problems.append("Reply claims an engineer visit was booked, but none was.")
                break
    return problems
