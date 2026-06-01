# Prompts & AI-assisted process

This project was built with **Claude Code** (Opus 4.8). Per the assignment, this
documents the prompts and the GenAI-assisted workflow used.

## Tooling

- **Claude Code** (Opus 4.8) drove research, design, and the test-first implementation.
- **cmux** — ran Claude Code inside a terminal multiplexer so long agent sessions, the
  dev server, and the test/screenshot loops lived in parallel panes.
- **Self-review & refine loop** — work was iterated through review rounds rather than
  one-shot: an external code reviewer (Codex) plus the member's own pushback fed findings
  back in; each was evaluated against the codebase ("fight back" on the wrong ones, fix the
  real ones), then driven to green with a new failing test first. See *Review & realism
  prompts* below and `docs/scheduler-bugs.md`.
- **Skills used:** `brainstorming` (design), `writing-plans`, `test-driven-development`
  (double-loop TDD), `frontend-design` (the dashboard UI direction),
  `receiving-code-review` (evaluate-don't-obey discipline on review feedback).
- The **activity catalog** (`catalog.py`) was authored from the *real* Elyx menu
  surfaced during research (see below) rather than free-form generated, then run
  through the `validate.py` realism gate (108 activities, all rules pass).

## Research prompts (grounding "realistic")

1. "Read and understand Elyx business by scraping the home page: https://elyx.life/"
2. "Scrape from home page https://360.elyx.life/, understand all information."
3. "Focus on The Operating System for Proactive Healthcare, especially the diagram."
   → decoded the architecture SVG (HealthSpan AI → Resource Allocator → Brain Hacker AI).
4. "Read longevity.technology/clinics/longevity-clinics/elyx for product, pricing, target client."
   → $150k/yr, UHNW exec persona; real catalog (VO₂max, DEXA, cryo, HBOT, red-light, sauna,
   supplements, Zone-2, strength), real facilitators (physician, physio, dietitian, psychologist,
   sports-med), 7 pillars.

## Design prompts (brainstorming → spec → UI)

- Scope boundary: "Resource Allocator emits a *plan*, not bookings — tracking/analytics
  and booking race-conditions belong to Brain Hacker AI (Personalized UX)."
- Realism, framed as product: "think like a real product, care about client need" — led to
  encoding the coach's reasoning (circadian fit, load budget, pairing, travel behavior) in the
  data so a simple scheduler yields a coach-quality week.
- "≥100 activities" interpreted as a **catalog** superset; the action plan is a priority subset.
- Availability friction: "reasonable and generous — the client pays a lot" → white-glove access;
  friction is the member's life + body, not a stingy clinic; wearable-measurable items abundant.
- UI: "interactive single-screen dashboard, details on click" + "adapt the elyx.life style"
  (light `#EFEDEB`, Cormorant Garamond + Work Sans, gold accent). Refined via:
  milestones clickable, pillar filters, week/month toggle, event→reason drawer with back-nav.

## Build prompts (test-first)

- "Write the tests first — unit, integration, and E2E — before implementation" (double-loop TDD).
- Implemented module-by-module to turn the red suite green: models → validate → scheduler →
  render → catalog/pipeline. 38 tests pass (33 unit/integration + 5 Playwright E2E).

## Review & realism prompts (iteration)

The member pushed back hard on realism and ran external code reviews; each round was a
write-the-failing-test-first fix (see `docs/scheduler-bugs.md` — 11 bugs, each with a guarding test):

- "Fight back" on an external review — evaluated each item against the codebase, conceded the
  real gaps (details echoing the name; load cap counting recovery as training; silent drop of an
  in-plan activity; same-day duplicates) and pushed back on the false ones (a blanket "prep
  required" rule). Fixed the real ones with new whole-plan invariant tests.
- "Skip adjustment makes no sense for X" → `skip_adjustment` became `Optional[str]`: None for
  standing constraints and self-care; "rebook the clinic slot" for booked clinic therapies.
- "Prep for every meal is the same fixed recipe" → prep means scheduling lead-time, not a recipe;
  cleared from cook-at-the-time meals, kept on Meal-prep/Bone-broth.
- "Remote session shows Location: Clinic — wrong" → remote tasks render "Remote".
- "No caffeine after 2pm is scheduled at 12:00 — intended?" → standing daily rules became
  **all-day guardrails** (`all_day`), rendered in an all-day lane, booking nothing. Decided per the
  "governs-the-day vs happens-at-a-time" test (kept doses, workouts, eye exercises timed).

## Reproducing the data

```bash
PYTHONPATH=src python -m elyx_allocator.generate_data   # 108 activities, realistic: true
```
