"""The Elyx activity catalog (100+) + the clinic's resources and the member's
availability — grounded in the real Elyx menu and the $150k exec persona.

Model: a **facilitator** is always a person (trainer, physio, physician, dietitian,
psychologist, sports-medicine, recovery technician, lab technician) or **self** (the
member, unsupervised). **Equipment belongs to the location** — the location is the
bookable resource that carries capacity/operating-hours (gym, clinic, sauna suite,
DEXA suite, …). The scheduler books the facilitator (if any) AND the location.

The dataset is a *catalog* of 100+ distinct activities; a member's *action plan*
is a priority-ordered subset (build_action_plan).
"""
from __future__ import annotations

import re
from datetime import date
from .models import (
    Activity, ActivityType, Pillar, Frequency, Circadian, Window, MealRelation,
    Load, Intensity, TravelBehavior, Resource, ResourceTier, TravelTrip,
    ClientCommitments, Availability,
)

FIT, FOOD, MED, THER, CONS = (ActivityType.FITNESS, ActivityType.FOOD, ActivityType.MEDICATION,
                              ActivityType.THERAPY, ActivityType.CONSULTATION)
MOV, NUT, MEDS, THERAP, DIAG, SLEEP, MIND = (Pillar.MOVEMENT, Pillar.NUTRITION, Pillar.MEDS,
                                             Pillar.THERAPIES, Pillar.DIAGNOSTICS, Pillar.SLEEP, Pillar.MIND)
W, MR, I, TB = Window, MealRelation, Intensity, TravelBehavior

DEFAULT_SKIP = {
    FIT: "shift to the next open day; keep 48h between hard sessions",
    FOOD: "resume at the next meal — don't double up",
    MED: "take at the next scheduled dose — never double",
    THER: "rebook the clinic slot within the next day or two",
    CONS: "rebook within the same week",
}

# sentinel: pass skip=NO_SKIP for activities that are standing constraints or continuous
# daily targets (avoidance rules, eating windows, hydration) — there's nothing to "make up",
# so they carry no skip adjustment at all (distinct from skip=None, which means "use default")
NO_SKIP = object()


def _res():
    everyday = {d: ("06:00", "21:00") for d in range(7)}
    home = {d: ("05:30", "22:30") for d in range(7)}            # waking hours, incl. before-bed
    clinic = {d: ("06:00", "22:00") for d in range(7)}          # premium clinic — wide daily hours
    physician_days = {0: ("09:00", "17:00"), 2: ("09:00", "17:00"), 4: ("09:00", "13:00")}
    sportsmd_days = {1: ("09:00", "16:00")}                     # visiting fellow — Tue
    appt = {d: ("06:00", "20:00") for d in range(7)}            # owned labs/machines — daily, white-glove

    def R(id, type, tier, cap, hours, label):
        return Resource(id=id, type=type, tier=tier, capacity=cap,
                        operating_hours=hours, booked_windows=[], remote_offered=(type == "human"),
                        label=label)
    return {
        # --- people (facilitators) ---
        "res-trainer": R("res-trainer", "human", ResourceTier.MODERATE, 1, everyday, "Personal trainer"),
        "res-coach": R("res-coach", "human", ResourceTier.MODERATE, 1, everyday, "Performance coach"),
        "res-physio": R("res-physio", "human", ResourceTier.MODERATE, 1, clinic, "Physiotherapist"),
        "res-dietitian": R("res-dietitian", "human", ResourceTier.MODERATE, 1, everyday, "Dietitian"),
        "res-psychologist": R("res-psychologist", "human", ResourceTier.MODERATE, 1, everyday, "Psychologist"),
        "res-physician": R("res-physician", "human", ResourceTier.SCARCE, 1, physician_days, "Physician"),
        "res-sportsmd": R("res-sportsmd", "human", ResourceTier.SCARCE, 1, sportsmd_days, "Sports-medicine physician"),
        "res-technician": R("res-technician", "human", ResourceTier.BROAD, 3, clinic, "Recovery technician"),
        "res-labtech": R("res-labtech", "human", ResourceTier.SCARCE, 1, appt, "Lab technician"),
        # --- places (equipment lives here) ---
        "res-home": R("res-home", "location", ResourceTier.ABUNDANT, 99, home, "Home"),
        "res-gym": R("res-gym", "location", ResourceTier.BROAD, 3, everyday, "Gym"),
        "res-clinic": R("res-clinic", "location", ResourceTier.BROAD, 20, clinic, "Clinic"),
        "res-sauna": R("res-sauna", "location", ResourceTier.BROAD, 2, clinic, "Sauna suite"),
        "res-cryo": R("res-cryo", "location", ResourceTier.SINGLE_UNIT, 1, clinic, "Cryo chamber"),
        "res-hbot": R("res-hbot", "location", ResourceTier.SINGLE_UNIT, 1, appt, "HBOT chamber"),
        "res-redlight": R("res-redlight", "location", ResourceTier.BROAD, 1, clinic, "Red-light room"),
        "res-dexa": R("res-dexa", "location", ResourceTier.SINGLE_UNIT, 1, appt, "DEXA suite"),
        "res-vo2lab": R("res-vo2lab", "location", ResourceTier.SINGLE_UNIT, 1, appt, "VO₂ lab"),
        "res-bloodlab": R("res-bloodlab", "location", ResourceTier.SINGLE_UNIT, 1, appt, "Blood lab"),
        "res-outdoors": R("res-outdoors", "location", ResourceTier.ABUNDANT, 99, everyday, "Outdoors"),
        "res-pool": R("res-pool", "location", ResourceTier.BROAD, 4, clinic, "Pool"),
        "res-track": R("res-track", "location", ResourceTier.ABUNDANT, 20, everyday, "Track"),
    }


