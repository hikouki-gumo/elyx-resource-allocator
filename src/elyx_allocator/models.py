"""The type spine: enums + dataclasses shared across the allocator.

A note on philosophy: the *intelligence lives in the data*. Each Activity carries
the coach's reasoning (circadian fit, load, pairing, travel behavior) so the
scheduler can stay a simple greedy pass and still produce a coach-quality week.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# --------------------------------------------------------------------------- enums
class ActivityType(str, Enum):
    FITNESS = "fitness"
    FOOD = "food"
    MEDICATION = "medication"
    THERAPY = "therapy"
    CONSULTATION = "consultation"


class Pillar(str, Enum):
    DIAGNOSTICS = "Diagnostics"
    MOVEMENT = "Movement"
    NUTRITION = "Nutrition"
    SLEEP = "Sleep"
    MIND = "Mind"
    MEDS = "Meds"
    THERAPIES = "Therapies"


class Mode(str, Enum):
    IN_PERSON = "in_person"
    REMOTE = "remote"
    SKIPPED = "skipped"


class Window(str, Enum):
    ANY = "any"
    MORNING = "morning"
    MIDDAY = "midday"
    EVENING = "evening"
    BEFORE_BED = "before_bed"


class MealRelation(str, Enum):
    NONE = "none"
    WITH_FOOD = "with_food"
    WITH_FAT = "with_fat"
    FASTED = "fasted"
    EMPTY_STOMACH = "empty_stomach"


class Intensity(str, Enum):
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class TravelBehavior(str, Enum):
    CONTINUE = "continue"   # do it anyway (home-style, e.g. supplements)
    REMOTE = "remote"       # switch to remote/video
    BACKUP = "backup"       # substitute a backup activity
    SKIP = "skip"           # drop + apply skip_adjustment


class ResourceTier(str, Enum):
    ABUNDANT = "abundant"
    BROAD = "broad"
    MODERATE = "moderate"
    SCARCE = "scarce"
    SINGLE_UNIT = "single_unit"


# --------------------------------------------------------------------------- value objects
_PERIOD_DAYS = {"day": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}


@dataclass
class Frequency:
    times: int
    period: str  # one of _PERIOD_DAYS

    def total_occurrences(self, days: int) -> int:
        """How many times this happens over `days` (rounded to nearest int)."""
        per_day = self.times / _PERIOD_DAYS[self.period]
        return round(per_day * days)


@dataclass
class Circadian:
    window: Window = Window.ANY
    meal_relation: MealRelation = MealRelation.NONE


@dataclass
class Load:
    intensity: Intensity = Intensity.NONE
    score: int = 0  # 0–10


# --------------------------------------------------------------------------- entities
@dataclass
class Activity:
    id: str
    name: str
    type: ActivityType
    pillar: Pillar
    priority: int                      # lower = more important to health
    frequency: Frequency
    details: str
    facilitator: dict                  # {"role": str, "id": Optional[str]}
    location: str
    remote_capable: bool
    prep: dict                         # {"description": str, "lead_time_min": int}
    backups: list                      # [activity_id] — same pillar
    skip_adjustment: Optional[str]     # None for standing constraints (no make-up exists)
    metrics: list                      # carried, filled downstream (Brain Hacker AI)
    circadian: Circadian
    load: Load
    min_gap_hours: int
    duration_min: int
    travel_behavior: TravelBehavior
    all_day: bool = False              # standing daily guardrail (a rule, not a timed slot)


@dataclass
class Resource:
    id: str
    type: str                          # human (trainer/physio/physician…) | location (gym/clinic/sauna…)
    tier: ResourceTier
    capacity: int
    operating_hours: dict              # {weekday(0=Mon): ("HH:MM", "HH:MM")}; empty = closed
    booked_windows: list = field(default_factory=list)  # [(datetime, datetime)] pre-booked by others
    remote_offered: bool = False
    label: str = ""                    # human-readable name for display


@dataclass
class TravelTrip:
    start: "object"                    # datetime.date
    end: "object"                      # datetime.date (inclusive)
    destination: str
    timezone: str


@dataclass
class ClientCommitments:
    sleep: tuple                       # ("22:30", "06:30")
    work_blocks: list = field(default_factory=list)   # [(weekday, "HH:MM", "HH:MM")]
    meals: list = field(default_factory=list)         # ["08:00", ...]


@dataclass
class Availability:
    resources: dict                    # {resource_id: Resource}
    travel: list = field(default_factory=list)        # [TravelTrip]
    commitments: Optional[ClientCommitments] = None


@dataclass
class ScheduledTask:
    activity_id: str
    start: datetime
    end: datetime
    mode: Mode
    pillar: Pillar
    reason: str
    resources: list = field(default_factory=list)     # [resource_id]
    substituted_from: Optional[str] = None            # original activity id if this is a backup
    note: Optional[str] = None                        # e.g. skip-adjustment applied
    status: str = "planned"                           # downstream (Brain Hacker AI) updates this
    title: str = ""                                   # human display name (activity.name)
    detail: dict = field(default_factory=dict)        # prep/backups/metrics/location for the drawer
    load: int = 0                                     # intensity rank 0–3 (rest/easy/moderate/hard) for the arc
