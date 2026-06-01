# Elyx Resource Allocator

A simple implementation of the **Resource Allocator** node from Elyx's
["Operating System for Proactive Healthcare"](https://360.elyx.life). It turns a
HealthSpan-AI **action plan** (priority-ordered health activities) plus a
**resource-availability snapshot** into a personalized, conflict-resolved
**90-day plan**, rendered as a readable interactive calendar (+ `.ics`).

> Position in the OS: `Recommender → Action Plan ─┐`
> `Availability + calendar + body rules ─┼→ [Resource Allocator] → Proposed Plan → Brain Hacker AI`
> It is a **stateless transform**. Booking, tracking and analytics live downstream
> (Brain Hacker AI → Personalized UX). We emit a *proposed plan*, not confirmed bookings.

## What it does

- **Member persona:** a 35–55 founder/exec, travels ~1 week/month across time
  zones, sleep + stress are the real problems, trains inconsistently. Realism =
  the week a world-class coach + physician would actually design.
- **Intelligence in the data:** each activity carries the coach's reasoning —
  circadian window, training load, meal relation, travel behavior, backups — so
  the scheduler stays a simple greedy pass and still produces a coachable week.
- **Smart behaviors:** priority-first placement, protected sleep window, fixed
  meal anchors (08:00 / 13:00 / 19:00, placed first), two daily budgets —
  **LOAD** (moderate+ ≤ 10/day, intensity) and **TIME** (≤ 90 fitness-min/day,
  volume) — fitness spread across the day (≤ 1 per half, ≤ 2/day, AM + PM),
  **protected work hours** (09:00–17:30 weekday; train 06:30–08:00 & 17:30–19:00),
  **Sunday = active rest** (no moderate+; Saturday trains), travel weeks →
  remote / backup / skip-and-adjust, scarce resources booked ahead, every task
  carries a one-line *reason*.
- **Standing rules as all-day guardrails:** continuous daily rules (no caffeine
  after 2pm, hydration, eating window) render in an all-day lane, not as a
  misleading 12:00 slot. Remote sessions show "Remote", not their fixed venue.

## Why a deterministic scheduler (not an AI scheduler)

The placement is a **deterministic greedy** pass, not an LLM. The node's worth is its
**invariants** — no double-booking, sleep never raided, ≤1 hard session/day, travel→backup,
priority order — which must be *guaranteed and unit-tested* (an LLM is stochastic and can't be).
In a health context every slot must be provably valid and explainable. So the **judgment lives in
the data** (each activity carries circadian/load/travel) and placement stays mechanical,
instant, and offline. The AI lives *around* this node: upstream (the Recommender decides *what* to
do) and downstream (Brain Hacker AI handles personalization + the real-time booking negotiation).
See §11 of the design spec for the full rationale.

## Architecture

```
catalog.py ─ generate_data.py ─ validate.py ─ scheduler.py ─ render.py ─ pipeline.py
 (108 acts)   (writes JSON)      (realism gate) (greedy core)  (HTML+ICS)  (build_site)
```

| Module | Responsibility |
|--------|----------------|
| `models.py` | enums + dataclasses (the type spine) |
| `catalog.py` | the real Elyx catalog (108 activities) + clinic resources + member availability |
| `generate_data.py` | writes `data/activities.json` + `data/availability.json`, gated by the validator |
| `validate.py` | the realism gate — 4 rules (coherence, referential integrity, variety, distribution) |
| `scheduler.py` | greedy priority-first allocator (sleep/work/meal canvas + load & time budgets + travel-patch) |
| `render.py` | the member-facing dashboard (HTML) + `.ics` |
| `pipeline.py` | wires plan + availability → schedule → site |

## Deliverables

| # | Deliverable | Location |
|---|-------------|----------|
| 1 | ≥100 sample activities | `data/activities.json` (108) |
| 2 | 3-month availability data | `data/availability.json` |
| 3 | Scheduler | `src/elyx_allocator/scheduler.py` |
| 4 | Readable calendar output | `web/out/index.html` (interactive) + `web/out/plan.ics` |
| 5 | Hosted on the internet | Vercel (see below) |
| 6 | Prompts used | `PROMPTS.md` |

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install jinja2 icalendar pytest pytest-playwright && playwright install chromium

# generate + validate the sample data (writes data/*.json)
PYTHONPATH=src python -m elyx_allocator.generate_data

# build the calendar site (writes web/out/index.html + plan.ics)
PYTHONPATH=src python -c "from elyx_allocator.pipeline import build_site; build_site('web/out')"
open web/out/index.html
```

## Tests (double-loop TDD)

```bash
pytest -m "not e2e"   # unit + integration
pytest -m e2e         # Playwright E2E (drives the rendered dashboard)
pytest                # all 48
```

- **Unit** — model shape, the realism gate, and scheduler invariants
  (no double-booking, member not double-booked, priority order, protected sleep,
  protected work hours, load + time caps, half-day fitness spread, Sunday rest,
  meals after fasted tests, travel→remote, backup substitution).
- **Integration** — plan → schedule → render HTML/ICS content.
- **E2E** — Playwright loads the dashboard and verifies event→reason drawer,
  back navigation, month toggle, pillar filtering, and milestone clicks.

## Hosting

**Live demo:** https://elyx-resource-allocator.vercel.app

The output is a self-contained static site (`web/out/` — one HTML file + one `.ics`).
The deployed build is pushed directly:

```bash
# rebuild the data + site, then deploy the prebuilt static folder
PYTHONPATH=src python -m elyx_allocator.generate_data
PYTHONPATH=src python -c "from elyx_allocator.pipeline import build_site; build_site('web/out')"
cd web/out && npx vercel deploy --prod
```

(`vercel.json` can also build on Vercel's side, but deploying the prebuilt folder
avoids installing the Python deps in Vercel's build container.)

### Why Vercel static (not a production deployment)

This is a **demo of one node**, not a service to operate, so the hosting matches the
scope deliberately:

- **It's a static artifact.** The Resource Allocator is a deterministic, offline
  transform — it emits one HTML calendar + one `.ics`. There's no backend, no
  database, no auth, no live booking. A CDN serving static files is exactly the
  right shape; a containerized app server / managed DB / IaC pipeline would be
  theatre around a folder of files.
- **Zero maintenance, free, stable.** Static files on Vercel's CDN don't sleep,
  cold-start, or expire; the free tier's limits dwarf demo traffic.
- **Production hosting would live elsewhere anyway.** In the real Elyx OS this node
  is internal plumbing between HealthSpan-AI (upstream) and Brain Hacker AI
  (downstream) — it would ship as a library/service inside that platform's own
  infra, not as a public website. Hosting the *demo* on production-grade
  infrastructure wouldn't reflect how the node is actually deployed.

Trade-off accepted: redeploys are a manual `vercel deploy` of the rebuilt folder
(no CI/CD on git push). Fine for a demo; a real service would wire the build into a
pipeline.

## Design

The approved UI direction and the design spec live in `docs/`:
`docs/superpowers/specs/resource-allocator-design.md` and
`docs/mockups/` (current screenshots: `current-week.png`, `current-month.png`, `current-event.png`, `current-sidebar-collapsed.png`).
