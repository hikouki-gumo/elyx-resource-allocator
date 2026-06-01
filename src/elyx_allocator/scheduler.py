"""The Resource Allocator core.

Greedy, priority-first, single pass over a 90-day horizon. The intelligence is in
the *data* (each Activity carries circadian window, load, travel behavior, backups),
so this stays a simple placer that still produces a coach-quality plan.

Per-occurrence fallback chain:
    preferred window → alternate time same day → remote (if capable)
    → backup activity (the skip-adjustment realised) → otherwise omit
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, time

from .models import (ScheduledTask, Mode, Intensity, TravelBehavior, Window, ActivityType,
                     MealRelation)

# intensity rank from the activity's own classification (feeds the day's "hard days" stat)
_INTENSITY_RANK = {Intensity.NONE: 0, Intensity.LOW: 1, Intensity.MODERATE: 2, Intensity.HIGH: 3}

WINDOW_TIMES = {
    Window.MORNING: [(6, 30), (7, 0), (7, 30), (8, 0)],
    Window.MIDDAY: [(12, 0), (12, 30), (13, 0), (13, 30)],
    Window.EVENING: [(17, 30), (18, 0), (18, 30), (19, 0), (19, 30)],
    Window.BEFORE_BED: [(21, 0), (21, 30)],
    Window.ANY: [(7, 0), (8, 0), (12, 30), (16, 0), (18, 30)],
}

# a working member trains in two windows only: before breakfast and before dinner.
# ≤1 fitness per window. (Core work hours 09:00–17:30 are protected — see work_free.)
AM_SLOTS = [(6, 30), (7, 0), (7, 30)]          # 06:30–08:00, before the 08:00 breakfast
PM_SLOTS = [(17, 30), (18, 0), (18, 30)]       # 17:30–19:00, before the 19:00 dinner

# weekday core working hours — no in-person sessions land here (meals/remote are exempt)
WORK_START, WORK_END = (9, 0), (17, 30)


def _hhmm(s: str):
    h, m = s.split(":")
    return int(h), int(m)


def _in_sleep(dt: datetime, sleep) -> bool:
    sh, sm = _hhmm(sleep[0])
    eh, em = _hhmm(sleep[1])
    mins = dt.hour * 60 + dt.minute
    smin, emin = sh * 60 + sm, eh * 60 + em
    if smin > emin:            # overnight window (e.g. 22:30 → 06:30)
        return mins >= smin or mins < emin
    return smin <= mins < emin


def _trip_for(d: date, trips):
    for t in trips:
        if t.start <= d <= t.end:
            return t
    return None


def schedule(plan, availability, start: date, days: int = 90, catalog=None):
    plan = sorted(plan, key=lambda a: a.priority)        # most-important-to-health first
    by_id = {a.id: a for a in (catalog or plan)}          # resolve backups from the catalog
    by_id.update({a.id: a for a in plan})
    res = availability.resources
    sleep = availability.commitments.sleep if availability.commitments else ("22:30", "06:30")
    trips = availability.travel or []
    bookings = {rid: list(r.booked_windows) for rid, r in res.items()}
    day_load = {}          # date -> cumulative training-load score (caps a day's total volume)
    DAILY_LOAD_CAP = 10    # ~one key session + something light; blocks stacking two real workouts
    day_fit_min = {}       # date -> fitness minutes (sessions score>=2) — caps daily volume
    DAILY_FITNESS_MIN = 90 # a time-poor exec's ceiling; load-1 micro-work is free (not counted)
    placed_on = {}         # activity_id -> set of dates already scheduled (once-per-day guard)
    member_busy = []       # [(start, end)] — the member is one person; body-occupying
    fitness_part = {}      # date -> {'am','pm'} halves already holding a fitness session
    tasks = []             # sessions can't overlap (supplements piggyback on meals → exempt)
    meal_times = (availability.commitments.meals if availability.commitments
                  else ["07:30", "13:00", "19:00"])
    _WIN_MEAL = {Window.MORNING: 0, Window.MIDDAY: 1, Window.EVENING: 2}

    def occupies_member(act):
        # a real demand on the member's body/time. Pills/supplements are taken alongside
        # a meal (you swallow Vitamin D with breakfast), so they don't block the timeline.
        return act.type != ActivityType.MEDICATION and not act.all_day

    def member_free(s, e) -> bool:
        return all(not (s < be and bs < e) for (bs, be) in member_busy)

    def training_load(act):
        # only real workouts (moderate+) count toward the training budget; recovery (sauna,
        # cold plunge) and mind work (breathwork) are not training and must not saturate it
        return act.load.score if _INTENSITY_RANK.get(act.load.intensity, 0) >= 2 else 0

    def on_day(aid, day):
        return day in placed_on.get(aid, set())

    def day_ok(day, score):
        # Sunday is active rest — no moderate+ training (score>0); easy/recovery only.
        # Saturday is a normal training day. Otherwise just the daily load budget.
        if score and day.weekday() == 6:
            return False
        return day_load.get(day, 0) + score <= DAILY_LOAD_CAP

    def work_free(s, e):
        # protect weekday core hours: no in-person session may overlap 09:00–17:30 Mon–Fri
        if s.weekday() >= 5:
            return True
        ws = s.replace(hour=WORK_START[0], minute=WORK_START[1], second=0, microsecond=0)
        we = s.replace(hour=WORK_END[0], minute=WORK_END[1], second=0, microsecond=0)
        return not (s < we and ws < e)

    def is_main_meal(act):
        return (act.type == ActivityType.FOOD and not act.all_day
                and act.circadian.meal_relation == MealRelation.WITH_FOOD
                and act.frequency.period == "day" and act.frequency.times == 1
                and act.circadian.window in _WIN_MEAL)

    def meal_anchor(act):
        idx = _WIN_MEAL[act.circadian.window]
        return _hhmm(meal_times[idx]) if idx < len(meal_times) else None

    def fit_minutes(act):
        # fitness time that counts toward the daily budget — score-1 micro-work is free
        return act.duration_min if act.load.score >= 2 else 0

    def fitness_day_ok(dd, act, score):
        """A fitness session fits day dd iff all three gates pass; returns the half-day's
        candidate slot times (natural half preferred, else the other), or None."""
        if score and not day_ok(dd, score):                              # LOAD (+ Sunday rest)
            return None
        if day_fit_min.get(dd, 0) + fit_minutes(act) > DAILY_FITNESS_MIN:  # TIME budget
            return None
        natural = "am" if act.circadian.window == Window.MORNING else "pm"
        used = fitness_part.get(dd, set())
        for part in (natural, "pm" if natural == "am" else "am"):         # ≤1 fitness per half
            if part not in used:
                return AM_SLOTS if part == "am" else PM_SLOTS
        return None

    def res_free(rid, s, e) -> bool:
        r = res.get(rid)
        if r is None:
            return False
        oh = r.operating_hours.get(s.weekday())
        if not oh:
            return False
        if not (time(*_hhmm(oh[0])) <= s.time() and e.time() <= time(*_hhmm(oh[1]))):
            return False
        overlaps = sum(1 for (bs, be) in bookings.get(rid, []) if s < be and bs < e)
        return overlaps < r.capacity

    def window_slot(act, d):
        for (h, m) in WINDOW_TIMES.get(act.circadian.window, WINDOW_TIMES[Window.ANY]):
            s = datetime(d.year, d.month, d.day, h, m)
            e = s + timedelta(minutes=act.duration_min)
            if _in_sleep(s, sleep):
                continue
            if occupies_member(act) and not member_free(s, e):
                continue
            return s, e
        # windowed slots all taken/asleep — scan the waking day for the first free slot
        for mins in range(6 * 60, 21 * 60, 15):
            s = datetime(d.year, d.month, d.day, mins // 60, mins % 60)
            e = s + timedelta(minutes=act.duration_min)
            if _in_sleep(s, sleep):
                continue
            if occupies_member(act) and not member_free(s, e):
                continue
            return s, e
        s = datetime(d.year, d.month, d.day, 16, 0)
        return s, s + timedelta(minutes=act.duration_min)

    def place_in_person(act, d, slots=None):
        fid = (act.facilitator or {}).get("id")
        need = [r for r in (fid, act.location) if r and r in res]   # book facilitator + location
        times = slots if slots is not None else WINDOW_TIMES.get(act.circadian.window,
                                                                 WINDOW_TIMES[Window.ANY])
        for (h, m) in times:
            s = datetime(d.year, d.month, d.day, h, m)
            e = s + timedelta(minutes=act.duration_min)
            if _in_sleep(s, sleep):
                continue
            if occupies_member(act) and not member_free(s, e):
                continue
            if act.type != ActivityType.FOOD and not work_free(s, e):
                continue   # protect weekday work hours (meals are exempt)
            if act.location != "res-home" and s.hour * 60 + s.minute < 7 * 60:
                continue   # day starts 06:30; getting to a venue takes until 07:00
            if need and not all(res_free(r, s, e) for r in need):
                continue
            return s, e, need
        if slots is not None:
            return None   # fitness is pinned to its half-day's slots — don't scan the whole day
        # preferred windows are blocked — scan the waking day for any valid slot before
        # giving up, so a flexible daily anchor (a meal) shifts in time rather than being
        # dropped. res_free still enforces each resource's real operating hours.
        for mins in range(6 * 60, 21 * 60, 15):
            s = datetime(d.year, d.month, d.day, mins // 60, mins % 60)
            e = s + timedelta(minutes=act.duration_min)
            if _in_sleep(s, sleep):
                continue
            if occupies_member(act) and not member_free(s, e):
                continue
            if act.type != ActivityType.FOOD and not work_free(s, e):
                continue
            if act.location != "res-home" and s.hour * 60 + s.minute < 7 * 60:
                continue
            if need and not all(res_free(r, s, e) for r in need):
                continue
            return s, e, need
        return None

    def reason_for(act, mode, trip):
        bits = []
        w = act.circadian.window.value
        if w != "any":
            bits.append(f"{w} slot")
        if act.circadian.meal_relation.value not in ("none",):
            bits.append(act.circadian.meal_relation.value.replace("_", " "))
        if mode is Mode.REMOTE and trip:
            bits.append(f"remote while travelling to {trip.destination}")
        elif mode is Mode.REMOTE:
            bits.append("resource unavailable — taken remotely")
        return ", ".join(bits) or f"{act.pillar.value} session"

    def _detail(act):
        fid = (act.facilitator or {}).get("id")
        role = (act.facilitator or {}).get("role")
        fac_label = res[fid].label if (fid and fid in res) else ("Self" if role == "self" else role)
        loc_label = res[act.location].label if act.location in res else act.location
        return {
            "type": act.type.value, "details": act.details, "location": loc_label,
            "duration_min": act.duration_min, "prep": act.prep,
            "backups": [by_id[b].name if b in by_id else b for b in act.backups],  # names, not ids
            "metrics": act.metrics, "facilitator": fac_label,
            "skip_adjustment": act.skip_adjustment, "all_day": act.all_day,
        }

    def emit(act, s, e, mode, resources, reason, sub=None, note=None):
        placed_on.setdefault(act.id, set()).add(s.date())
        if occupies_member(act):
            member_busy.append((s, e))
        if act.type == ActivityType.FITNESS and not act.all_day:
            fitness_part.setdefault(s.date(), set()).add("am" if s.hour < 12 else "pm")
            day_fit_min[s.date()] = day_fit_min.get(s.date(), 0) + fit_minutes(act)
        tasks.append(ScheduledTask(
            activity_id=act.id, start=s, end=e, mode=mode, pillar=act.pillar,
            reason=reason, resources=resources, substituted_from=sub, note=note,
            title=act.name, detail=_detail(act), load=_INTENSITY_RANK.get(act.load.intensity, 0)))

    def try_fitness(act, dd, score, allow_remote=False, remote_only=False,
                    sub=None, note=None, reason=None):
        """Place a fitness session on dd honouring all three gates (load+Sunday, time, half).
        Returns True if placed (in person, or remote when allowed). Every fitness emission
        goes through here so the daily caps can't be bypassed by backups or travel."""
        slots = fitness_day_ok(dd, act, score)
        if slots is None:
            return False
        if not remote_only:
            spot = place_in_person(act, dd, slots)
            if spot:
                s, e, need = spot
                for r in need:
                    bookings.setdefault(r, []).append((s, e))
                emit(act, s, e, Mode.IN_PERSON, need,
                     reason or reason_for(act, Mode.IN_PERSON, None), sub=sub, note=note)
                if score:
                    day_load[dd] = day_load.get(dd, 0) + score
                return True
        if remote_only or (allow_remote and act.remote_capable):
            for (h, m) in slots:
                s = datetime(dd.year, dd.month, dd.day, h, m)
                e = s + timedelta(minutes=act.duration_min)
                if _in_sleep(s, sleep) or not member_free(s, e):
                    continue
                emit(act, s, e, Mode.REMOTE, [],
                     reason or reason_for(act, Mode.REMOTE, None), sub=sub, note=note)
                if score:
                    day_load[dd] = day_load.get(dd, 0) + score
                return True
        return False

    def do_backup(act, d) -> bool:
        """Apply the activity's adjustment by scheduling a backup in its place.
        If no backup fits, the activity is simply omitted (not rendered as 'skipped')."""
        for bid in act.backups:
            b = by_id.get(bid)
            if not b:
                continue
            # fitness backups must respect the daily fitness gates (load/time/half)
            if b.type == ActivityType.FITNESS:
                if try_fitness(b, d, training_load(b), allow_remote=True,
                               sub=act.id, note=act.skip_adjustment,
                               reason=f"travel-friendly alternative to {act.name}"):
                    return True
                continue
            slot = place_in_person(b, d)
            if slot:
                s, e, need = slot
                for r in need:
                    bookings.setdefault(r, []).append((s, e))
                emit(b, s, e, Mode.IN_PERSON, need, f"travel-friendly alternative to {act.name}",
                     sub=act.id, note=act.skip_adjustment)
                return True
            if b.remote_capable:
                s, e = window_slot(b, d)
                emit(b, s, e, Mode.REMOTE, [], f"travel-friendly alternative to {act.name}",
                     sub=act.id, note=act.skip_adjustment)
                return True
        return False

    def pick_day_offsets(count, period, phase):
        if count <= 0:
            return []
        step = days / count
        # daily = every day; everything else staggers by a per-activity phase within its own
        # gap, so different weekly/rare activities land on different days (not all on day 0)
        base = 0 if period == "day" else phase % max(1, round(step))
        return sorted({min(days - 1, int(base + i * step)) for i in range(count)})

    # --- Phase 0: meal canvas. Anchor lunch & dinner at fixed times every day, first, so the
    # day is built around them. Breakfast waits for Phase 2 — it must come *after* any morning
    # fasted test (bloods/DEXA), so it can't be pinned before the main pass places those. ---
    for act in plan:
        if not is_main_meal(act) or act.circadian.window == Window.MORNING:
            continue
        anchor = meal_anchor(act)
        if not anchor:
            continue
        fid = (act.facilitator or {}).get("id")
        need = [r for r in (fid, act.location) if r and r in res]
        for off in range(days):
            d = start + timedelta(days=off)
            s = datetime(d.year, d.month, d.day, anchor[0], anchor[1])
            e = s + timedelta(minutes=act.duration_min)
            for r in need:
                bookings.setdefault(r, []).append((s, e))
            emit(act, s, e, Mode.IN_PERSON, need, "fixed meal time")

    for act in plan:
        if is_main_meal(act):
            continue                                   # already placed in Phase 0
        phase = sum(ord(c) for c in act.id) % 14   # stable per-activity stagger

        # standing daily guardrails (hydration, caffeine cut-off …) are rules, not timed
        # sessions: emit one all-day entry per applicable day — no clock time, no resource
        # booking, no training load. Applies even while travelling.
        if act.all_day:
            for off in pick_day_offsets(act.frequency.total_occurrences(days),
                                        act.frequency.period, phase):
                d = start + timedelta(days=off)
                s = datetime(d.year, d.month, d.day, 0, 0)
                emit(act, s, s, Mode.IN_PERSON, [], "standing daily guardrail — applies all day")
            continue

        is_fitness = act.type == ActivityType.FITNESS
        for off in pick_day_offsets(act.frequency.total_occurrences(days), act.frequency.period, phase):
            d = start + timedelta(days=off)
            score = training_load(act)
            trip = _trip_for(d, trips)

            # ---- fitness: load + time + half-day gates decide the day; the half picks the time.
            # All fitness (travel included) flows through try_fitness so the caps always hold ----
            if is_fitness:
                if trip and act.travel_behavior == TravelBehavior.SKIP:
                    do_backup(act, d)
                    continue
                if trip and act.travel_behavior == TravelBehavior.BACKUP:
                    do_backup(act, d)
                    continue
                if trip and act.travel_behavior == TravelBehavior.REMOTE:
                    if not try_fitness(act, d, score, remote_only=True):
                        do_backup(act, d)
                    continue
                # no trip (or CONTINUE on a trip): place in person on the nearest gated day
                placed = False
                for delta in range(0, days):
                    for cand in ((off,) if delta == 0 else (off + delta, off - delta)):
                        if not (0 <= cand < days):
                            continue
                        dd = start + timedelta(days=cand)
                        if on_day(act.id, dd) or _trip_for(dd, trips):
                            continue
                        if try_fitness(act, dd, score):
                            placed = True
                            break
                    if placed:
                        break
                if not placed:                       # no day fits in person → remote, else backup
                    if not try_fitness(act, d, score, allow_remote=True) and act.backups:
                        do_backup(act, d)
                continue

            # shift off a day that's over the training budget OR already holds this activity.
            # Search the nearest day that has room AND isn't already running this activity →
            # avoids stacking and same-day duplicates.
            if on_day(act.id, d) or (score and not day_ok(d, score)):
                alt = None
                for delta in range(1, days):
                    for cand in (off + delta, off - delta):
                        if not (0 <= cand < days):
                            continue
                        cd = start + timedelta(days=cand)
                        if not on_day(act.id, cd) and (not score or day_ok(cd, score)):
                            alt = cand
                            break
                    if alt is not None:
                        break
                if alt is not None:
                    d = start + timedelta(days=alt)
                else:
                    # budget full everywhere → try a backup in its place, then move on.
                    do_backup(act, d)
                    continue

            trip = _trip_for(d, trips)   # recompute: the shift above may have moved the day

            if trip and act.travel_behavior == TravelBehavior.SKIP:
                do_backup(act, d)   # apply adjustment via a backup if one fits; else omit
                continue
            if trip and act.travel_behavior == TravelBehavior.REMOTE:
                s, e = window_slot(act, d)
                emit(act, s, e, Mode.REMOTE, [], reason_for(act, Mode.REMOTE, trip))
                if score:
                    day_load[d] = day_load.get(d, 0) + score
                continue
            if trip and act.travel_behavior == TravelBehavior.BACKUP:
                if do_backup(act, d) and score:
                    day_load[d] = day_load.get(d, 0) + score
                continue

            slot = place_in_person(act, d)
            if slot:
                s, e, need = slot
                for r in need:
                    bookings.setdefault(r, []).append((s, e))
                emit(act, s, e, Mode.IN_PERSON, need, reason_for(act, Mode.IN_PERSON, trip))
                if score:
                    day_load[d] = day_load.get(d, 0) + score
            elif act.remote_capable:
                s, e = window_slot(act, d)
                emit(act, s, e, Mode.REMOTE, [], reason_for(act, Mode.REMOTE, trip))
                if score:
                    day_load[d] = day_load.get(d, 0) + score
            elif act.backups:
                if do_backup(act, d) and score:
                    day_load[d] = day_load.get(d, 0) + score
            else:
                # last resort before skipping: shift to a nearby open day (e.g. scarce lab)
                placed_alt = False
                for delta in (1, -1, 2, -2, 3, -3, 4, 5, 6):
                    cand = off + delta
                    if not (0 <= cand < days):
                        continue
                    dd = start + timedelta(days=cand)
                    if _trip_for(dd, trips) or on_day(act.id, dd):
                        continue
                    slot2 = place_in_person(act, dd)
                    if slot2:
                        s, e, need = slot2
                        for r in need:
                            bookings.setdefault(r, []).append((s, e))
                        emit(act, s, e, Mode.IN_PERSON, need, reason_for(act, Mode.IN_PERSON, None))
                        if score:
                            day_load[dd] = day_load.get(dd, 0) + score
                        placed_alt = True
                        break
                if not placed_alt:
                    do_backup(act, d)   # try a backup; otherwise leave the slot empty (omit)

    # --- Phase 2: breakfast. Placed last so it lands *after* any morning fasted test that
    # day (you don't eat before fasted bloods/DEXA) and never overlaps a workout already there.
    # Prefer the 08:00 anchor; otherwise the first free morning slot past the fast. ---
    fasted_ids = {a.id for a in by_id.values()
                  if a.circadian.meal_relation in (MealRelation.FASTED, MealRelation.EMPTY_STOMACH)
                  and occupies_member(a)}
    fasted_end = {}   # date -> latest end of a morning fasted test that day
    for t in tasks:
        if t.activity_id in fasted_ids and t.start.hour < 12:
            d0 = t.start.date()
            if d0 not in fasted_end or t.end > fasted_end[d0]:
                fasted_end[d0] = t.end
    for act in plan:
        if not (is_main_meal(act) and act.circadian.window == Window.MORNING):
            continue
        anchor = meal_anchor(act) or (8, 0)
        fid = (act.facilitator or {}).get("id")
        need = [r for r in (fid, act.location) if r and r in res]
        for off in range(days):
            d = start + timedelta(days=off)
            earliest = anchor[0] * 60 + anchor[1]
            fe = fasted_end.get(d)
            if fe is not None:
                earliest = max(earliest, fe.hour * 60 + fe.minute)
            for mins in range(earliest, 12 * 60, 15):       # morning slots from the floor up
                s = datetime(d.year, d.month, d.day, mins // 60, mins % 60)
                e = s + timedelta(minutes=act.duration_min)
                if _in_sleep(s, sleep) or not member_free(s, e):
                    continue
                if need and not all(res_free(r, s, e) for r in need):
                    continue
                for r in need:
                    bookings.setdefault(r, []).append((s, e))
                reason = ("after the fasted test" if fe is not None else "fixed meal time")
                emit(act, s, e, Mode.IN_PERSON, need, reason)
                break

    tasks.sort(key=lambda t: t.start)
    return tasks
