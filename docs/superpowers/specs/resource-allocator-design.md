# Resource Allocator — design spec

**status:** built (48 tests green) · **assignment:** `Assignment.pdf` (repo root)

> This document describes the system **as built** — a single current-state spec, not a change log.

---

## 1. Context & purpose

Elyx is a Singapore concierge longevity service ($150k/yr, UHNW members). Its platform — "The Operating System for Proactive Healthcare" (360.elyx.life) — turns AI health recommendations into coordinated action.

This project implements **a simple version of the Resource Allocator node** from that OS.

**Position in the OS stack:**
```
Recommender → action plan ─┐
availability snapshot ──────┤→ [Resource Allocator] → proposed plan → Brain Hacker AI
calendar / travel / sleep ──┘   stateless, single-pass        (books it for real,
body load / recovery rules ─┘   smart-data + greedy            tracks behaviour)
```

The Resource Allocator is a **stateless transform**: it takes a priority-ordered action plan plus a resource-availability snapshot and emits a **proposed personalized 90-day plan** — recommended slot, resource, and mode for each activity.

### Scope boundary (locked)

**In scope:** schedule generation, conflict-aware placement, calendar + ICS output, sample data, hosting.

**Out of scope** (belongs downstream to Brain Hacker AI — *Resource Allocator plan + client preferences → personalized UX + tailored communication*):
- activity tracking, analytics, behaviour feedback loop
- real-time booking, slot locking, concurrency / race conditions
- transactional confirmation / rebooking on rejection

Availability is read as a **known snapshot** (operating hours, capacity). We emit a *proposed plan*, not confirmed bookings; the model carries empty `status`/`metrics` slots for the downstream node to fill.

---

## 2. The member (persona driving all "realism")

A single member profile drives the data:
- **35–55**, founder / C-suite / fund principal / family-office head; globally mobile
- **travels ~1 week/month** across time zones (trips over the 90-day horizon)
- **sleep and stress are the real problems**; trains but inconsistently because of the calendar
- works core weekday hours; wants to **be told what to do**, not handed options
- time-poor, premium expectations, data-driven (wearables)

Realism = **the week a world-class coach + physician would design for this person** — safe, effective, and *livable around a working life* — not a legal slotting of activities into open time.

---

## 3. Data model (`models.py`)

Dates/times: ISO 8601, Asia/Singapore home weeks; travel weeks carry the trip timezone.

### 3.1 Activity (catalog item / action-plan entry)

Grounded in the real Elyx catalog. The dataset is a **catalog of 108 distinct activities**; a member's **action plan is a priority-ordered subset (~30)**.

The 10 assignment fields:
- `id`, `name`
- `type` ∈ {fitness, food, medication, therapy, consultation}
- `frequency` `{times, period}` (e.g. 3/week)
- `details` — concrete coaching info (HR zones, dosages, protocols); never just echoes the name
- `facilitator` `{role, id?}` — **always a person or "self"** (see 3.2)
- `location` — the bookable place (equipment lives here)
- `remote_capable` (bool)
- `prep` `{description, lead_time_min}` — *advance preparation the scheduler must account for*, not a recipe
- `backups` `[activity_id]` — same-pillar substitutes
- `skip_adjustment` `Optional[str]` — what to do if it can't happen; `None` when there's nothing to make up
- `metrics` `[name]` — carried, unfilled (downstream consumes)

Coach-reasoning fields (added — *why* a placement happens):
- `pillar` ∈ {diagnostics, movement, nutrition, sleep, mind, meds/supplements, therapies}
- `priority` (rank — health importance; lower = more important)
- `circadian` `{window: any|morning|midday|evening|before_bed, meal_relation: none|with_food|with_fat|fasted|empty_stomach}`
- `load` `{intensity: none|low|moderate|high, score: 0–9}`
- `min_gap_hours`, `duration_min`
- `travel_behavior` ∈ {continue, remote, backup, skip}
- `all_day` (bool) — a **standing daily guardrail** (a rule that governs the whole day, e.g. "no caffeine after 2pm", hydration), not a timed slot

Load score bands: **easy 1–3**, **moderate 4–6**, **hard 7–9** (none/0 = meals, supplements, guardrails).

### 3.2 Facilitator vs. location

