"""Deterministic crash evidence and a small, reviewed official-guidance library."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHP_URL = "https://data.ca.gov/@california-highway-patrol/ccrs"
FHWA = "https://highways.dot.gov/safety/proven-safety-countermeasures/"
GUIDANCE = [
    {"id": "G-lighting", "title": "FHWA · Lighting", "url": FHWA + "lighting",
     "text": "Lighting can improve visibility along roads and at intersections and crossings. Review nighttime conditions and measured illumination before deciding whether lighting changes are warranted.",
     "prerequisites": "Night field review and illumination measurements; a daytime aerial image cannot establish lighting adequacy."},
    {"id": "G-crosswalk", "title": "FHWA · Crosswalk visibility enhancements", "url": FHWA + "crosswalk-visibility-enhancements",
     "text": "High-visibility markings, lighting, and signing can improve crossing visibility. Parked vehicles and other obstructions can limit sightlines. Markings alone may be inadequate for some multilane, high-volume crossings.",
     "prerequisites": "Verify crossing use, lane configuration, speeds, traffic volumes, and sightlines. A visible crosswalk does not prove safe operation."},
    {"id": "G-signals", "title": "FHWA · Backplates with retroreflective borders", "url": FHWA + "backplates-retroreflective-borders",
     "text": "Signal backplates with retroreflective borders can improve signal conspicuity in daytime and darkness.",
     "prerequisites": "Verify that signals exist and inspect approach visibility and existing equipment. A crash type alone does not establish a signal-visibility problem."},
    {"id": "G-lpi", "title": "FHWA · Leading pedestrian interval", "url": FHWA + "leading-pedestrian-interval",
     "text": "A leading pedestrian interval lets pedestrians establish their presence in a crosswalk before turning vehicles receive a green indication. FHWA discusses improved visibility and reduced pedestrian-turning conflicts.",
     "prerequisites": "Confirm signal control, pedestrian and turning movements, accessible pedestrian signals, and existing phase timing. Do not prescribe timing from imagery or predict a site-specific crash reduction."},
]
for item in GUIDANCE:
    item.update(kind="guidance", reviewed_at="2026-11-14", basis="Reviewed paraphrase of linked FHWA guidance; not a live web search")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def build_evidence(site, path=None):
    path = path or ROOT / "public/data/ccrs.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {"sites": {}, "near_ft": 150, "years": [2023, 2024]}
        unavailable = True
    else:
        unavailable = False
    records, seen = [], set()
    # No cross-site aggregation: aliases can share reports, but never count twice here.
    for index, original in enumerate(data["sites"].get(site["name"], [])):
        row = dict(original)
        identity = row.get("evidence_id")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        row["id"] = identity or "L-" + fingerprint([site["name"], index, original])[:16]
        row["location_group"] = ("uncertain" if row.get("offset_ft") is None else
                                 "junction" if row["offset_ft"] <= data["near_ft"] else "nearby road")
        records.append(row)
    sources = {}
    def fact(id_, title, value, record_ids):
        sources[id_] = {"id": id_, "kind": "statistic", "title": title, "value": value,
                        "text": f"{title}: {value}", "record_ids": record_ids, "url": CHP_URL,
                        "period": "2023–2024"}
    ids = [r["id"] for r in records]
    fact("S-total", "Matched CHP reports", len(records), ids)
    for group, id_ in [("junction", "S-junction"), ("nearby road", "S-nearby"), ("uncertain", "S-uncertain")]:
        subset = [r for r in records if r["location_group"] == group]
        fact(id_, f"Reports assigned to {group}", len(subset), [r["id"] for r in subset])
    for key in ("injured", "killed"):
        known = [r for r in records if isinstance(r.get(key), (int, float)) and r[key] >= 0]
        fact(f"S-{key}", f"People {key} in records with known values", sum(r[key] for r in known), [r["id"] for r in known])
        fact(f"S-{key}-missing", f"Reports missing {key} count", len(records)-len(known), [r["id"] for r in records if r not in known])
    injury = [r for r in records if (r.get("injured") or 0) > 0]
    fact("S-injury-crashes", "Reports with people injured", len(injury), [r["id"] for r in injury])
    for field in ("type", "light", "involved_with", "year"):
        counts = Counter(str(r.get(field) or "Not recorded") for r in records)
        for index, (value, total) in enumerate(sorted(counts.items())):
            subset = [r["id"] for r in records if str(r.get(field) or "Not recorded") == value]
            fact(f"S-{field}-{index}", f"Reports · {field.replace('_', ' ')} · {value}", total, subset)
    for row in records:
        sources[row["id"]] = {"id": row["id"], "kind": "crash", "title": f"{row.get('when', 'Unknown date')} · {row.get('type') or 'Unknown type'}",
                              "url": CHP_URL, "period": "2023–2024", "record": row}
    sources.update({item["id"]: dict(item) for item in GUIDANCE})
    sources["E-location"] = {"id": "E-location", "kind": "context", "title": "Location and evidence limits",
        "text": "Street-name matches may be ambiguous. Junction screening uses reported offsets, not surveyed crash coordinates. The aerial center is a representative historical LAPD point. Traffic volumes, speed measurements, signal timing, and surveyed widths are unavailable. No cause or risk per trip is established.",
        "url": CHP_URL}
    return {"site": {k: site[k] for k in ("name", "lat", "lon")}, "period": "2023–2024",
            "records": records, "sources": sources, "near_ft": data["near_ft"],
            "source_version": fingerprint(data), "retrieved_at": data.get("retrieved_at", "Legacy import; retrieval time unavailable"),
            "unavailable": unavailable, "provenance_complete": all(r.get("evidence_id") for r in records)}
