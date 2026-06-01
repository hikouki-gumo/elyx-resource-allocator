"""Unit tests — scheduler invariants. These ARE the definition of done."""
from datetime import date, datetime, time
import pytest

from elyx_allocator.models import (
    ActivityType, Pillar, Mode, Window, MealRelation, Intensity, Load,
    Frequency, TravelBehavior,
)
from elyx_allocator.scheduler import schedule
from tests.conftest import make_activity


def _overlaps(a, b):
    return a.start < b.end and b.start < a.end


def test_no_resource_double_booking(availability, start_date):
    plan = [
        make_activity(id="a1", name="Zone-2", facilitator={"role": "trainer", "id": "res-trainer"},
                      frequency=Frequency(7, "week"), remote_capable=False),
        make_activity(id="a2", name="Strength", facilitator={"role": "trainer", "id": "res-trainer"},
                      frequency=Frequency(7, "week"), remote_capable=False, backups=[]),
    ]
    tasks = schedule(plan, availability, start_date, days=7)
    by_res = {}
    for t in tasks:
        for r in t.resources:
            by_res.setdefault(r, []).append(t)
    for r, ts in by_res.items():
        ts.sort(key=lambda x: x.start)
        for i in range(1, len(ts)):
            assert not _overlaps(ts[i - 1], ts[i]), f"double-booked {r}"


def test_sleep_window_never_scheduled(availability, start_date):
    plan = [make_activity(id="a1", frequency=Frequency(7, "week"))]
    tasks = schedule(plan, availability, start_date, days=7)
    for t in tasks:
        # sleep 22:30–06:30 — nothing may start inside it
        h = t.start.hour + t.start.minute / 60
        assert not (h >= 22.5 or h < 6.5), f"task raids sleep window: {t.start}"


def test_frequency_expanded_across_horizon(availability, start_date):
    plan = [make_activity(id="a1", frequency=Frequency(3, "week"), remote_capable=True)]
    tasks = [t for t in schedule(plan, availability, start_date, days=14) if t.activity_id == "a1"]
    assert 5 <= len(tasks) <= 6  # 3/week over 2 weeks


def test_every_task_has_a_reason(availability, start_date):
    plan = [make_activity(id="a1", frequency=Frequency(3, "week"))]
    tasks = schedule(plan, availability, start_date, days=14)
    assert tasks
    assert all(t.reason.strip() for t in tasks)


def test_travel_week_goes_remote(availability_with_travel, start_date):
    plan = [make_activity(
        id="consult", name="Dietitian", type=ActivityType.CONSULTATION,
        pillar=Pillar.DIAGNOSTICS, facilitator={"role": "dietitian", "id": "res-dietitian"},
        location="clinic", remote_capable=True, frequency=Frequency(7, "week"),
        travel_behavior=TravelBehavior.REMOTE, backups=[],
    )]
    tasks = schedule(plan, availability_with_travel, start_date, days=21)
    trip_tasks = [t for t in tasks if date(2026, 6, 15) <= t.start.date() <= date(2026, 6, 19)]
    assert trip_tasks
    assert all(t.mode is Mode.REMOTE for t in trip_tasks)


