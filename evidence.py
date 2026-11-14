"""Deterministic crash evidence and a small, reviewed official-guidance library."""
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHP_URL = "https://data.ca.gov/@california-highway-patrol/ccrs"
FHWA = "https://highways.dot.gov/safety/proven-safety-countermeasures/"
EPRIMER = "https://highways.dot.gov/safety/speed-management/traffic-calming-eprimer"
GUIDANCE = [
    {"id": "G-lighting", "title": "FHWA · Lighting", "url": FHWA + "lighting",
     "targets": "Crashes in darkness; pedestrian and intersection crashes at night.",
     "text": "Lighting can improve visibility along roads and at intersections and crossings. Review nighttime conditions and measured illumination before deciding whether lighting changes are warranted.",
     "prerequisites": "Night field review and illumination measurements; a daytime aerial image cannot establish lighting adequacy."},
    {"id": "G-crosswalk", "title": "FHWA · Crosswalk visibility enhancements", "url": FHWA + "crosswalk-visibility-enhancements",
     "targets": "Pedestrian crashes at marked or unmarked crossings.",
     "text": "High-visibility markings, lighting, and signing can improve crossing visibility. Parked vehicles and other obstructions can limit sightlines. Markings alone may be inadequate for some multilane, high-volume crossings.",
     "prerequisites": "Verify crossing use, lane configuration, speeds, traffic volumes, and sightlines. A visible crosswalk does not prove safe operation."},
    {"id": "G-signals", "title": "FHWA · Backplates with retroreflective borders", "url": FHWA + "backplates-retroreflective-borders",
     "targets": "Red-light running, broadside and rear-end crashes at signals.",
     "text": "Signal backplates with retroreflective borders can improve signal conspicuity in daytime and darkness.",
     "prerequisites": "Verify that signals exist and inspect approach visibility and existing equipment. A crash type alone does not establish a signal-visibility problem."},
    {"id": "G-lpi", "title": "FHWA · Leading pedestrian interval", "url": FHWA + "leading-pedestrian-interval",
     "targets": "Pedestrians struck by turning vehicles at signals.",
     "text": "A leading pedestrian interval lets pedestrians establish their presence in a crosswalk before turning vehicles receive a green indication. FHWA discusses improved visibility and reduced pedestrian-turning conflicts.",
     "prerequisites": "Confirm signal control, pedestrian and turning movements, accessible pedestrian signals, and existing phase timing. Do not prescribe timing from imagery or predict a site-specific crash reduction."},
    {"id": "G-chicane", "title": "FHWA · Traffic calming: chicanes and lateral shifts", "url": EPRIMER,
     "targets": "Speed-related crashes: rear-end, hit-object and severe-injury crashes on straight approaches.",
     "text": "Horizontal deflection such as chicanes and lateral shifts introduces deliberate curves so drivers cannot hold a straight high-speed path and naturally slow down. It is used mainly on lower-volume streets and needs room for emergency vehicles, buses, drainage and cyclists.",
     "prerequisites": "Measure operating speeds and volumes, confirm street classification, transit and emergency routes, and check available width. Not normally applied to major arterials without a wider corridor redesign."},
    {"id": "G-road-diet", "title": "FHWA · Road diets (roadway reconfiguration)", "url": FHWA + "road-diets-roadway-configuration",
     "targets": "Rear-end, sideswipe and left-turn crashes on undivided multilane streets; multilane pedestrian crossings.",
     "text": "A road diet reallocates travel lanes, typically converting a four-lane undivided street to two through lanes with a centre turn lane, freeing width for bike lanes, parking or refuge islands. It reduces vehicle-to-vehicle conflict points and the number of lanes a pedestrian must cross.",
     "prerequisites": "Check daily traffic volumes, peak turning counts, transit operations and signal spacing before judging feasibility."},
    {"id": "G-roundabout", "title": "FHWA · Roundabouts", "url": FHWA + "roundabouts",
     "targets": "Broadside (angle) and head-on crashes; severe-injury crashes at intersections.",
     "text": "A roundabout replaces crossing conflicts with low-speed curved entries that all drivers must negotiate, removing the high-speed right-angle conflict. FHWA lists it as a proven countermeasure for severe intersection crashes.",
     "prerequisites": "Needs right-of-way, capacity analysis, pedestrian and cyclist accommodation, and a check of large-vehicle turning paths. Dense urban corners often lack the space."},
    {"id": "G-median", "title": "FHWA · Medians and pedestrian refuge islands", "url": FHWA + "medians-and-pedestrian-refuge-islands-urban-and-suburban-areas",
     "targets": "Pedestrian crashes on wide streets; head-on and left-turn crashes.",
     "text": "Raised medians and refuge islands separate opposing traffic and let pedestrians cross one direction at a time. They can also restrict risky turning movements.",
     "prerequisites": "Confirm available width, driveway and turn access needs, and emergency access."},
    {"id": "G-left-turn", "title": "FHWA · Dedicated left- and right-turn lanes at intersections", "url": FHWA + "dedicated-left-and-right-turn-lanes-intersections",
     "targets": "Rear-end crashes behind turning vehicles; left-turn broadside crashes.",
     "text": "Dedicated turn lanes separate turning vehicles from through traffic, reducing rear-end conflicts. Paired with protected signal phasing, left turns no longer cross oncoming traffic on a permissive green.",
     "prerequisites": "Turning-movement counts, queue lengths, existing signal phasing and available width."},
    {"id": "G-yellow", "title": "FHWA · Yellow change intervals", "url": FHWA + "yellow-change-intervals",
     "targets": "Red-light running, broadside and rear-end crashes at signals.",
     "text": "Appropriately timed yellow change intervals reduce red-light running and the abrupt stops that lead to rear-end crashes.",
     "prerequisites": "Obtain existing signal timing and approach speeds from the operating agency."},
    {"id": "G-raised", "title": "FHWA · Traffic calming: raised crosswalks and raised intersections", "url": EPRIMER,
     "targets": "Pedestrian crashes and speed-related crashes on lower-speed streets.",
     "text": "Raised crosswalks and raised intersections use vertical deflection to slow vehicles where pedestrians cross and make the crossing more prominent.",
     "prerequisites": "Check street classification, transit and emergency routes, drainage and operating speeds."},
    {"id": "G-curb-ext", "title": "FHWA · Traffic calming: curb extensions and corner daylighting", "url": EPRIMER,
     "targets": "Pedestrian crashes, turning crashes and sightline problems near corners.",
     "text": "Curb extensions narrow the roadway at the corner, shorten crossings, slow turning vehicles and keep parked cars from blocking sightlines between drivers and people crossing.",
     "prerequisites": "Check turning paths for buses and trucks, drainage, parking loss and bike-lane continuity."},
    {"id": "G-speed", "title": "FHWA · Appropriate speed limits for all road users", "url": FHWA + "appropriate-speed-limits-all-road-users",
     "targets": "Severe crashes of any type where speed is a factor.",
     "text": "Setting speed limits that reflect the street's context and vulnerable users, supported by design changes that make the intended speed feel natural, reduces crash severity.",
     "prerequisites": "Speed study and the legal framework for setting limits; a limit change alone often needs supporting design changes."},
]
for item in GUIDANCE:
    item.update(kind="guidance", reviewed_at="2026-11-14", basis="Summary of the linked FHWA guidance; not a live web search. Verify against the source before relying on it")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _when(row):
    try:
        return datetime.fromisoformat(str(row.get("when")).replace("Z", ""))
    except (TypeError, ValueError):
        return None


