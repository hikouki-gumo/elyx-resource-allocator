"""Generate + validate the sample data deliverables.

Writes:
  data/activities.json    — the catalog (100+ activities), all fields populated
  data/availability.json  — 3-month resource availability + travel + commitments

Run: python -m elyx_allocator.generate_data
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .catalog import build_catalog, build_availability
from .validate import validate


def _activities_payload(catalog):
    return [asdict(a) for a in catalog]


def _availability_payload(avail):
    return {
        "resources": {rid: asdict(r) for rid, r in avail.resources.items()},
        "travel": [asdict(t) for t in avail.travel],
        "commitments": asdict(avail.commitments) if avail.commitments else None,
    }


def main(out_dir: str = "data") -> dict:
    catalog = build_catalog()
    avail = build_availability()

    report = validate(catalog, avail.resources)
    if not report.ok:
        raise SystemExit("Catalog failed the realism gate:\n  " + "\n  ".join(report.errors))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "activities.json").write_text(
        json.dumps(_activities_payload(catalog), default=str, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (out / "availability.json").write_text(
        json.dumps(_availability_payload(avail), default=str, indent=2, ensure_ascii=False),
        encoding="utf-8")

    summary = {"activities": len(catalog), "resources": len(avail.resources),
               "travel_trips": len(avail.travel), "realistic": report.ok}
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