RESOURCES = _res()


def _slug(name):
    body = re.sub(r"-+", "-", "".join(c if c.isalnum() else "-" for c in name.lower())).strip("-")
    return "act-" + body  # collapse runs (e.g. " — " → single "-") so ids stay clean & referenceable


def _A(name, typ, pillar, times, period, window, intensity, score, remote, fac, facid, loc, travel,
       backups=(), meal=MR.NONE, dur=45, gap=24, prep="", details="", prio=20, metrics=(), skip=None,
       all_day=False):
    # fac = human role or "self"; facid = human resource id or None; loc = location resource id
    return Activity(
        id=_slug(name), name=name, type=typ, pillar=pillar, priority=prio,
        frequency=Frequency(times=times, period=period), details=details or name,
        facilitator={"role": fac, "id": facid}, location=loc, remote_capable=remote,
        prep={"description": prep, "lead_time_min": 30 if prep else 0},
        backups=[_slug(b) for b in backups],
        skip_adjustment=(None if skip is NO_SKIP else (skip or DEFAULT_SKIP[typ])),
        metrics=list(metrics) or ["adherence"],
        circadian=Circadian(window=window, meal_relation=meal),
        load=Load(intensity=intensity, score=score), min_gap_hours=gap, duration_min=dur,
        travel_behavior=travel, all_day=all_day,
    )


