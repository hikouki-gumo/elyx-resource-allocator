# Scheduler bugs — found & fixed

A log of scheduler / output bugs surfaced during development — by an external code review,
by author feedback on the rendered plan, and by an adversarial whole-plan audit — with the fix
and the regression test that now guards each one. All evidence is reproducible from
`build_tasks()` (108-activity catalog, ~30-activity action plan, 90-day horizon).

**11 items found & fixed — 7 genuine bugs + 4 rule refinements.** Every one now has an invariant
test against the real plan, so it can't silently return.

**Type** separates a **Bug** (a defect against the original spec — double-booking, silent drop, a
fasted test not honoured) from a **Refinement** (a new rule the author added later to raise realism —
all-day rules, a time budget, protected work hours; the code wasn't "wrong" before, the bar rose).
**Found by**: **AI** (independent code review / adversarial whole-plan audit) vs **Author** (feedback
on the rendered plan); **Author → AI** = the author surfaced the symptom, AI found the root cause.
Tally: **9 / 11 author-found, 2 AI** · **7 bug / 4 refinement** (plus 2 more refinements below). **Prompt** = the PROMPTS.md entry that surfaced it (#71 = the review confirming AI-audit bugs 1–3).

| # | Type | Found by | Prompt | Item | Symptom | Fix | Guarding test |
|---|------|----------|--------|------|---------|-----|---------------|
| 1 | Bug | AI | #71 | Load cap counted recovery/mind as training | 84/90 days pinned at the cap (sauna, cold plunge, breathwork ate the budget) | only `intensity >= MODERATE` counts toward the load budget | daily training-load realistic |
| 2 | Bug | AI | #71 | Budget-blocked occurrence silently dropped | Cold plunge appeared 0/90 — the load-shift did `continue`, bypassing the fallback chain, and never tried its backup | attempt a backup before omitting; never stack a second hard session | full action-plan coverage |
| 3 | Bug | Author → AI | #71 | Same activity placed twice, same day & time | 20 exact-duplicate `(activity, datetime)` pairs (shift landed on a day already holding it) | once-per-day-per-activity guard in every shift path | no duplicate placements / no same-day repeats |
| 4 | Bug | Author | #75 | Remote session showed its fixed venue | a remote Physician review read "Location: Clinic" | view-model renders "Remote" for any `Mode.REMOTE` task | remote task hides fixed location |
| 5 | Refinement | Author | #76 | Standing daily rules placed as timed slots | "No caffeine after 2pm" scheduled at 12:00 (a non-event, wrong time) | `all_day` guardrails — untimed, no booking/load, rendered in an all-day lane | guardrail untimed & books nothing |
| 6 | Bug | Author | #78 | Member double-booked | Sauna 17:30 and dinner 17:30 on the same clock (276 clashes) — the member wasn't modelled as a resource | book the member as a capacity-1 resource (supplements exempt) | member not double-booked |
| 7 | Bug | Author | #79 | Daily meals dropped (regression of #6) | breakfast appeared on only 75/90 days when its window was blocked | a flexible anchor scans the waking day before giving up | meals present every day |
| 8 | Refinement | Author | #80 | Morning over-stacked with training | 2 cardio + mobility = 115 min before breakfast; the load cap couldn't see low-intensity volume | TIME budget ≤ 90 fitness-min/day (score ≥ 2) + ≤ 1 fitness per half-day (AM/PM spread) | daily fitness-time cap; ≤1 fitness per half |
| 9 | Bug | Author | #90 | Ate before a fasted test | bloods (fasted) at 08:00, right after the 07:30 breakfast | mark bloods/DEXA `meal_relation = FASTED`; place breakfast last, after any morning fasted test | no meal before a fasted test |
| 10 | Refinement | Author | #92 | In-person sessions during work hours | 110 in-person sessions inside the 09:00–18:00 weekday work block (16:00 strength mid-workday) | protect weekday core hours 09:00–17:30; train 06:30–08:00 / 17:30–19:00 | no in-person session in work hours |
| 11 | Refinement | Author | #96 | Venue sessions before the day starts | in-person sessions at a venue scheduled before 07:00 with no get-ready/travel time | the member wakes 06:30; venue (non-home) sessions start no earlier than 07:00 | venue sessions not before 07:00 |

## Rule refinements (not bugs, but corrections)
- **Sunday = active rest.** _(Author, #85)_ An early over-restrictive rule blocked hard work on *both* weekend days; corrected so **Saturday is a normal training day** and only **Sunday** blocks moderate+.
- **Meal anchors.** _(Author, #81)_ Meals are anchored at fixed times (breakfast 08:00, lunch 13:00, dinner 19:00) and the day is built around them.

## A held decision (not fixed by design)
**Unplaceable occurrences are omitted silently, not surfaced as a "skipped" marker.** This is a
*proposed* plan — it shows what *is* scheduled, not ghosts of what isn't. The full-coverage test
(#2) guarantees nothing in the action plan vanishes, which is the real protection; a skip marker
would just add noise.

## NOT bugs — do not "fix" these
- **Sauna "80–90 °C, 20–25 min"** is correct — ambient dry-air temperature; Finnish saunas run 80–100 °C.
- **`res-cryo` / `res-hbot` show 0 bookings** — correct; they're in the 108-activity catalog but not the action plan.
- **`prep` empty on most activities** — correct by design. Prep is filled only where it's real (cooked meals, fasted tests, kit). The validator gates only `fasted`/`empty_stomach`; do not add a generic "prep required" rule.
