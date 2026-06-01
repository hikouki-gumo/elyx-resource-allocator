"""Integration tests — full pipeline plan→schedule→render (no browser)."""
from datetime import date
from icalendar import Calendar

from elyx_allocator.models import Frequency, Mode, ActivityType, Pillar, TravelBehavior
from elyx_allocator.scheduler import schedule
from elyx_allocator.render import render_html, render_ics, build_view_model
from tests.conftest import make_activity


def test_render_html_contains_events_and_reasons(availability, start_date):
    plan = [make_activity(id="a1", name="Zone-2 cardio", frequency=Frequency(3, "week"),
                          remote_capable=True)]
    tasks = schedule(plan, availability, start_date, days=14)
    html = render_html(tasks, member="A-1042", start=start_date)
    assert "Zone-2 cardio" in html
    assert 'data-testid="event"' in html
    # at least one reason string is present
    assert any(t.reason and t.reason in html for t in tasks)


def test_remote_task_does_not_show_fixed_location(availability_with_travel, start_date):
    """A session taken remotely must not display its fixed in-person location (e.g. Clinic)."""
    plan = [make_activity(
        id="consult", name="Physician review", type=ActivityType.CONSULTATION,
        pillar=Pillar.DIAGNOSTICS, facilitator={"role": "physician", "id": "res-physician"},
        location="res-clinic", remote_capable=True, frequency=Frequency(7, "week"),
        travel_behavior=TravelBehavior.REMOTE, backups=[])]
    tasks = schedule(plan, availability_with_travel, start_date, days=21)
    remote = [t for t in tasks if t.mode is Mode.REMOTE]
    assert remote, "expected at least one remote occurrence"
    vm = build_view_model(tasks, member="A-1042", start=start_date)
    items = [it for wk in vm["weeks"] for day in wk["days"] for it in day["items"]]
    remote_items = [it for it in items if it["mode"] == "remote"]
    assert remote_items
    for it in remote_items:
        assert it["location"] != "Clinic", "remote session shows its fixed clinic location"
        assert it["location"].lower() == "remote", f"remote location should read 'Remote', got {it['location']!r}"


def test_all_day_guardrail_renders_without_clock_time(availability, start_date):
    """An all-day guardrail must show 'All day', never a misleading clock time like 12:00."""
    from elyx_allocator.models import Intensity, Load
    plan = [make_activity(
        id="caffeine", name="No caffeine after 2pm", type=ActivityType.FOOD,
        pillar=Pillar.NUTRITION, facilitator={"role": "self", "id": "res-home"},
        location="res-home", remote_capable=True, frequency=Frequency(1, "day"),
        all_day=True, travel_behavior=TravelBehavior.CONTINUE, backups=[],
        load=Load(intensity=Intensity.NONE, score=0))]
    tasks = schedule(plan, availability, start_date, days=7)
    vm = build_view_model(tasks, member="A-1042", start=start_date)
    items = [it for wk in vm["weeks"] for day in wk["days"] for it in day["items"]]
    guards = [it for it in items if it["title"] == "No caffeine after 2pm"]
    assert guards
    for it in guards:
        assert it["all_day"] is True
        assert it["t"] == "All day", f"guardrail showed a clock time: {it['t']!r}"


def test_render_ics_is_valid_and_complete(availability, start_date):
    plan = [make_activity(id="a1", name="Zone-2 cardio", frequency=Frequency(3, "week"),
                          remote_capable=True)]
    tasks = schedule(plan, availability, start_date, days=14)
    ics = render_ics(tasks)
    cal = Calendar.from_ical(ics)
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(events) == len(tasks)
    assert all(e.get("dtstart") is not None for e in events)