def test_backup_substitution_when_resource_unavailable(start_date):
    # primary needs a closed resource, not remote-capable, has a backup → expect substitution
    from elyx_allocator.models import Resource, ResourceTier, ClientCommitments, Availability
    closed = Resource(id="res-sauna", type="equipment", tier=ResourceTier.SINGLE_UNIT,
                      capacity=1, operating_hours={}, booked_windows=[], remote_offered=False)
    avail = Availability(
        resources={"res-sauna": closed, "res-home": Resource(
            id="res-home", type="home", tier=ResourceTier.ABUNDANT, capacity=99,
            operating_hours={d: ("06:00", "22:00") for d in range(7)},
            booked_windows=[], remote_offered=False)},
        travel=[],
        commitments=ClientCommitments(sleep=("22:30", "06:30"), work_blocks=[], meals=[]),
    )
    plan = [
        make_activity(id="sauna", name="Sauna", type=ActivityType.THERAPY, pillar=Pillar.THERAPIES,
                      facilitator={"role": "facility", "id": "res-sauna"}, location="clinic",
                      remote_capable=False, frequency=Frequency(3, "week"),
                      travel_behavior=TravelBehavior.BACKUP, backups=["walk"]),
        make_activity(id="walk", name="Evening walk", type=ActivityType.FITNESS, pillar=Pillar.MOVEMENT,
                      facilitator={"role": "self", "id": "res-home"}, location="home",
                      remote_capable=False, frequency=Frequency(0, "week"), backups=[],
                      load=Load(intensity=Intensity.LOW, score=2)),
    ]
    tasks = schedule(plan, avail, start_date, days=7)
    assert any(t.substituted_from == "sauna" for t in tasks)


def test_no_two_high_intensity_sessions_same_day(availability, start_date):
    plan = [
        make_activity(id="hiit", name="HIIT", frequency=Frequency(7, "week"),
                      load=Load(intensity=Intensity.HIGH, score=9), remote_capable=True, backups=[]),
        make_activity(id="lift", name="Strength", frequency=Frequency(7, "week"),
                      load=Load(intensity=Intensity.HIGH, score=8), remote_capable=True, backups=[]),
    ]
    tasks = schedule(plan, availability, start_date, days=7)
    by_day = {}
    for t in tasks:
        by_day.setdefault(t.start.date(), []).append(t)
    for d, ts in by_day.items():
        highs = [t for t in ts if t.activity_id in ("hiit", "lift")]
        assert len(highs) <= 1, f"two hard sessions on {d}"


def test_daily_training_load_is_capped(availability, start_date):
    # a hard lift (8) and a long ride (6) can't share a day (14 > the 10 budget) → they spread out
    plan = [
        make_activity(id="lift", name="Strength", frequency=Frequency(4, "week"),
                      load=Load(intensity=Intensity.HIGH, score=8), remote_capable=True, backups=[]),
        make_activity(id="ride", name="Long ride", frequency=Frequency(3, "week"),
                      load=Load(intensity=Intensity.MODERATE, score=6), remote_capable=True, backups=[]),
    ]
    tasks = schedule(plan, availability, start_date, days=21)
    score = {"lift": 8, "ride": 6}
    daily = {}
    for t in tasks:
        daily[t.start.date()] = daily.get(t.start.date(), 0) + score.get(t.activity_id, 0)
    assert daily and max(daily.values()) <= 10, f"a day exceeds the training-load budget: {daily}"


def test_priority_respected_under_contention(availability, start_date):
    # two activities, same single resource, only fits one in-person → higher priority wins it
    high = make_activity(id="high", name="Physician", type=ActivityType.CONSULTATION,
                         pillar=Pillar.DIAGNOSTICS, priority=1,
                         facilitator={"role": "trainer", "id": "res-trainer"},
                         remote_capable=False, frequency=Frequency(7, "week"), backups=[])
    low = make_activity(id="low", name="Optional", type=ActivityType.CONSULTATION,
                        pillar=Pillar.MIND, priority=99,
                        facilitator={"role": "trainer", "id": "res-trainer"},
                        remote_capable=False, frequency=Frequency(7, "week"), backups=[])
    tasks = schedule([high, low], availability, start_date, days=7)
    high_inperson = [t for t in tasks if t.activity_id == "high" and t.mode is Mode.IN_PERSON]
    assert high_inperson, "highest-priority activity should secure the contended resource"


# --- Whole-plan invariants (run against the real build_tasks output) -------------

@pytest.fixture(scope="module")
def real_plan():
    from elyx_allocator.pipeline import build_tasks, build_plan
    plan, _, _ = build_plan()
    return plan, build_tasks()


