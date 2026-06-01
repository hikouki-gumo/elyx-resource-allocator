"""Wire the pieces: action plan + availability → schedule → rendered site.

build_plan()  → (plan, availability, start)
build_site(d) → writes <d>/index.html and <d>/plan.ics, returns the html Path
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .catalog import build_action_plan, build_availability, build_catalog
from .scheduler import schedule
from .render import render_html, render_ics

MEMBER = "A-1042"
START = date(2026, 6, 1)
HORIZON_DAYS = 90


def build_plan():
    plan = build_action_plan()
    availability = build_availability(START)
    return plan, availability, START


def build_tasks():
    plan, availability, start = build_plan()
    return schedule(plan, availability, start, days=HORIZON_DAYS, catalog=build_catalog())


def build_site(out_dir) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    plan, availability, start = build_plan()
    tasks = schedule(plan, availability, start, days=HORIZON_DAYS, catalog=build_catalog())
    trips = [(t.start, t.end, t.destination) for t in availability.travel]
    (out / "index.html").write_text(
        render_html(tasks, member=MEMBER, start=start, travel=trips), encoding="utf-8")
    (out / "plan.ics").write_text(render_ics(tasks), encoding="utf-8")
    return out / "index.html"