A `facilitator` is always a **person** — trainer, coach, physio, dietitian, psychologist, physician, sports-medicine, **recovery technician** (sauna/cryo/HBOT/red-light), **lab technician** (DEXA/VO₂/bloods) — or **self** (member, unsupervised, `id=None`). **Equipment belongs to the location**: the location is the bookable `Resource` carrying capacity + operating hours (Gym, Clinic, Sauna suite, DEXA suite, …). The scheduler books the facilitator (if any) **and** the location.

### 3.3 Resource & availability snapshot (3 months)

Tiered by what *actually* limits each resource. The member pays for white-glove access, so Elyx-owned facilities are deliberately generous — the real friction is the member's own life (work, travel, sleep), not clinic scarcity. The only genuinely scarce resources are rare *visiting humans*.

| tier | resources | what limits it |
|------|-----------|----------------|
| abundant | supplements, home/bodyweight, wearable-measured items | nothing — always available |
| broad | gym, clinic, sauna, pool, red-light | ample capacity, wide hours |
| moderate | physio, dietitian, coach, psychologist | regular staff on working hours, often remote |
| scarce | **visiting** physician (Mon/Wed/Fri), sports-medicine fellow (Tue), lab technician | a rare human's schedule (1–3 days/week) |
| single-unit | DEXA, cryo, HBOT, VO₂ lab, **blood draw room** | one owned machine — capacity 1, but open daily/long hours |

Rule of thumb: **Elyx-owned equipment = `single-unit`** (limit is the machine); **rare people = `scarce`** (limit is their schedule).

`Resource`: `{id, type (human|location), tier, capacity, operating_hours (per weekday), booked_windows[], remote_offered, label}`. Hours (white-glove): home/self 05:30–22:30; **clinic 06:00–22:00, 7 days**; **owned labs/machines (DEXA, VO₂, HBOT, blood, cryo) daily 06:00–20:00/22:00**. Genuine scarcity is carried only by the visiting specialists' day-limited schedules.

`Availability`: `{resources, travel: [TravelTrip], commitments}`.
`TravelTrip`: `{start, end, destination, timezone}` — trips block in-person clinic/local; remote persists.
`ClientCommitments`: `{sleep window (never raided), work_blocks (Mon–Fri 09:00–18:00, protected), meals [08:00, 13:00, 19:00]}`.

### 3.4 ScheduledTask (output)

`{activity_id, start, end, mode: in_person|remote, resources: [resource_id], substituted_from?, reason, note?, title, detail (full Activity schema for the drawer), load (intensity rank 0–3)}`.

`reason` is a one-line human explanation ("morning slot, fasted") for the demo + downstream tailored communication. There are **no "skipped" placeholder rows** — an occurrence that can't happen is substituted by a backup or omitted, never rendered as a ghost.

---

## 4. The scheduler (`scheduler.py`)

A coach designs a repeating rhythm, then adapts it. The algorithm mirrors that: **deterministic, greedy, priority-first, single pass** over the 90-day horizon. The judgment lives in the data; the placer enforces constraints.

### Running state
`bookings[resource]` (capacity-aware), `member_busy` (the member is one person), `day_load[date]` (moderate+ score sum), `day_fit_min[date]` (fitness minutes, score ≥ 2), `fitness_part[date]` (am/pm halves used), `placed_on[activity]` (once-per-day guard).

### Phase 0 — canvas (fixed rhythm, placed first)
1. **Sleep** window and **weekday work blocks (09:00–17:30)** are protected — nothing in-person lands inside them (meals and remote sessions exempt).
2. **Lunch (13:00) and dinner (19:00)** are anchored every day, reserving the member's time so everything else fits around them. (Breakfast waits for Phase 2.)

### Phase 1 — main pass
Activities sorted by `priority`; each frequency expanded into staggered day-offsets (a stable per-activity phase spreads rare diagnostics across the horizon). Per occurrence on day `d`:

- **All-day guardrail** → emit one untimed entry (no clock time, no booking, no load).
- **Travel day** → apply `travel_behavior`: remote / backup / skip / continue.
- **Fitness** → three gates decide the day, the half-day decides the time:
  - **LOAD** ≤ 10 (sum of moderate+ scores); **Sunday** blocks all moderate+ (active rest); Saturday trains.
  - **TIME** ≤ 90 fitness-minutes/day (sessions with score ≥ 2; easy score-1 micro-work is free).
  - **HALF-DAY**: ≤ 1 fitness per half (noon split). 1st in its natural window (06:30–08:00 or 17:30–19:00); a 2nd relocates to the other window; a 3rd shifts to another day.
  - All fitness — in-person, remote, travel, backup — routes through one gated helper so the caps can't be bypassed.
