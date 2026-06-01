"""Unit tests — the type spine (models.py)."""
from datetime import datetime
import pytest

from elyx_allocator.models import (
    ActivityType, Pillar, Mode, Frequency, ScheduledTask,
)
from tests.conftest import make_activity


def test_activity_type_has_five_members():
    assert {t.value for t in ActivityType} == {
        "fitness", "food", "medication", "therapy", "consultation"
    }


def test_pillar_has_seven_members():
    assert len(list(Pillar)) == 7


def test_make_activity_builds_with_expected_fields():
    a = make_activity()
    assert a.id == "act-strength"
    assert a.type is ActivityType.FITNESS
    assert a.pillar is Pillar.MOVEMENT
    assert a.frequency.times == 3
    assert a.backups == ["act-bodyweight"]
    assert a.duration_min == 60


def test_frequency_total_occurrences():
    assert Frequency(times=3, period="week").total_occurrences(7) == 3
    assert Frequency(times=1, period="day").total_occurrences(7) == 7
    assert Frequency(times=1, period="month").total_occurrences(90) == 3


def test_scheduled_task_defaults_to_planned():
    t = ScheduledTask(
        activity_id="act-strength",
        start=datetime(2026, 6, 1, 18, 30),
        end=datetime(2026, 6, 1, 19, 30),
        mode=Mode.IN_PERSON,
        pillar=Pillar.MOVEMENT,
        reason="48h since last lift; evening slot clear",
    )
    assert t.status == "planned"
    assert t.substituted_from is None
    assert t.reason


def test_scheduled_task_carries_substitution_and_reason():
    t = ScheduledTask(
        activity_id="act-bodyweight",
        start=datetime(2026, 6, 16, 7, 0),
        end=datetime(2026, 6, 16, 7, 30),
        mode=Mode.REMOTE,
        pillar=Pillar.MOVEMENT,
        reason="hotel — no equipment; substituted for strength",
        substituted_from="act-strength",
    )
    assert t.substituted_from == "act-strength"
    assert t.mode is Mode.REMOTE
