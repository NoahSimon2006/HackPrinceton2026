"""Fetch public CCRS crash fields and index reports for the demo's street pairs."""
import json
import hashlib
from datetime import datetime, timezone
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public/data"
API = "https://publish.data.ca.gov/api/3/action/datastore_search_sql"
RESOURCES = {
    2023: "436642c0-cd04-4a4c-b45e-564b66437476",
    2024: "f775df59-b89b-4f82-bd3d-8807fa3a22a0",
}
FIELDS = (
    "_id", "Collision Id", "Report Version", "IsDeleted", "Crash Date Time",
    "PrimaryRoad", "SecondaryRoad", "SecondaryDistance", "SecondaryUnitOfMeasure",
    "NumberInjured", "NumberKilled", "Collision Type Description", "LightingDescription",
    "MotorVehicleInvolvedWithDesc",
)
SUFFIXES = {
    "ST": "ST", "STREET": "ST", "AVE": "AVE", "AV": "AVE", "AVENUE": "AVE",
    "BLVD": "BLVD", "BOULEVARD": "BLVD", "RD": "RD", "ROAD": "RD",
    "DR": "DR", "DRIVE": "DR", "PL": "PL", "PLACE": "PL", "CT": "CT", "WAY": "WAY",
}
DIRECTIONS = dict(zip(("NORTH", "SOUTH", "EAST", "WEST", "N", "S", "E", "W"), "NSEWNSEW"))
NEAR_FT = 150
PAGE_SIZE = 3000


def street_key(name):
    words = re.findall(r"[A-Z0-9]+", (name or "").upper())
    direction = DIRECTIONS.get(words[0], "") if len(words) > 1 else ""
    if direction:
        words.pop(0)
    suffix = SUFFIXES.get(words[-1], "") if len(words) > 1 else ""
    if suffix:
        words.pop()
    return " ".join(words), direction, suffix


def same_street(a, b):
    return a[0] == b[0] and all(not x or not y or x == y for x, y in zip(a[1:], b[1:]))


def offset_ft(row):
    raw = row["SecondaryDistance"]
    unit = (row["SecondaryUnitOfMeasure"] or "").strip().upper()
    if not isinstance(raw, (int, float)) or not 0 <= raw < float("inf"):
        return None
    if raw == 0 or unit in {"F", "FT", "FEET"}:
        return round(raw)
    if unit in {"MI", "MILE", "MILES"}:
        return round(raw * 5280)
    return None


def fetch_year(item):
    year, resource = item
    columns = ", ".join(f'"{field}"' for field in FIELDS)
    cursor = 0
    latest = {}
    while True:
        sql = (
            f'SELECT {columns} FROM "{resource}" WHERE "_id" > {cursor} '
            """AND "City Name" = 'Los Angeles' """
            f'ORDER BY "_id" LIMIT {PAGE_SIZE}'
        )
        with urlopen(f"{API}?{urlencode({'sql': sql})}", timeout=35) as response:
            payload = json.load(response)
        if not payload.get("success"):
            raise RuntimeError(f"CCRS query failed for {year}")
        rows = payload["result"]["records"]
        for row in rows:
            record_id = row["Collision Id"]
            if record_id is None:
                continue
            previous = latest.get(record_id)
            if previous is None or (row["Report Version"] or 0) >= (previous["Report Version"] or 0):
                latest[record_id] = row
        if len(rows) < PAGE_SIZE:
            return year, latest.values()
        cursor = rows[-1]["_id"]


def main():
    sites = json.loads((DATA / "la.json").read_text())["sites"]
    street_pairs = {}
    for site in sites:
        streets = site["name"].split(" & ")
        if len(streets) != 2:
            continue
        pair = tuple(sorted(map(street_key, streets)))
        if pair[0][0] != pair[1][0]:
            street_pairs.setdefault(tuple(key[0] for key in pair), []).append((site["name"], pair))

    results = {site["name"]: [] for site in sites}
    provenance = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for year, rows in pool.map(fetch_year, RESOURCES.items()):
            for row in rows:
                if str(row["IsDeleted"]).strip().upper() in {"TRUE", "T", "YES", "Y", "1"}:
                    continue
                primary, cross = row["PrimaryRoad"], row["SecondaryRoad"]
                pair = tuple(sorted(map(street_key, (primary, cross))))
                candidates = street_pairs.get(tuple(key[0] for key in pair), [])
                for name, site_pair in candidates:
                    if not all(same_street(a, b) for a, b in zip(pair, site_pair)):
                        continue
                    distance = offset_ft(row)
                    road_label = next(street for street in name.split(" & ")
                                      if same_street(street_key(street), street_key(primary)))
                    evidence_id = "C-" + hashlib.sha256(f"{year}:{row['Collision Id']}".encode()).hexdigest()[:16]
                    provenance[evidence_id] = {
                        "resource": RESOURCES[year], "collision_id": row["Collision Id"],
                        "report_version": row["Report Version"], "source_row": row["_id"],
                    }
                    results[name].append({
                        "evidence_id": evidence_id,
                        "year": year, "when": row["Crash Date Time"], "road": " ".join(primary.split()),
                        "road_label": road_label,
                        "cross": " ".join(cross.split()), "offset_ft": distance,
                        "type": row["Collision Type Description"], "light": row["LightingDescription"],
                        "involved_with": row["MotorVehicleInvolvedWithDesc"],
                        "injured": row["NumberInjured"], "killed": row["NumberKilled"],
                    })

    if not any(results.values()):
        raise SystemExit("CCRS returned no matching street pairs. No local data was replaced.")
    for rows in results.values():
        rows.sort(key=lambda row: row["when"] or "", reverse=True)
    output = DATA / "ccrs.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps({"near_ft": NEAR_FT, "years": list(RESOURCES), "sites": results,
                                    "retrieved_at": datetime.now(timezone.utc).isoformat(), "resources": RESOURCES}))
    temporary.replace(output)
    private = ROOT / "private"
    private.mkdir(exist_ok=True)
    lookup = private / "ccrs-provenance.json"
    lookup.write_text(json.dumps(provenance))
    lookup.chmod(0o600)
    matches = sum(bool(rows) for rows in results.values())
    print(f"Imported CCRS crash histories for {matches} of {len(results)} selectable street pairs.")


if __name__ == "__main__":
    main()
