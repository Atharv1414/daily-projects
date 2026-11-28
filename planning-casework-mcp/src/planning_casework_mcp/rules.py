"""Deterministic planning rules. These are the facts the agent must never make up.

Statutory periods follow the Town and Country Planning (Development Management Procedure)
(England) Order 2015 in simplified form: 13 weeks for major development, 16 weeks where an
Environmental Impact Assessment is needed, 8 weeks for everything else, and 56 days for prior
approval (after which approval is deemed to be given). Publicity runs for 21 days, and no
decision may be issued before it ends.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .domain import Application, AppType, PublicComment, Recommendation, Stance, Status

CONSULTATION_DAYS = 21
COMMITTEE_OBJECTION_THRESHOLD = 5


class RuleError(ValueError):
    """A business rule forbids the requested action."""


@dataclass(frozen=True)
class Deadline:
    statutory_period: str
    statutory_date: date | None
    effective_date: date | None  # statutory date, or the agreed extension of time
    consultation_ends: date | None
    can_determine_from: date | None
    days_remaining: int | None
    overdue: bool
    deemed_consent_risk: bool  # prior approval: silence means approval
    clock_started: bool


def statutory_period(app: Application) -> tuple[str, timedelta]:
    if app.app_type is AppType.PRIOR_APPROVAL:
        return "56 days (prior approval: deemed consent if not determined)", timedelta(days=56)
    if app.is_eia:
        return "16 weeks (EIA development)", timedelta(weeks=16)
    if app.is_major:
        return "13 weeks (major development)", timedelta(weeks=13)
    return "8 weeks", timedelta(weeks=8)


def deadline(app: Application, today: date) -> Deadline:
    label, period = statutory_period(app)
    if app.validated is None:
        return Deadline(label, None, None, None, None, None, False, False, False)
    statutory = app.validated + period
    effective = max(statutory, app.extension_agreed_to) if app.extension_agreed_to else statutory
    consultation_ends = (
        app.consultation_start + timedelta(days=CONSULTATION_DAYS)
        if app.consultation_start
        else None
    )
    can_determine = consultation_ends + timedelta(days=1) if consultation_ends else None
    open_case = app.status.is_open
    remaining = (effective - today).days if open_case else None
    return Deadline(
        statutory_period=label,
        statutory_date=statutory,
        effective_date=effective,
        consultation_ends=consultation_ends,
        can_determine_from=can_determine,
        days_remaining=remaining,
        overdue=open_case and today > effective,
        deemed_consent_risk=app.app_type is AppType.PRIOR_APPROVAL and open_case,
        clock_started=True,
    )


# ---- public comment analysis -------------------------------------------------------------

MATERIAL_THEMES: dict[str, tuple[str, ...]] = {
    "loss of light / overshadowing": ("light", "overshadow", "sunlight", "dark"),
    "overlooking / privacy": ("overlook", "privacy", "look straight into"),
    "highways and parking": ("parking", "traffic", "highway", "road safety", "cars"),
    "noise and disturbance": ("noise", "disturbance", "late at night", "music"),
    "design and character": ("character", "design", "scale", "out of keeping", "bulk"),
    "flood risk": ("flood", "drainage", "surface water"),
    "trees": ("tree", "hedge", "oak"),
    "heritage": ("heritage", "listed", "conservation area", "historic"),
}
NON_MATERIAL_THEMES: dict[str, tuple[str, ...]] = {
    "loss of private view (not material)": ("my view", "the view"),
    "property values (not material)": ("value", "house price", "devalue"),
    "boundary / party wall (civil matter)": ("boundary", "party wall", "fence line"),
    "trade competition (not material)": ("competition", "another shop"),
}

INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore (all |any )?(previous|prior|above) (instructions|rules)",
        r"\bsystem\s*:",
        r"\byou are now\b",
        r"disregard (the|your) (policy|policies|instructions)",
        r"(approve|refuse) this (application )?(immediately|now) without",
        r"call the tool",
        r"</?(tool|function|assistant)",
    )
]


def looks_like_injection(text: str) -> bool:
    return any(p.search(text) for p in INJECTION_PATTERNS)


def classify_comment(text: str) -> tuple[list[str], list[str]]:
    lowered = text.lower()
    material = [t for t, words in MATERIAL_THEMES.items() if any(w in lowered for w in words)]
    non_material = [
        t for t, words in NON_MATERIAL_THEMES.items() if any(w in lowered for w in words)
    ]
    return material, non_material


@dataclass
class CommentSummary:
    total: int = 0
    objections: int = 0
    supports: int = 0
    neutral: int = 0
    objecting_addresses: int = 0
    material_objection_addresses: int = 0
    duplicates_removed: int = 0
    themes: dict[str, int] = field(default_factory=dict)
    non_material: dict[str, int] = field(default_factory=dict)
    flagged_injection_ids: list[int] = field(default_factory=list)


def summarise_comments(comments: list[PublicComment]) -> CommentSummary:
    """Counts objections by unique address (one household, one voice), as officers do."""
    s = CommentSummary()
    seen: set[tuple[str, str]] = set()
    objecting: set[str] = set()
    material_objecting: set[str] = set()
    for c in comments:
        key = (c.address.strip().lower(), c.text.strip().lower())
        if key in seen:
            s.duplicates_removed += 1
            continue
        seen.add(key)
        s.total += 1
        if looks_like_injection(c.text):
            s.flagged_injection_ids.append(c.comment_id)
        material, non_material = classify_comment(c.text)
        if c.stance is Stance.OBJECT:
            s.objections += 1
            objecting.add(c.address.strip().lower())
            if material:
                material_objecting.add(c.address.strip().lower())
            for t in material:
                s.themes[t] = s.themes.get(t, 0) + 1
            for t in non_material:
                s.non_material[t] = s.non_material.get(t, 0) + 1
        elif c.stance is Stance.SUPPORT:
            s.supports += 1
        else:
            s.neutral += 1
    s.objecting_addresses = len(objecting)
    s.material_objection_addresses = len(material_objecting)
    return s


# ---- scheme of delegation -----------------------------------------------------------------


@dataclass(frozen=True)
class Route:
    route: str  # "delegated" or "committee"
    reasons: list[str]


def decision_route(
    app: Application, summary: CommentSummary, recommendation: Recommendation
) -> Route:
    """Harrowfield's scheme of delegation: who is allowed to take the decision."""
    reasons: list[str] = []
    if app.is_major:
        reasons.append("major development is always decided by committee")
    if app.councillor_call_in:
        reasons.append("a ward councillor has called the application in")
    if app.applicant_is_member_or_staff:
        reasons.append("the applicant is a councillor or council employee")
    if (
        recommendation is Recommendation.APPROVE
        and summary.material_objection_addresses >= COMMITTEE_OBJECTION_THRESHOLD
    ):
        reasons.append(
            f"{summary.material_objection_addresses} households raised material objections "
            f"against an approval recommendation (threshold {COMMITTEE_OBJECTION_THRESHOLD})"
        )
    if reasons:
        return Route("committee", reasons)
    return Route("delegated", ["within the officer scheme of delegation"])