def build_catalog() -> list:
    """100+ distinct, coherent activities across all 5 types & 7 pillars.

    _A(name, type, pillar, times, period, window, intensity, score, remote,
       facilitator_role, facilitator_id, location_id, travel_behavior, ...)
    """
    A = []

    # ---- Fitness / Movement ----
    A += [
        _A("Zone-2 cardio — easy", FIT, MOV, 2, "week", W.MORNING, I.LOW, 3, True, "trainer", "res-trainer", "res-gym", TB.REMOTE, ["Indoor cycling", "Rowing intervals"], dur=45, metrics=["avg HR", "distance"], prio=15, details="Keep HR in Zone 2 (60–70% HRmax), nose-breathing pace, fasted"),
        _A("Zone-2 cardio — moderate", FIT, MOV, 1, "week", W.MORNING, I.MODERATE, 5, True, "trainer", "res-trainer", "res-gym", TB.REMOTE, ["Indoor cycling"], dur=50, prio=11, details="Upper Zone 2 (~70% HRmax), steady continuous effort"),
        _A("Long Zone-2 ride", FIT, MOV, 1, "week", W.MORNING, I.MODERATE, 6, False, "self", None, "res-outdoors", TB.BACKUP, ["Treadmill incline walk"], dur=75, prio=13, details="Long aerobic ride in Zone 2; fuel 40–60g carbs/hr"),
        _A("VO2max intervals", FIT, MOV, 1, "week", W.MORNING, I.HIGH, 9, False, "trainer", "res-trainer", "res-gym", TB.BACKUP, ["Bodyweight HIIT"], dur=40, gap=48, prio=8, details="4×4 min @ 90–95% HRmax, 3 min easy recovery between"),
        _A("Strength — full body", FIT, MOV, 2, "week", W.EVENING, I.HIGH, 8, False, "trainer", "res-trainer", "res-gym", TB.BACKUP, ["Bodyweight circuit"], dur=60, gap=48, prio=9, details="Compound lifts, 3–4 sets @ RPE 8, full rest between sets"),
        _A("Strength — push", FIT, MOV, 1, "week", W.EVENING, I.HIGH, 8, False, "trainer", "res-trainer", "res-gym", TB.BACKUP, ["Bodyweight circuit"], dur=55, gap=48, details="Bench, overhead press, dips — 4 sets @ RPE 8"),
        _A("Strength — pull", FIT, MOV, 1, "week", W.EVENING, I.HIGH, 8, False, "trainer", "res-trainer", "res-gym", TB.BACKUP, ["Bodyweight circuit"], dur=55, gap=48, details="Rows, pull-ups, hinge — 4 sets @ RPE 8"),
        _A("Strength — legs", FIT, MOV, 1, "week", W.EVENING, I.HIGH, 9, False, "trainer", "res-trainer", "res-gym", TB.BACKUP, ["Bodyweight circuit"], dur=55, gap=48, prio=10, details="Squat + deadlift focus, 3–4 sets @ RPE 8–9"),
        _A("Bodyweight circuit", FIT, MOV, 1, "month", W.MORNING, I.MODERATE, 5, True, "self", None, "res-home", TB.CONTINUE, dur=30, details="Hotel circuit: push-ups, squats, lunges, plank × 3 rounds"),
        _A("Mobility flow", FIT, MOV, 3, "week", W.MORNING, I.LOW, 2, True, "self", None, "res-home", TB.CONTINUE, dur=20, prio=16, details="Hips, T-spine and ankles; controlled 20-min flow"),
        _A("Eye exercises", FIT, MOV, 3, "week", W.MIDDAY, I.LOW, 1, True, "self", None, "res-home", TB.CONTINUE, dur=10, prio=22, details="Near/far focus shifts + eye-muscle drills to ease screen strain"),
        _A("Tempo run", FIT, MOV, 1, "week", W.MORNING, I.HIGH, 8, False, "coach", "res-coach", "res-track", TB.BACKUP, ["Treadmill tempo"], dur=40, gap=48, details="20 min @ threshold (~85% HRmax), 10 min warm-up/down"),
        _A("Rowing intervals", FIT, MOV, 1, "month", W.MORNING, I.MODERATE, 6, False, "trainer", "res-trainer", "res-gym", TB.BACKUP, dur=30, details="6×500m @ 2k pace + 5, 90s easy between"),
        _A("Indoor cycling", FIT, MOV, 1, "month", W.MORNING, I.MODERATE, 5, True, "self", None, "res-home", TB.CONTINUE, dur=45, details="Steady Zone 2 on the turbo trainer"),
        _A("Swim technique", FIT, MOV, 1, "week", W.MORNING, I.MODERATE, 5, False, "coach", "res-coach", "res-pool", TB.SKIP, dur=45, details="Drill-focused freestyle, easy aerobic"),
        _A("Hike", FIT, MOV, 1, "month", W.MORNING, I.MODERATE, 6, False, "self", None, "res-outdoors", TB.CONTINUE, dur=120, details="Zone 2 hike on rolling terrain; bring water + snack"),
        _A("Core stability", FIT, MOV, 2, "week", W.EVENING, I.LOW, 3, True, "self", None, "res-home", TB.CONTINUE, dur=15, details="Anti-rotation + bracing: planks, dead bugs, Pallof"),
        _A("Balance training", FIT, MOV, 1, "week", W.EVENING, I.LOW, 2, True, "physio", "res-physio", "res-clinic", TB.REMOTE, dur=20, details="Single-leg balance + proprioception drills"),
        _A("Treadmill incline walk", FIT, MOV, 1, "month", W.MIDDAY, I.LOW, 3, True, "self", None, "res-home", TB.CONTINUE, dur=40, details="12% incline, 5 km/h — Zone 2 walking"),
        _A("Treadmill tempo", FIT, MOV, 1, "month", W.MORNING, I.HIGH, 8, False, "self", None, "res-gym", TB.BACKUP, dur=35, gap=48, details="Threshold pace blocks, ~85% HRmax"),
        _A("Bodyweight HIIT", FIT, MOV, 1, "month", W.MORNING, I.HIGH, 9, True, "self", None, "res-home", TB.CONTINUE, dur=25, gap=48, details="30s on / 30s off × 16: burpees, squat jumps, mountain climbers"),
        _A("Posture drills", FIT, MOV, 2, "week", W.MIDDAY, I.LOW, 1, True, "physio", "res-physio", "res-clinic", TB.REMOTE, dur=10, details="Scapular + thoracic resets to offset desk posture"),
        _A("Grip strength work", FIT, MOV, 1, "week", W.EVENING, I.LOW, 3, True, "self", None, "res-home", TB.CONTINUE, dur=10, details="Dead hangs + farmer holds — longevity marker"),
        _A("Sprint intervals", FIT, MOV, 1, "month", W.MORNING, I.HIGH, 9, False, "coach", "res-coach", "res-track", TB.SKIP, dur=30, gap=48, details="8×80m @ ~95% effort, full walk-back recovery"),
        _A("Yoga", FIT, MOV, 1, "week", W.EVENING, I.LOW, 2, True, "self", None, "res-home", TB.CONTINUE, dur=40, details="Vinyasa flow for mobility + parasympathetic wind-down"),
        _A("Pilates", FIT, MOV, 1, "week", W.MIDDAY, I.MODERATE, 4, False, "coach", "res-coach", "res-clinic", TB.REMOTE, dur=45, details="Mat Pilates — core control and stability"),
        _A("Kettlebell complex", FIT, MOV, 1, "month", W.EVENING, I.HIGH, 7, False, "trainer", "res-trainer", "res-gym", TB.BACKUP, dur=30, gap=48, details="Clean–press–squat flow, 5 rounds, moderate load"),
        _A("Loaded carries", FIT, MOV, 1, "month", W.EVENING, I.MODERATE, 6, False, "trainer", "res-trainer", "res-gym", TB.BACKUP, dur=20, details="Farmer + suitcase carries, 4 × 40m heavy"),
        _A("Sled pushes", FIT, MOV, 1, "month", W.EVENING, I.HIGH, 8, False, "trainer", "res-trainer", "res-gym", TB.BACKUP, dur=20, gap=48, details="10 × 20m pushes, heavy, full recovery"),
        _A("Foam rolling", FIT, MOV, 3, "week", W.BEFORE_BED, I.LOW, 1, True, "self", None, "res-home", TB.CONTINUE, dur=10, details="Quads, glutes, calves, T-spine — 60s each"),
        _A("Stretch routine", FIT, MOV, 2, "week", W.BEFORE_BED, I.LOW, 1, True, "self", None, "res-home", TB.CONTINUE, dur=15, details="Static holds 45s for hips, hamstrings, chest"),
        _A("Breath-paced walk", FIT, MOV, 2, "week", W.MIDDAY, I.LOW, 2, True, "self", None, "res-outdoors", TB.CONTINUE, dur=25, details="Easy walk, nasal breathing, post-lunch glucose dip"),
    ]

    # ---- Food / Nutrition (all self-administered, at home) ----
    A += [
        _A("Protein-forward breakfast", FOOD, NUT, 1, "day", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=20, metrics=["protein g"], details="≥30 g protein within 1h of waking"),
        _A("Protein-forward lunch", FOOD, NUT, 1, "day", W.MIDDAY, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=30, metrics=["protein g"], details="~40 g protein + fibrous veg, lower-GI carbs"),
        _A("Protein-forward dinner", FOOD, NUT, 1, "day", W.EVENING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=40, details="~40 g protein, finish ≥3h before bed"),
        _A("CGM-guided meal", FOOD, NUT, 2, "week", W.MIDDAY, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=30, metrics=["glucose AUC"], details="Order food → protein/veg first, keep glucose rise < 30 mg/dL"),
        _A("Omega-3 rich meal", FOOD, NUT, 2, "week", W.EVENING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FAT, dur=30, details="Wild salmon/sardines, ~2 g EPA+DHA from food"),
        _A("Hydration protocol", FOOD, NUT, 1, "day", W.ANY, I.NONE, 0, True, "self", None, "res-home", TB.CONTINUE, dur=5, metrics=["fluid L"], details="~3 L water across the day + electrolytes on training days", skip=NO_SKIP, all_day=True),
        _A("Electrolyte load", FOOD, NUT, 3, "week", W.MORNING, I.NONE, 0, True, "self", None, "res-home", TB.CONTINUE, dur=5, details="Sodium + potassium + magnesium pre-training"),
        _A("Fermented foods", FOOD, NUT, 3, "week", W.MIDDAY, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=10, details="A serving of kefir/kimchi/sauerkraut for gut diversity"),
        _A("Polyphenol salad", FOOD, NUT, 3, "week", W.MIDDAY, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=15, details="Mixed colours + EVOO; aim 30 plants/week"),
        _A("Time-restricted eating window", FOOD, NUT, 1, "day", W.MORNING, I.NONE, 0, True, "self", None, "res-home", TB.CONTINUE, dur=5, metrics=["window hrs"], details="Keep eating inside a 10-hour window", skip=NO_SKIP, all_day=True),
        _A("Fibre target", FOOD, NUT, 1, "day", W.EVENING, I.NONE, 0, True, "self", None, "res-home", TB.CONTINUE, dur=5, metrics=["fibre g"], details="≥35 g fibre/day across whole foods", skip=NO_SKIP, all_day=True),
        _A("Pre-training carbs", FOOD, NUT, 2, "week", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=10, details="~30–40 g easy carbs 60–90 min before a hard session"),
        _A("Post-training protein", FOOD, NUT, 3, "week", W.EVENING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=10, details="25–40 g protein within the recovery window"),
        _A("Leafy greens portion", FOOD, NUT, 1, "day", W.EVENING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=10, details="2 cups dark leafy greens — nitrates + folate"),
        _A("Oily fish serving", FOOD, NUT, 2, "week", W.EVENING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FAT, dur=20, details="Salmon, mackerel or sardines for omega-3"),
        _A("Berries & nuts snack", FOOD, NUT, 3, "week", W.MIDDAY, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, dur=5, details="Mixed berries + a small handful of nuts"),
        _A("No caffeine after 2pm", FOOD, NUT, 1, "day", W.MIDDAY, I.NONE, 0, True, "self", None, "res-home", TB.CONTINUE, dur=1, details="Caffeine cut-off ~8–10h before bed to protect deep sleep", skip=NO_SKIP, all_day=True),
        _A("Alcohol-free day", FOOD, NUT, 4, "week", W.EVENING, I.NONE, 0, True, "self", None, "res-home", TB.CONTINUE, dur=1, details="No alcohol — protects HRV and sleep architecture", skip=NO_SKIP, all_day=True),
        _A("Bone broth", FOOD, NUT, 2, "week", W.EVENING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=10, details="Collagen + electrolytes; gut and joint support", prep="simmer 8h or reheat pre-made"),
        _A("Meal prep session", FOOD, NUT, 1, "week", W.EVENING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, dur=60, details="Batch-cook proteins, grains and veg for the week", prep="shop the list; batch-cook + portion into containers"),
    ]

    # ---- Medication / Supplements (self-administered at home) ----
    A += [
        _A("Vitamin D3", MED, MEDS, 1, "day", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FAT, dur=1, details="4000 IU with the fatty breakfast (fat-soluble)"),
        _A("Omega-3 capsules", MED, MEDS, 1, "day", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FAT, dur=1, details="~2 g combined EPA+DHA with food"),
        _A("Magnesium glycinate", MED, MEDS, 1, "day", W.BEFORE_BED, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, dur=1, details="300–400 mg ~60 min before bed; keep away from iron"),
        _A("Creatine monohydrate", MED, MEDS, 1, "day", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=1, details="5 g daily, timing-agnostic"),
        _A("NMN", MED, MEDS, 1, "day", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, dur=1, details="500 mg in the morning"),
        _A("Berberine", MED, MEDS, 1, "day", W.MIDDAY, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=1, details="500 mg with the largest carb-containing meal"),
        _A("Probiotic", MED, MEDS, 1, "day", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.EMPTY_STOMACH, dur=1, details="Multi-strain, on an empty stomach", prep="take ~20 min before breakfast"),
        _A("Vitamin K2", MED, MEDS, 1, "day", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FAT, dur=1, details="MK-7 100 mcg with fat; pairs with vitamin D"),
        _A("Zinc", MED, MEDS, 3, "week", W.EVENING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=1, details="15 mg with food; not alongside iron"),
        _A("B-complex", MED, MEDS, 1, "day", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=1, details="Methylated B-complex with breakfast"),
        _A("CoQ10", MED, MEDS, 1, "day", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FAT, dur=1, details="100 mg ubiquinol with a fatty meal"),
        _A("Ashwagandha", MED, MEDS, 1, "day", W.BEFORE_BED, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, dur=1, details="600 mg KSM-66 in the evening for stress/cortisol"),
        _A("Glycine", MED, MEDS, 1, "day", W.BEFORE_BED, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, dur=1, details="3 g before bed to support sleep onset"),
        _A("Taurine", MED, MEDS, 1, "day", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, dur=1, details="1–2 g in the morning"),
        _A("Collagen peptides", MED, MEDS, 1, "day", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=1, details="15 g with vitamin C for connective tissue"),
        _A("Iron (fasted)", MED, MEDS, 3, "week", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.EMPTY_STOMACH, dur=1, details="On an empty stomach with vitamin C; away from calcium", prep="take fasted, 30 min before food; no coffee/dairy"),
        _A("Curcumin", MED, MEDS, 1, "day", W.EVENING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FAT, dur=1, details="500 mg with piperine + fat for absorption"),
        _A("Melatonin (travel)", MED, MEDS, 1, "month", W.BEFORE_BED, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, dur=1, details="0.5–1 mg, timed to the destination bedtime", prep="take ~30 min before target local bedtime"),
        _A("Vitamin C", MED, MEDS, 1, "day", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=1, details="500 mg with food"),
        _A("Fish oil (high-dose)", MED, MEDS, 3, "week", W.EVENING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FAT, dur=1, details="3 g on heavy-training days for recovery"),
        _A("Electrolyte tablets", MED, MEDS, 3, "week", W.MORNING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, dur=1, details="Sodium/potassium tab on long-session mornings"),
        _A("Psyllium fibre", MED, MEDS, 1, "day", W.EVENING, I.NONE, 0, False, "self", None, "res-home", TB.CONTINUE, meal=MR.WITH_FOOD, dur=1, details="5 g with a large glass of water"),
    ]

    # ---- Therapy / Therapies (technician-run equipment, or hands-on physio, or self at home) ----
    A += [
        _A("Sauna", THER, THERAP, 3, "week", W.EVENING, I.LOW, 3, False, "technician", "res-technician", "res-sauna", TB.SKIP, ["Hot bath"], dur=25, metrics=["duration", "HR"], details="80–90°C, 20–25 min, after training (heat-shock + recovery)"),
        _A("Cold plunge", THER, THERAP, 2, "week", W.MORNING, I.LOW, 3, False, "technician", "res-technician", "res-cryo", TB.SKIP, ["Cold shower"], dur=10, details="10–12°C, 2–3 min; not within 4h of hypertrophy work"),
        _A("Cryotherapy", THER, THERAP, 1, "week", W.MORNING, I.LOW, 3, False, "technician", "res-technician", "res-cryo", TB.SKIP, ["Cold plunge"], dur=5, details="−110°C whole-body, 3 min"),
        _A("Red-light therapy", THER, THERAP, 2, "week", W.EVENING, I.NONE, 1, False, "technician", "res-technician", "res-redlight", TB.SKIP, dur=20, details="660/850 nm panel, 10–20 min on bare skin"),
        _A("HBOT session", THER, THERAP, 1, "week", W.MIDDAY, I.NONE, 1, False, "technician", "res-technician", "res-hbot", TB.SKIP, dur=90, details="90 min at ~2.0 ATA"),
        _A("Sports massage", THER, THERAP, 1, "week", W.EVENING, I.LOW, 2, False, "physio", "res-physio", "res-clinic", TB.SKIP, dur=60, details="Deep-tissue, focus on training-stressed areas"),
        _A("Contrast therapy", THER, THERAP, 1, "week", W.EVENING, I.LOW, 3, False, "technician", "res-technician", "res-sauna", TB.SKIP, ["Sauna"], dur=30, details="Hot/cold alternation × 3–4 rounds, finish cold"),
        _A("Compression boots", THER, THERAP, 2, "week", W.BEFORE_BED, I.NONE, 1, False, "self", None, "res-home", TB.CONTINUE, dur=30, details="Pneumatic recovery boots, 30 min, legs elevated", skip=NO_SKIP),
        _A("Float tank", THER, THERAP, 1, "month", W.EVENING, I.NONE, 1, False, "technician", "res-technician", "res-clinic", TB.SKIP, dur=60, details="Sensory-deprivation float for nervous-system downshift"),
        _A("PEMF mat", THER, THERAP, 2, "week", W.BEFORE_BED, I.NONE, 1, False, "self", None, "res-home", TB.CONTINUE, dur=20, details="Low-frequency PEMF mat, 20 min pre-sleep", skip=NO_SKIP),
        _A("Breathwork session", THER, THERAP, 3, "week", W.BEFORE_BED, I.LOW, 1, False, "self", None, "res-home", TB.CONTINUE, dur=15, details="Slow nasal breathing / box breathing to lift HRV", skip=NO_SKIP),
        _A("Hot bath", THER, THERAP, 1, "month", W.BEFORE_BED, I.LOW, 2, False, "self", None, "res-home", TB.CONTINUE, dur=20, details="40°C bath 1–2h before bed to aid sleep onset", skip=NO_SKIP),
        _A("Cold shower", THER, THERAP, 1, "month", W.MORNING, I.LOW, 2, False, "self", None, "res-home", TB.CONTINUE, dur=5, details="2–3 min cold finish to a morning shower", skip=NO_SKIP),
        _A("Stretch therapy", THER, THERAP, 1, "week", W.EVENING, I.LOW, 2, False, "physio", "res-physio", "res-clinic", TB.SKIP, dur=45, details="Assisted stretching for hips/shoulders"),
        _A("Lymphatic massage", THER, THERAP, 1, "month", W.EVENING, I.LOW, 2, False, "physio", "res-physio", "res-clinic", TB.SKIP, dur=45, details="Light drainage massage to reduce swelling/fatigue"),
        _A("Acupuncture", THER, THERAP, 1, "month", W.MIDDAY, I.NONE, 1, False, "physio", "res-physio", "res-clinic", TB.SKIP, dur=45, details="Targeted needling for tension and recovery"),
    ]

    # ---- Consultation (clinicians; lab tests run by a lab technician) ----
    A += [
        _A("Physician review", CONS, DIAG, 1, "quarter", W.MORNING, I.NONE, 0, True, "physician", "res-physician", "res-clinic", TB.REMOTE, dur=45, prep="bring wearables export + latest labs", prio=2, metrics=["biomarkers"], details="Review biomarkers + wearable trends; adjust the protocol"),
        _A("Dietitian check-in", CONS, NUT, 1, "week", W.MIDDAY, I.NONE, 0, True, "dietitian", "res-dietitian", "res-clinic", TB.REMOTE, dur=30, prio=14, details="Weekly adherence + tweak macros and meal timing"),
        _A("Psychology session", CONS, MIND, 1, "week", W.MIDDAY, I.NONE, 0, True, "psychologist", "res-psychologist", "res-clinic", TB.REMOTE, dur=50, prio=6, metrics=["mood"], details="Stress + sleep psychology; CBT tools for a high-pressure calendar"),
        _A("Physio assessment", CONS, MOV, 1, "month", W.MIDDAY, I.NONE, 0, True, "physio", "res-physio", "res-clinic", TB.REMOTE, dur=45, prio=12, details="Movement quality + niggle check; update mobility work"),
        _A("Sports-medicine review", CONS, MOV, 1, "quarter", W.MIDDAY, I.NONE, 0, True, "sports-medicine", "res-sportsmd", "res-clinic", TB.REMOTE, dur=40, prio=11, details="Training-load review + injury-risk screen"),
        _A("Sleep consult", CONS, SLEEP, 1, "month", W.EVENING, I.NONE, 0, True, "physician", "res-physician", "res-clinic", TB.REMOTE, dur=40, prio=5, details="Review sleep stages/HRV; refine wind-down + light protocol"),
        _A("DEXA body composition", CONS, DIAG, 1, "quarter", W.MORNING, I.NONE, 0, False, "lab-technician", "res-labtech", "res-dexa", TB.SKIP, meal=MR.FASTED, dur=30, prep="fasted 3h; no exercise beforehand", prio=4, metrics=["body-fat %", "lean mass"], details="Whole-body scan: body-fat %, lean mass, visceral fat, bone density"),
        _A("VO2max lab retest", CONS, MOV, 1, "quarter", W.MORNING, I.MODERATE, 6, False, "lab-technician", "res-labtech", "res-vo2lab", TB.SKIP, dur=45, prep="no hard training 24h prior; bring HR strap", prio=7, metrics=["VO2max"], details="Graded treadmill test to exhaustion with gas analysis"),
        _A("Quarterly bloods", CONS, DIAG, 1, "quarter", W.MORNING, I.NONE, 0, False, "lab-technician", "res-labtech", "res-bloodlab", TB.SKIP, meal=MR.FASTED, dur=20, prep="fasted 12h; water only", prio=3, metrics=["ApoB", "HbA1c", "hsCRP"], details="Fasted panel: ApoB, HbA1c, hsCRP, lipids, metabolic markers"),
        _A("Brain health evaluation", CONS, MIND, 1, "quarter", W.MORNING, I.NONE, 0, True, "psychologist", "res-psychologist", "res-clinic", TB.REMOTE, dur=60, prio=8, details="Cognitive battery: memory, processing speed, attention"),
        _A("Cardiovascular test", CONS, DIAG, 1, "quarter", W.MORNING, I.MODERATE, 5, False, "physician", "res-physician", "res-clinic", TB.SKIP, dur=45, prio=5, details="Stress ECG + blood pressure response under load"),
        _A("CGM review", CONS, NUT, 1, "month", W.MIDDAY, I.NONE, 0, True, "dietitian", "res-dietitian", "res-clinic", TB.REMOTE, dur=30, prio=15, details="Read 2-week CGM traces; identify glucose-spiking foods"),
        _A("Skin check", CONS, DIAG, 1, "quarter", W.MIDDAY, I.NONE, 0, False, "physician", "res-physician", "res-clinic", TB.SKIP, dur=20, prio=18, details="Full-body mole/lesion mapping"),
        _A("Eye exam", CONS, DIAG, 1, "quarter", W.MIDDAY, I.NONE, 0, False, "physician", "res-physician", "res-clinic", TB.SKIP, dur=30, prio=18, details="Vision + retinal imaging (vascular health proxy)"),
        _A("Hormone panel review", CONS, DIAG, 1, "quarter", W.MORNING, I.NONE, 0, True, "physician", "res-physician", "res-clinic", TB.REMOTE, dur=30, prio=9, details="Testosterone, thyroid, cortisol — review + titrate"),
        _A("Cognitive coaching", CONS, MIND, 1, "month", W.MIDDAY, I.NONE, 0, True, "psychologist", "res-psychologist", "res-clinic", TB.REMOTE, dur=45, prio=13, details="Focus, decision-making and recovery-mindset coaching"),
        _A("Movement screen", CONS, MOV, 1, "month", W.MIDDAY, I.NONE, 0, True, "physio", "res-physio", "res-clinic", TB.REMOTE, dur=30, prio=16, details="FMS-style screen to flag asymmetries"),
        _A("Nutrition strategy review", CONS, NUT, 1, "month", W.MIDDAY, I.NONE, 0, True, "dietitian", "res-dietitian", "res-clinic", TB.REMOTE, dur=40, prio=14, details="Monthly strategy: targets, supplements, travel eating"),
    ]
    return A