def time_band(row):
    when = _when(row)
    if when is None:
        return "Not recorded"
    hour = when.hour
    return ("Late night (9 pm–6 am)" if hour >= 21 or hour < 6 else "Morning peak (6–10 am)" if hour < 10
            else "Midday (10 am–3 pm)" if hour < 15 else "Afternoon peak (3–7 pm)" if hour < 19 else "Evening (7–9 pm)")


def day_band(row):
    when = _when(row)
    return "Not recorded" if when is None else "Weekend" if when.weekday() >= 5 else "Weekday"


_SIM = {"mtime": None, "data": None, "ranks": {}}


def _simulation():
    """Load the summarised SUMO run once per file version."""
    path = ROOT / "public/data/sim.json"
    try:
        mtime = path.stat().st_mtime
        if _SIM["mtime"] != mtime:
            data = json.loads(path.read_text())
            ranks = {}
            for period in data["periods"]:
                ranks[period] = sorted(s["data"][period]["idle_s"] for s in data["segments"].values()
                                       if period in s["data"] and s["class"] != "motorway" and s["data"][period]["flow"] >= 100)
            _SIM.update(mtime=mtime, data=data, ranks=ranks)
    except (OSError, ValueError, KeyError):
        return None
    return _SIM


def simulation_sources(site_name):
    """Simulated idling and emissions on each approach to this intersection, as citable sources."""
    sim = _simulation()
    if not sim or site_name not in sim["data"]["sites"]:
        return []
    data, basis = sim["data"], {"counted": "volume from an LADOT count", "assumed": "assumed volume", "unconstrained": "no volume target"}
    method = data["method"]
    sources = [{"id": "T-method", "kind": "simulation", "title": "How the traffic simulation was built",
                "text": f"{method['engine']}. Traffic: {method['demand']}. {method['signals']}. Emissions: {method['emission_model']}. {method['caveat']}"}]
    for period, info in data["periods"].items():
        ranks = sim["ranks"][period]
        for index, edge_id in enumerate(data["sites"][site_name]):
            segment = data["segments"].get(edge_id)
            d = segment and segment["data"].get(period)
            if not d:
                continue
            worse_than = round(100 * sum(v < d["idle_s"] for v in ranks) / len(ranks)) if ranks else None
            text = (f"Simulated, {info['label'].lower()}: {segment['name']} {segment['dir']} approach, {segment['lanes']} lanes, {basis[d['basis']]}. "
                    f"{d['flow']} vehicles an hour; {d['idle_s']} seconds stopped per vehicle; {round(d['stopped_share'] * 100)}% of time on the approach spent stopped; "
                    f"speed {d['speed_kmh']} km/h, {round(d['speed_ratio'] * 100)}% of free flow; {d['co2_g_vkm']} g CO2 per vehicle-km; "
                    f"{d['co2_kg_km']} kg CO2 and {d['nox_g_km']} g NOx per km of road in the hour."
                    + (f" Idling per vehicle is higher than on {worse_than}% of simulated road segments." if worse_than is not None else "")
                    + (" Flagged causes: " + " ".join(c["text"] for c in d["causes"]) if d["causes"] else " No idling cause flagged."))
            sources.append({"id": f"T-{'pm' if period == 'pm_peak' else period[:3]}-{index}", "kind": "simulation",
                            "title": f"Simulated traffic · {info['label']} · {segment['name']} {segment['dir']}", "text": text,
                            "period": info["label"], "approach": f"{segment['name']} {segment['dir']}", "values": {k: v for k, v in d.items() if k != "causes"},
                            "causes": [c["code"] for c in d["causes"]]})
    return sources if len(sources) > 1 else []


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
    total_records = len(records)
    def fact(id_, title, value, record_ids, of=None):
        of = total_records if of is None else of
        text = f"{title}: {value}" + (f" of {of} matched reports" if of and id_ != "S-total" else "")
        sources[id_] = {"id": id_, "kind": "statistic", "title": title, "value": value,
                        "text": text, "record_ids": record_ids, "url": CHP_URL,
                        "period": "2023–2024"}
    def breakdown(prefix, label, key):
        counts = Counter(key(r) for r in records)
        for index, (value, total) in enumerate(sorted(counts.items())):
            fact(f"{prefix}-{index}", f"Reports · {label} · {value}", total, [r["id"] for r in records if key(r) == value])
    ids = [r["id"] for r in records]
    fact("S-total", "Matched CHP reports", len(records), ids)
    for group, id_ in [("junction", "S-junction"), ("nearby road", "S-nearby"), ("uncertain", "S-uncertain")]:
        subset = [r for r in records if r["location_group"] == group]
        fact(id_, f"Reports assigned to {group}", len(subset), [r["id"] for r in subset])
    for key in ("injured", "killed"):
        known = [r for r in records if isinstance(r.get(key), (int, float)) and r[key] >= 0]
        fact(f"S-{key}", f"People {key} in records with known values", sum(r[key] for r in known), [r["id"] for r in known], of=0)
        fact(f"S-{key}-missing", f"Reports missing {key} count", len(records)-len(known), [r["id"] for r in records if r not in known])
    injury = [r for r in records if (r.get("injured") or 0) > 0 or (r.get("killed") or 0) > 0]
    fact("S-injury-crashes", "Reports with people injured or killed", len(injury), [r["id"] for r in injury])
    for field in ("type", "light", "involved_with", "year"):
        breakdown(f"S-{field}", field.replace("_", " "), lambda r, field=field: str(r.get(field) or "Not recorded"))
    breakdown("S-time", "time of day", time_band)
    breakdown("S-day", "day", day_band)
    breakdown("S-road", "reported on", lambda r: str(r.get("road_label") or r.get("road") or "Not recorded"))
    # Which collision types carry the injuries: the pattern a redesign should target.
    for index, (value, total) in enumerate(sorted(Counter(str(r.get("type") or "Not recorded") for r in injury).items())):
        subset = [r["id"] for r in injury if str(r.get("type") or "Not recorded") == value]
        fact(f"S-injury-type-{index}", f"Injury or fatal reports · type · {value}", total, subset, of=0)
    history = site.get("years") or {}
    if history:
        sources["H-lapd"] = {"id": "H-lapd", "kind": "context", "title": "LAPD historical report counts (separate source)",
            "text": "LAPD legacy collision reports naming this street pair: " + ", ".join(f"{year}: {n}" for year, n in sorted(history.items()))
                    + ". A different source and period from the CHP records; never add the two together.",
            "url": "https://data.lacity.org/Public-Safety/Traffic-Collision-Data-from-2010-to-Present/d5tf-ez2w/about_data"}
    for row in records:
        sources[row["id"]] = {"id": row["id"], "kind": "crash", "title": f"{row.get('when', 'Unknown date')} · {row.get('type') or 'Unknown type'}",
                              "url": CHP_URL, "period": "2023–2024", "record": row}
    sources.update({item["id"]: dict(item) for item in GUIDANCE})
    sources.update({item["id"]: item for item in simulation_sources(site["name"])})
    sources["E-location"] = {"id": "E-location", "kind": "context", "title": "Location and evidence limits",
        "text": "Street-name matches may be ambiguous. Junction screening uses reported offsets, not surveyed crash coordinates. The aerial center is a representative historical LAPD point. Traffic volumes, speed measurements, signal timing, and surveyed widths are unavailable. No cause or risk per trip is established.",
        "url": CHP_URL}
    if site.get("featured"):
        sources["E-location"]["text"] = ("The junction center is from City of Los Angeles street centerlines. "
            "Street-name crash matches may be ambiguous. Traffic volumes, signal timing and surveyed widths are unavailable.")
    return {"site": {k: site[k] for k in ("name", "lat", "lon")}, "period": "2023–2024",
            "records": records, "sources": sources, "near_ft": data["near_ft"],
            "source_version": fingerprint(data), "retrieved_at": data.get("retrieved_at", "Legacy import; retrieval time unavailable"),
            "unavailable": unavailable, "provenance_complete": all(r.get("evidence_id") for r in records)}