STANDARD_TIME_LIMIT = "TL01: The development must begin within three years of this permission."


def validate_draft(
    app: Application,
    recommendation: Recommendation,
    reasons: list[str],
    conditions: list[str],
    today: date,
) -> list[str]:
    """Checks a decision draft against the rules; returns the conditions to use."""
    if not app.status.is_open:
        raise RuleError(f"{app.ref} is already {app.status.value}; it cannot be re-decided")
    if app.status is Status.RECEIVED or app.validated is None:
        raise RuleError(f"{app.ref} has not been validated, so it cannot be determined")
    d = deadline(app, today)
    if d.can_determine_from and today < d.can_determine_from:
        raise RuleError(
            f"publicity for {app.ref} ends on {d.consultation_ends}; the earliest decision date "
            f"is {d.can_determine_from}"
        )
    cleaned_reasons = [r.strip() for r in reasons if r.strip()]
    if recommendation is Recommendation.REFUSE and not cleaned_reasons:
        raise RuleError("a refusal must give at least one reason linked to policy")
    out = [c.strip() for c in conditions if c.strip()]
    if recommendation is Recommendation.APPROVE:
        if app.app_type in {AppType.PRIOR_APPROVAL, AppType.ADVERTISEMENT}:
            return out
        if not any(c.startswith("TL01") for c in out):
            out.insert(0, STANDARD_TIME_LIMIT)
    elif out:
        raise RuleError("conditions cannot be attached to a refusal")
    return out
