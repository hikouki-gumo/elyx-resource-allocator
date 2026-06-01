"""Shared fixtures + factories for the Elyx Resource Allocator test suite.

These reference the API we *wish* existed; until the modules are implemented the
imports fail and every test is RED — which is the point (test-first).
"""
from datetime import date
import pytest

from elyx_allocator.models import (
    Activity, ActivityType, Pillar, Frequency, Circadian, Window, MealRelation,
    Load, Intensity, TravelBehavior, Resource, ResourceTier, TravelTrip,
    ClientCommitments, Availability,
)


def make_activity(**kw):
    """Factory: a coherent default Activity, override any field via kwargs."""
    defaults = dict(
        id="act-strength",
        name="Strength training",
        type=ActivityType.FITNESS,
        pillar=Pillar.MOVEMENT,
        priority=10,
        frequency=Frequency(times=3, period="week"),
        details="Full-body, RPE 8",
        facilitator={"role": "trainer", "id": "res-trainer"},
        location="res-gym",
        remote_capable=False,
        prep={"description": "", "lead_time_min": 0},
        backups=["act-bodyweight"],
        skip_adjustment="add mobility the next day",
        metrics=["load", "RPE"],
        circadian=Circadian(window=Window.EVENING, meal_relation=MealRelation.NONE),
        load=Load(intensity=Intensity.HIGH, score=8),
        min_gap_hours=48,
        duration_min=60,
        travel_behavior=TravelBehavior.BACKUP,
    )
    defaults.update(kw)
    return Activity(**defaults)


def make_resource(**kw):
    defaults = dict(
        id="res-trainer",
        type="facilitator",
        tier=ResourceTier.MODERATE,
        capacity=1,
        operating_hours={d: ("06:00", "21:00") for d in range(7)},
        booked_windows=[],
        remote_offered=True,
    )
    defaults.update(kw)
    return Resource(**defaults)


@pytest.fixture
def commitments():
    return ClientCommitments(
        sleep=("22:30", "06:30"),
        work_blocks=[(d, "09:00", "18:00") for d in range(5)],  # Mon–Fri
        meals=["08:00", "12:30", "19:00"],
    )


@pytest.fixture
def resources():
    return {
        "res-trainer": make_resource(id="res-trainer"),
        "res-gym": make_resource(id="res-gym", type="equipment", capacity=1),
        "res-sauna": make_resource(id="res-sauna", type="equipment", capacity=1, remote_offered=False),
        "res-dietitian": make_resource(id="res-dietitian", type="allied_health", capacity=1, remote_offered=True),
    }


@pytest.fixture
def availability(resources, commitments):
    return Availability(resources=resources, travel=[], commitments=commitments)


@pytest.fixture
def availability_with_travel(resources, commitments):
    trip = TravelTrip(start=date(2026, 6, 15), end=date(2026, 6, 19),
                      destination="New York", timezone="America/New_York")
    return Availability(resources=resources, travel=[trip], commitments=commitments)


@pytest.fixture
def start_date():
    return date(2026, 6, 1)  # a Monday