def test_meals_anchored_at_fixed_times(real_plan):
    """Lunch 13:00 and dinner 19:00 are fixed anchors; breakfast defaults to 08:00
    (it may sit later on the rare day with a morning fasted test — see the fasted test)."""
    from elyx_allocator.pipeline import build_catalog
    from elyx_allocator.models import MealRelation, ActivityType
    _, tasks = real_plan
    cat = {a.id: a for a in build_catalog()}
    fasted_days = {t.start.date() for t in tasks
                   if (a := cat.get(t.activity_id)) and a.type != ActivityType.MEDICATION
                   and a.circadian.meal_relation in (MealRelation.FASTED, MealRelation.EMPTY_STOMACH)}
    exact = {"act-protein-forward-lunch": (13, 0), "act-protein-forward-dinner": (19, 0)}
    for t in tasks:
        if t.activity_id in exact:
            assert (t.start.hour, t.start.minute) == exact[t.activity_id], \
                f"{t.activity_id} at {t.start.time()}"
        if t.activity_id == "act-protein-forward-breakfast":
            # never before the 08:00 anchor, always in the morning (after any fasted test)
            assert 8 <= t.start.hour < 12, f"breakfast at {t.start.time()} out of morning band"


def test_no_meal_before_a_fasted_test(real_plan):
    """You don't eat before a fasted test: no meal starts before a same-day fasted test."""
    from elyx_allocator.pipeline import build_catalog
    from elyx_allocator.models import MealRelation, ActivityType
    _, tasks = real_plan
    cat = {a.id: a for a in build_catalog()}
    is_meal = lambda t: (cat.get(t.activity_id) and cat[t.activity_id].type == ActivityType.FOOD
                         and not cat[t.activity_id].all_day)
    fasted = [t for t in tasks if (a := cat.get(t.activity_id))
              and a.type != ActivityType.MEDICATION
              and a.circadian.meal_relation in (MealRelation.FASTED, MealRelation.EMPTY_STOMACH)]
    assert fasted, "expected fasted tests in the plan (bloods/DEXA)"
    for ft in fasted:
        same_day_meals = [t for t in tasks if is_meal(t) and t.start.date() == ft.start.date()]
        for m in same_day_meals:
            assert m.start >= ft.end, \
                f"{m.title} {m.start.time()} eaten before fasted {ft.title} {ft.start.time()}"


def test_at_most_one_fitness_per_half_day(real_plan):
    """No two fitness sessions in the same half-day (noon split); <=2 fitness/day total."""
    from elyx_allocator.pipeline import build_catalog
    from elyx_allocator.models import ActivityType
    _, tasks = real_plan
    cat = {a.id: a for a in build_catalog()}
    is_fit = lambda t: cat.get(t.activity_id) and cat[t.activity_id].type == ActivityType.FITNESS \
        and not cat[t.activity_id].all_day
    by_day = {}
    for t in tasks:
        if is_fit(t):
            by_day.setdefault(t.start.date(), []).append(t)
    for d, ts in by_day.items():
        parts = [("am" if t.start.hour < 12 else "pm") for t in ts]
        assert len(parts) == len(set(parts)), \
            f"{d}: two fitness in the same half-day — {[(t.title, t.start.time()) for t in ts]}"
        assert len(ts) <= 2, f"{d}: {len(ts)} fitness sessions (>2)"


def test_daily_fitness_time_capped(real_plan):
    """Total fitness minutes/day (sessions with score>=2) stays within the 90-min budget.
    Score-1 micro-work (eye exercises, foam rolling) is free and doesn't count."""
    from elyx_allocator.pipeline import build_catalog
    from elyx_allocator.models import ActivityType
    _, tasks = real_plan
    cat = {a.id: a for a in build_catalog()}
    by_day = {}
    for t in tasks:
        a = cat.get(t.activity_id)
        if a and a.type == ActivityType.FITNESS and not a.all_day and a.load.score >= 2:
            by_day[t.start.date()] = by_day.get(t.start.date(), 0) + a.duration_min
    assert by_day, "expected fitness sessions in the plan"
    worst = max(by_day.values())
    assert worst <= 90, f"a day has {worst} min of fitness (> 90-min budget)"