- **Everything else** (therapy, consultation, supplements, snacks) → place in its `circadian` window, honouring: protected work hours, member-free, resource operating hours + capacity, once-per-day. If the window is blocked, scan the waking day for a valid slot; otherwise **remote → backup → nearby-open-day shift → omit**.

The member **wakes at 06:30**. Home/self sessions can start then, but an **in-person session at a venue** (clinic, gym, lab, outdoors…) starts **no earlier than 07:00** — time to get ready and travel. Remote-from-home is exempt.

### Phase 2 — breakfast
Placed last so it lands **after any morning fasted test** that day (you don't eat before fasted bloods/DEXA) and never overlaps a session already there. Prefers the 08:00 anchor; on a fasted-test morning it slides to just after the test.

### Per-occurrence fallback chain
`preferred slot → alternate time same day → remote (if capable) → backup activity → omit`. No "skipped" placeholder is ever emitted.

### Two daily budgets, distinct jobs
- **LOAD** caps *intensity* (moderate+ ≤ 10/day) — stops two hard, hard+moderate, or heavy moderate pairs.
- **TIME** caps *volume* (≤ 90 fitness-min/day) — catches the low-intensity pile-up LOAD can't see (a 115-min easy-cardio + mobility morning).
- **Work hours + meal anchors + half-day spread** shape *when* — train 06:30–08:00 and 17:30–19:00; meals fixed (±30 min to resolve a conflict).

Properties: greedy, priority-first, single-pass, deterministic, stateless across runs, explainable.

---

## 5. "Realistic" = a validator gate (`validate.py`)

A gate certifies the generated catalog. Pass all → `"realistic": true`. It doubles as the data test.

1. **Field coherence** — `type` aligns with facilitator role; physical therapies aren't remote-capable; `details` never just echoes `name`; fasted / empty-stomach activities declare `prep`.
2. **Referential integrity** — every facilitator id (if any) and location resolves to a resource; backups reference real activities.
3. **Variety** — ≥ 80% unique activity names (no clone spam).
4. **Distribution** — each of the 5 types is 10–40% of the catalog (a believable protocol mix).

---

## 6. Architecture & modules (Python)

```
catalog.py → generate_data.py → validate.py → scheduler.py → render.py → pipeline.py → Vercel
 (108 acts)   (writes JSON)      (realism gate) (greedy core)  (HTML+ICS)  (build_site)  (host)
```

| module | purpose |
|--------|---------|
| `models.py` | enums + dataclasses (the type spine) |
| `catalog.py` | the real Elyx catalog (108 activities) + clinic resources + member availability |
| `generate_data.py` | writes `data/activities.json` + `data/availability.json`, gated by the validator |
| `validate.py` | the realism gate (§5); also the data test |
| `scheduler.py` | the greedy allocator (§4) |
| `render.py` | the member-facing dashboard (HTML) + `.ics` |
| `pipeline.py` | wires plan + availability → schedule → site |

Deterministic over fixed data → pre-generate HTML + ICS at build, host static.

---

## 7. Output — interactive dashboard (`render.py`)

A single self-contained **interactive HTML dashboard** styled to the **elyx.life consumer brand** (warm `#EFEDEB` paper + grain, Cormorant Garamond + Work Sans + SF Mono, gold accent), plus a `.ics`.

- **Layout: collapsible left sidebar + central calendar.** The sidebar (☰ toggle) holds a scrollable, clickable **Upcoming milestones** list and **This-week** stats (activities / workouts / hard days / travel).
- **Week + Month** views; month cells show event rows + "+N more".
- **Toolbar:** sidebar toggle, week/month nav, **filters by the 5 activity types** (Fitness/Food/Medication/Therapy/Consultation). Event bars coloured by **type**; the 7-pillar value is shown in the drawer (an Elyx extension).
- **All-day guardrail lane** — a dashed "☼ All day" box atop each day for standing rules (hydration, no-caffeine).
- **Event drawer** — member-priority fields (empty ones hidden): details → location → duration → facilitator → preparation → backups (by name) → skip adjustment → metrics, with type/pillar/mode pills. Remote sessions show "Remote"; guardrails show "All day".
- **Travel** is trip-date-aware (✈ marker on travel weeks/days).
- Stable `data-testid` hooks for the E2E suite.

UI reference: `docs/mockups/current-*.png` (screenshots of the live generated app).

---

## 8. Testing (double-loop TDD) — 48 tests

Rather than discover issues reactively, the suite asserts **whole-plan invariants** against the real `build_tasks()` output, alongside unit/integration/E2E:

- **Correctness:** no resource double-booking, no member double-booking, nothing in the sleep window, **no in-person session inside weekday work hours**, every resource within its operating hours, no in-person clinic during travel, no `(activity, datetime)` duplicates.
- **Coverage:** every action-plan activity appears (placed or substituted) — nothing silently dropped.
- **Realism:** meals present every day; lunch 13:00 / dinner 19:00 exact; breakfast ≥ 08:00 and after any fasted test; ≤ 1 fitness per half-day; ≤ 90 fitness-min/day; no moderate+ on Sunday.
- **Files:** `test_models.py`, `test_validate.py`, `test_scheduler.py` (invariants = definition of done), `test_pipeline.py` (integration), `tests/e2e/test_dashboard.py` (Playwright).
- Run: `pytest` (all) · `pytest -m "not e2e"` (fast) · `pytest -m e2e`.

### Known simplifications (stated, not hidden)
- `min_gap_hours` (e.g. 48h between hard sessions) is carried in data but **not hard-enforced** — the load cap + half-day spread approximate it.
- **Therapy volume is uncapped** (only fitness has a time budget) — a morning can stack cardio + sauna + cold plunge.
- **Pairing rules** (sauna after training, cold plunge separate from hypertrophy) are not modelled — recovery order is left to the activity's circadian window.

---

## 9. Deliverables & hosting

| # | deliverable | location |
|---|-------------|----------|
| 1 | ≥100 activities | `data/activities.json` (108) |
| 2 | 3-month availability | `data/availability.json` |
| 3 | scheduler | `src/elyx_allocator/scheduler.py` |
| 4 | readable calendar | `web/out/index.html` + `web/out/plan.ics` |
| 5 | hosted on the internet | Vercel static (see README) |
| 6 | GitHub + prompts | repo + `PROMPTS.md` |

---

## 10. Decisions log

- **Stack:** Python · greedy scheduler · self-contained HTML dashboard + ICS · Vercel static.
- **Scheduler:** weekly-rhythm canvas + overlay + travel-patch (not day-by-day, not a solver).
- **"Simple":** intelligence in the data, simple greedy placement.
- **100+ activities:** catalog superset; action plan = priority subset.
- **Realism:** the week a great coach would build, livable around work; a validator gate enforces catalog coherence; scheduler invariants enforce the *scheduled day*.
- **Availability:** white-glove premium access; friction = the member's life + body + work, not clinic scarcity.
- **No booking / race conditions / tracking:** emits a *proposed plan*; those are downstream (Brain Hacker AI).

---

## 11. Why a deterministic scheduler (not an AI / LLM scheduler)

A **deterministic greedy** placer was chosen over an LLM/AI scheduler on purpose:

- **Testable correctness.** The node's value is its invariants (no double-booking, sleep never raided, work hours protected, travel→backup, priority order). Deterministic logic makes those reproducible and unit-testable (the 48 tests). An LLM is stochastic — same input → different output — so the invariants can't be guaranteed.
- **Safety + traceability.** In a health context every placement needs a guaranteed-valid slot and an explainable reason. An LLM can plausibly produce a slot that violates a hard rule; explicit code cannot.
- **Hard constraints, not fuzzy ones.** Operating hours, capacity, work blocks, fasting windows are exact — best enforced in code. The *judgment* lives in the **data** (each activity carries circadian/load/travel), so placement stays mechanical.
- **Cost / latency / reliability.** Runs instantly, offline, free, no API failure modes.
- **Architecture boundary.** The AI lives *around* this node: upstream the Recommender/HealthSpan AI decides *what* to do; downstream the Brain Hacker AI does personalization and the real-time booking negotiation. The Resource Allocator is the deterministic plumbing between them.

**Where an AI scheduler would earn its place** (future, not this node): global optimization over soft trade-offs (a CSP/ILP solver was considered and rejected as over-engineered for "simple"); natural-language replanning ("lighten this week"); and agent/human coordination for the actual booking handshake.
