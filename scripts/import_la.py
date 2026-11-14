"""Build a local intersection aggregate from LA's public legacy collision data."""
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ENDPOINT = "https://data.lacity.org/resource/d5tf-ez2w.json"
YEAR_START, YEAR_END = 2022, 2023
PAGE_SIZE = 1000
OUTPUT = Path(__file__).resolve().parents[1] / "public/data/la.json"


def records():
    offset = 0
    while True:
        query = urlencode({
            "$select": "date_occ,location,cross_street,location_1",
            "$where": (
                "area_name = 'Central' AND "
                f"date_occ >= '{YEAR_START}-01-01T00:00:00' AND "
                f"date_occ < '{YEAR_END + 1}-01-01T00:00:00'"
            ),
            "$order": "date_occ,dr_no",
            "$limit": PAGE_SIZE,
            "$offset": offset,
        })
        with urlopen(f"{ENDPOINT}?{query}", timeout=30) as response:
            page = json.load(response)
        yield from page
        if len(page) < PAGE_SIZE:
            return
        offset += PAGE_SIZE


def normalize_street(name):
    return " ".join(name.upper().split())


def main():
    groups = defaultdict(list)
    excluded = Counter()
    for row in records():
        names = sorted(normalize_street(row.get(key) or "") for key in ("location", "cross_street"))
        if not names[0] or names[0] == names[1]:
            excluded["missing or unusable street pair"] += 1
            continue
        try:
            point = row.get("location_1") or {}
            lat, lon = float(point["latitude"]), float(point["longitude"])
        except (KeyError, TypeError, ValueError):
            excluded["missing or invalid coordinates"] += 1
            continue
        # A coarse Central LA extent catches invalid geocodes. The source's
        # Central reporting-area filter determines which records are queried.
        if not (33.98 <= lat <= 34.13 and -118.33 <= lon <= -118.15):
            excluded["outside demo extent"] += 1
            continue
        groups[tuple(names)].append((lat, lon, row["date_occ"][:4]))

    sites = []
    for names, points in sorted(groups.items()):
        if len(points) < 3:
            excluded["street pairs with fewer than three reports"] += len(points)
            continue
        # Use the most frequently reported point as the map marker. Street
        # spellings remain as reported, so variants can form separate groups.
        locations = Counter((lat, lon) for lat, lon, _ in points)
        lat, lon = min(locations, key=lambda point: (-locations[point], point))
        sites.append({
            "name": " & ".join(names), "lat": lat, "lon": lon,
            "years": dict(Counter(year for _, _, year in points)),
        })
    if not sites:
        raise SystemExit("The public query returned no publishable intersection totals.")
    OUTPUT.parent.mkdir(exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps({"sites": sites, "excluded": sum(excluded.values())}))
    temporary.replace(OUTPUT)
    print(f"Imported {len(sites)} intersection aggregates. Excluded {sum(excluded.values())} reports.")


if __name__ == "__main__":
    main()