def test_sunday_is_active_rest(real_plan):
    """No moderate+ fitness on Sundays; easy/recovery only."""
    from elyx_allocator.pipeline import build_catalog
    from elyx_allocator.models import ActivityType
    from elyx_allocator.scheduler import _INTENSITY_RANK
    _, tasks = real_plan
    cat = {a.id: a for a in build_catalog()}
    for t in tasks:
        a = cat.get(t.activity_id)
        if a and a.type == ActivityType.FITNESS and t.start.weekday() == 6:
            assert _INTENSITY_RANK.get(a.load.intensity, 0) < 2, \
                f"moderate+ fitness on Sunday {t.start.date()}: {t.title}"


def test_daily_meals_present_every_day(real_plan):
    """Meals are daily anchors — they must appear on every one of the 90 days.
    (Regression: the member-as-resource constraint must shift a meal off a blocked
    window, never drop it.)"""
    from collections import Counter
    _, tasks = real_plan
    c = Counter(t.activity_id for t in tasks)
    for meal in ("act-protein-forward-breakfast", "act-protein-forward-lunch",
                 "act-protein-forward-dinner"):
        assert c[meal] == 90, f"{meal} appears {c[meal]}/90 days — a daily meal was dropped"


def test_venue_sessions_not_before_7am(real_plan):
    """The day starts 06:30; in-person sessions at a venue (not home) start no earlier
    than 07:00 — time to get ready and travel. Home/self sessions may start 06:30."""
    from elyx_allocator.models import Mode
    _, tasks = real_plan
    for t in tasks:
        if t.mode is Mode.IN_PERSON and "res-home" not in t.resources and t.resources:
            assert t.start.hour * 60 + t.start.minute >= 7 * 60, \
                f"{t.title} at a venue starts {t.start.time()} (< 07:00)"


def test_no_inperson_session_during_work_hours(real_plan):
    """Weekday core hours 09:00–17:30 are protected: no in-person session (meals exempt,
    remote exempt) may overlap them. The member works."""
    from elyx_allocator.pipeline import build_catalog
    from elyx_allocator.models import ActivityType, Mode
    from datetime import time
    _, tasks = real_plan
    cat = {a.id: a for a in build_catalog()}
    for t in tasks:
        a = cat.get(t.activity_id)
        if not a or a.all_day or a.type == ActivityType.FOOD or t.mode is not Mode.IN_PERSON:
            continue
        if t.start.weekday() < 5:
            overlaps = t.start.time() < time(17, 30) and time(9, 0) < t.end.time()
            assert not overlaps, f"{t.title} {t.start:%a %H:%M}–{t.end:%H:%M} inside work hours"


def test_resources_within_operating_hours(real_plan):
    """Every booked resource is used only within its real operating hours."""
    from datetime import time
    plan, tasks = real_plan
    from elyx_allocator.pipeline import build_availability
    from datetime import date as _date
    res = build_availability(_date(2026, 6, 1)).resources
    def hhmm(s):
        h, m = s.split(":"); return time(int(h), int(m))
    for t in tasks:
        for rid in t.resources:
            r = res.get(rid)
            if not r:
                continue
            oh = r.operating_hours.get(t.start.weekday())
            assert oh, f"{t.title} books {rid} on a day it's closed ({t.start:%a})"
            assert hhmm(oh[0]) <= t.start.time() and t.end.time() <= hhmm(oh[1]), \
                f"{t.title} at {t.start.time()} outside {rid} hours {oh}"


