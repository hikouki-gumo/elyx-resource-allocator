"""Unit tests — the realism gate (validate.py).

'Realistic' is defined as: passes all five rules.
"""
from elyx_allocator.validate import (
    check_field_coherence, check_referential_integrity, check_variety,
    check_distribution, validate,
)
from elyx_allocator.models import ActivityType, Pillar, MealRelation, Window, Intensity
from tests.conftest import make_activity, make_resource


# ---- field coherence ----
def test_coherent_activity_has_no_coherence_errors():
    assert check_field_coherence(make_activity()) == []


def test_food_activity_with_trainer_facilitator_is_incoherent():
    a = make_activity(
        id="act-lunch", name="Protein lunch", type=ActivityType.FOOD,
        pillar=Pillar.NUTRITION, facilitator={"role": "trainer", "id": "res-trainer"},
        location="home",
    )
    assert check_field_coherence(a) != []


def test_sauna_therapy_cannot_be_remote():
    a = make_activity(
        id="act-sauna", name="Sauna", type=ActivityType.THERAPY,
        pillar=Pillar.THERAPIES, facilitator={"role": "technician", "id": "res-technician"},
        location="res-sauna", remote_capable=True,
    )
    assert check_field_coherence(a) != []


# ---- referential integrity ----
def test_backup_referencing_unknown_activity_fails():
    catalog = [make_activity(id="act-strength", backups=["act-missing"])]
    resources = {"res-trainer": make_resource(id="res-trainer")}
    errors = check_referential_integrity(catalog, resources)
    assert any("act-missing" in e for e in errors)


def test_facilitator_not_in_resources_fails():
    catalog = [make_activity(id="act-strength", backups=[],
                             facilitator={"role": "trainer", "id": "res-ghost"})]
    errors = check_referential_integrity(catalog, {})
    assert any("res-ghost" in e for e in errors)


# ---- variety ----
def test_duplicate_names_fail_variety():
    catalog = [make_activity(id=f"a{i}", name="Same Thing", backups=[]) for i in range(10)]
    assert check_variety(catalog) != []


def test_distinct_names_pass_variety():
    catalog = [make_activity(id=f"a{i}", name=f"Thing {i}", backups=[]) for i in range(10)]
    assert check_variety(catalog) == []


# ---- distribution ----
def test_single_type_catalog_fails_distribution():
    catalog = [make_activity(id=f"a{i}", name=f"Run {i}", backups=[]) for i in range(20)]
    assert check_distribution(catalog) != []  # 100% fitness > 40% cap


def _balanced_catalog():
    """2 of each type, distinct names, human/self facilitators + location ids — passes all rules."""
    specs = [
        (ActivityType.FITNESS, Pillar.MOVEMENT, "trainer", "res-trainer", "res-gym"),
        (ActivityType.FOOD, Pillar.NUTRITION, "self", None, "res-home"),
        (ActivityType.MEDICATION, Pillar.MEDS, "self", None, "res-home"),
        (ActivityType.THERAPY, Pillar.THERAPIES, "technician", "res-technician", "res-sauna"),
        (ActivityType.CONSULTATION, Pillar.DIAGNOSTICS, "physician", "res-physician", "res-clinic"),
    ]
    out = []
    for t, p, role, fid, loc in specs:
        for n in range(2):
            out.append(make_activity(
                id=f"{t.value}-{n}", name=f"{t.value.title()} {n}",
                type=t, pillar=p, backups=[],
                facilitator={"role": role, "id": fid}, location=loc,
                remote_capable=(t in (ActivityType.CONSULTATION, ActivityType.FOOD)),
            ))
    return out


def test_balanced_catalog_validates_ok():
    catalog = _balanced_catalog()
    resources = {r: make_resource(id=r) for r in
                 ("res-trainer", "res-technician", "res-physician", "res-gym", "res-home",
                  "res-sauna", "res-clinic")}
    report = validate(catalog, resources)
    assert report.ok, report.errors