def build_availability(start: date = date(2026, 6, 1)) -> Availability:
    commitments = ClientCommitments(
        sleep=("22:30", "06:30"),
        work_blocks=[(d, "09:00", "18:00") for d in range(5)],
        meals=["08:00", "13:00", "19:00"],
    )
    travel = [
        TravelTrip(start=date(2026, 6, 15), end=date(2026, 6, 19), destination="New York", timezone="America/New_York"),
        TravelTrip(start=date(2026, 7, 20), end=date(2026, 7, 24), destination="London", timezone="Europe/London"),
    ]
    return Availability(resources=RESOURCES, travel=travel, commitments=commitments)


# the member's action plan = priority-ordered subset (~30) of the catalog
ACTION_PLAN_IDS = [
    "act-physician-review", "act-quarterly-bloods", "act-dexa-body-composition",
    "act-sleep-consult", "act-psychology-session", "act-vo2max-lab-retest",
    "act-vo2max-intervals", "act-strength-full-body", "act-strength-legs",
    "act-zone-2-cardio-easy", "act-zone-2-cardio-moderate", "act-long-zone-2-ride",
    "act-mobility-flow", "act-sauna", "act-cold-plunge", "act-red-light-therapy",
    "act-breathwork-session", "act-vitamin-d3", "act-omega-3-capsules",
    "act-magnesium-glycinate", "act-creatine-monohydrate", "act-protein-forward-breakfast",
    "act-protein-forward-lunch", "act-protein-forward-dinner", "act-hydration-protocol",
    "act-no-caffeine-after-2pm", "act-dietitian-check-in", "act-physio-assessment",
    "act-hormone-panel-review", "act-eye-exercises",
]


def build_action_plan(catalog=None) -> list:
    catalog = catalog or build_catalog()
    by_id = {a.id: a for a in catalog}
    plan = [by_id[i] for i in ACTION_PLAN_IDS if i in by_id]
    return sorted(plan, key=lambda a: a.priority)