def test_member_not_double_booked(real_plan):
    """The member is one person: two body-occupying activities can't overlap in time.
    Supplements/medication piggyback on meals (taken together), so they're exempt."""
    from elyx_allocator.pipeline import build_catalog
    _, tasks = real_plan
    cat = {a.id: a for a in build_catalog()}

    def occupies(t):
        a = cat.get(t.activity_id)
        return a is not None and a.type != ActivityType.MEDICATION and not a.all_day

    by_day = {}
    for t in tasks:
        if occupies(t):
            by_day.setdefault(t.start.date(), []).append(t)
    for d, ts in by_day.items():
        ts.sort(key=lambda x: x.start)
        for i in range(1, len(ts)):
            assert ts[i].start >= ts[i - 1].end, (
                f"member double-booked on {d}: "
                f"{ts[i-1].title} {ts[i-1].start.time()}–{ts[i-1].end.time()} "
                f"overlaps {ts[i].title} at {ts[i].start.time()}")


def test_all_day_guardrail_not_timed_or_booked(availability, start_date):
    """Standing daily rules (no caffeine after 2pm, hydration) are all-day guardrails:
    they appear every day, book no resource, carry no training load, and aren't pinned
    to a misleading clock time."""
    plan = [make_activity(
        id="caffeine", name="No caffeine after 2pm", type=ActivityType.FOOD,
        pillar=Pillar.NUTRITION, facilitator={"role": "self", "id": "res-home"},
        location="res-home", remote_capable=True, frequency=Frequency(1, "day"),
        all_day=True, travel_behavior=TravelBehavior.CONTINUE, backups=[],
        load=Load(intensity=Intensity.NONE, score=0))]
    tasks = schedule(plan, availability, start_date, days=7)
    g = [t for t in tasks if t.activity_id == "caffeine"]
    assert len(g) == 7, "a daily guardrail should appear on every day"
    assert all(t.detail.get("all_day") for t in g), "guardrail tasks must be flagged all_day"
    assert all(t.resources == [] for t in g), "a guardrail must not book any resource"
    # one per calendar day, not stacked
    assert len({t.start.date() for t in g}) == 7


def test_every_action_plan_activity_appears(real_plan):
    """No prescribed activity may vanish: each is placed or substituted at least once."""
    plan, tasks = real_plan
    placed = {t.activity_id for t in tasks}
    substituted = {t.substituted_from for t in tasks if t.substituted_from}
    covered = placed | substituted
    missing = [a.id for a in plan if a.id not in covered]
    assert not missing, f"action-plan activities silently dropped: {missing}"


def test_no_duplicate_placements(real_plan):
    """The same activity must never be placed twice at the exact same start time."""
    from collections import Counter
    _, tasks = real_plan
    pairs = Counter((t.activity_id, t.start) for t in tasks)
    dups = {k: v for k, v in pairs.items() if v > 1}
    assert not dups, f"exact-duplicate placements: {dups}"


def test_no_activity_twice_same_day(real_plan):
    """No activity appears more than once on a calendar day (none are multi-per-day)."""
    from collections import Counter
    _, tasks = real_plan
    per_day = Counter((t.activity_id, t.start.date()) for t in tasks)
    repeats = {k: v for k, v in per_day.items() if v > 1}
    assert not repeats, f"activity scheduled multiple times same day: {repeats}"


def test_daily_training_load_realistic(real_plan):
    """Training load (moderate+ only) stays within the budget and isn't pinned at the cap.

    Recovery (sauna, cold plunge) and mind work (breathwork) must NOT count as training load —
    if they did, every day saturates the cap, which is what the bug looked like.
    """
    from elyx_allocator.scheduler import _INTENSITY_RANK
    plan, tasks = real_plan
    train = {a.id: (a.load.score if _INTENSITY_RANK.get(a.load.intensity, 0) >= 2 else 0)
             for a in plan}
    daily = {}
    for t in tasks:
        daily[t.start.date()] = daily.get(t.start.date(), 0) + train.get(t.activity_id, 0)
    vals = list(daily.values())
    assert max(vals) <= 10, f"a day exceeds the training-load budget: max={max(vals)}"
    pinned = sum(1 for v in vals if v >= 10)
    assert pinned < len(vals) * 0.5, \
        f"{pinned}/{len(vals)} days pinned at the cap — recovery likely counted as training"
