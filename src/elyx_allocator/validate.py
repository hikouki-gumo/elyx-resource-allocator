"""The realism gate. 'Realistic' == passes all five rules.

1. field coherence   — type aligns with facilitator role; physical therapies aren't remote
2. referential integrity — facilitator/equipment ids resolve; backups reference real activities
3. variety           — >=80% unique names (no clone spam)
4. distribution      — each type 10–40% of the catalog (a believable protocol mix)
5. (aggregate)       — validate() composes the above into a pass/fail Report
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter

from .models import Activity, ActivityType, MealRelation


# type -> facilitator roles that make sense (facilitator is always a person, or "self")
ALLOWED_ROLES = {
    ActivityType.FITNESS: {"trainer", "coach", "physio", "self"},
    ActivityType.FOOD: {"dietitian", "self"},
    ActivityType.MEDICATION: {"physician", "self"},
    ActivityType.THERAPY: {"technician", "physio", "self"},
    ActivityType.CONSULTATION: {"physician", "dietitian", "psychologist", "physio",
                                "sports-medicine", "lab-technician", "self"},
}

# physical therapies can't happen over video
NON_REMOTE_TYPES = {ActivityType.THERAPY}

MIN_TYPE_SHARE = 0.10
MAX_TYPE_SHARE = 0.40
MIN_UNIQUE_RATIO = 0.80


@dataclass
class Report:
    ok: bool
    errors: list = field(default_factory=list)


def check_field_coherence(a: Activity) -> list:
    errors = []
    role = (a.facilitator or {}).get("role")
    allowed = ALLOWED_ROLES.get(a.type, set())
    if role not in allowed:
        errors.append(f"{a.id}: facilitator role '{role}' incoherent for type '{a.type.value}'")
    if a.type in NON_REMOTE_TYPES and a.remote_capable:
        errors.append(f"{a.id}: type '{a.type.value}' cannot be remote_capable")
    # details must carry real coaching info, not just echo the name (assignment field 3)
    if (a.details or "").strip() == (a.name or "").strip():
        errors.append(f"{a.id}: details just echoes the name — needs concrete coaching info")
    # fasted / empty-stomach activities must say so in prep (assignment field 7)
    if a.circadian.meal_relation in (MealRelation.FASTED, MealRelation.EMPTY_STOMACH) \
            and not (a.prep or {}).get("description", "").strip():
        errors.append(f"{a.id}: {a.circadian.meal_relation.value} activity must declare prep")
    return errors


def check_referential_integrity(catalog: list, resources: dict) -> list:
    errors = []
    ids = {a.id for a in catalog}
    for a in catalog:
        fid = (a.facilitator or {}).get("id")
        if fid and fid not in resources:
            errors.append(f"{a.id}: facilitator resource '{fid}' not found in availability")
        if a.location and a.location not in resources:
            errors.append(f"{a.id}: location resource '{a.location}' not found in availability")
        for b in a.backups:
            if b not in ids:
                errors.append(f"{a.id}: backup '{b}' is not a known activity")
    return errors


def check_variety(catalog: list) -> list:
    if not catalog:
        return []
    unique = len({a.name for a in catalog})
    if unique / len(catalog) < MIN_UNIQUE_RATIO:
        return [f"variety: only {unique} unique names across {len(catalog)} activities "
                f"(< {int(MIN_UNIQUE_RATIO*100)}%)"]
    return []


def check_distribution(catalog: list) -> list:
    if not catalog:
        return []
    errors = []
    n = len(catalog)
    counts = Counter(a.type for a in catalog)
    for t in ActivityType:
        share = counts.get(t, 0) / n
        if share > MAX_TYPE_SHARE:
            errors.append(f"distribution: type '{t.value}' is {share:.0%} (> {MAX_TYPE_SHARE:.0%})")
        elif share < MIN_TYPE_SHARE:
            errors.append(f"distribution: type '{t.value}' is {share:.0%} (< {MIN_TYPE_SHARE:.0%})")
    return errors


def validate(catalog: list, resources: dict) -> Report:
    errors = []
    for a in catalog:
        errors += check_field_coherence(a)
    errors += check_referential_integrity(catalog, resources)
    errors += check_variety(catalog)
    errors += check_distribution(catalog)
    return Report(ok=(len(errors) == 0), errors=errors)
