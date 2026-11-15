"""Parse official LADOT count sheets (public PDFs on NavigateLA) into checked numbers.

Two sheet types are supported:
- Manual traffic count summaries: per-approach left/through/right vehicles for each
  counted hour (normally 7-10 AM and 3-6 PM), plus crosswalk pedestrian counts.
- Automatic 24-hour volume sheets: 15-minute vehicle counts by direction.

Every sheet carries its own row and column totals. A sheet is accepted only when the
parsed numbers reproduce every printed total; otherwise it is rejected, never repaired.
Names of count staff printed on the sheets are not stored.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://navigatela.lacity.org/dot/traffic_data"
FOLDERS = {"MAN": "manual_counts", "AUTO": "automatic_counts"}
SUFFIXES = r"\b(STREET|ST|AVENUE|AVE|AV|BOULEVARD|BLVD|BL|PLACE|PL|DRIVE|DR|ROAD|RD|WAY|WY)\.?$"
HOURS = ("7-8", "8-9", "9-10", "3-4", "4-5", "5-6")
MOVES = ("left", "through", "right")


class SheetError(ValueError):
    """Sheet missing, unreadable, or its printed totals do not reproduce."""


def street_token(name: str) -> str:
    """'1 st ST' -> '1ST', 'SAN PEDRO ST' -> 'SANPEDRO' (NavigateLA file naming)."""
    text = re.sub(r"\(.*?\)", "", name.upper()).strip()
    text = re.sub(r"^(N|S|E|W|NORTH|SOUTH|EAST|WEST)\s+", "", text)
    text = re.sub(SUFFIXES, "", text.strip()).strip()
    text = re.sub(r"\b(\d+)\s*(ST|ND|RD|TH)\b", r"\1\2", text)
    return re.sub(r"[^A-Z0-9]", "", text)


def sheet_names(primary: str, cross: str, count_date: str, kind: str) -> list[str]:
    stamp = datetime.fromisoformat(count_date[:10]).strftime("%y%m%d")
    a, b = street_token(primary), street_token(cross)
    suffix = "MAN" if kind == "MAN" else "AUTO"
    return [f"{x}.{y}.{stamp}-{suffix}.pdf" for x, y in ((a, b), (b, a))]


def sheet_url(filename: str) -> str:
    kind = "MAN" if filename.endswith("-MAN.pdf") else "AUTO"
    return f"{BASE}/{FOLDERS[kind]}/{filename}"


def fetch_sheet(filename: str, cache: Path, *, timeout=12) -> bytes:
    """Download once into the ignored cache; a 404 raises SheetError."""
    path = cache / filename
    missing = cache / (filename + ".missing")
    if path.exists():
        return path.read_bytes()
    if missing.exists():
        raise SheetError("Sheet not published (404, cached).")
    request = Request(sheet_url(filename), headers={"User-Agent": "SustainabilityMap/0.2 research prototype"})
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read(5_000_001)
    except HTTPError as error:
        if error.code == 404:
            cache.mkdir(parents=True, exist_ok=True)
            missing.write_text("404")
        raise SheetError(f"Sheet not published ({error.code}).") from None
    except (URLError, TimeoutError, OSError):
        raise SheetError("NavigateLA could not be reached.") from None
    if len(data) > 5_000_000 or not data.startswith(b"%PDF"):
        raise SheetError("Response is not a count sheet PDF.")
    cache.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def sheet_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _ints(tokens):
    return [int(t.replace(",", "")) for t in tokens]


def _check(condition, message):
    if not condition:
        raise SheetError(message)


def parse_manual(text: str) -> dict:
    """Return approaches {nb,sb,eb,wb} -> {hour -> {left,through,right}} with checks."""
    _check("MANUAL TRAFFIC COUNT SUMMARY" in text, "Not a manual count summary.")
    ns = re.search(r"North/South\s+(.+)", text)
    ew = re.search(r"East/West\s+(.+)", text)
    _check(ns and ew, "Street names missing.")
    found_date = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})\s*([A-Z]+DAY)", text)
    _check(found_date, "Count date missing.")
    counted = datetime.strptime(found_date.group(1), "%B %d, %Y").date()
    row = re.compile(r"^(7-8|8-9|9-10|3-4|4-5|5-6|10-11|11-12|12-1|1-2|2-3|6-7|TOTAL)\s+((?:[\d,]+\s+){4})"
                     r"\1\s+((?:[\d,]+\s+){4})([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s*$")
    tables, current = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("NORTHBOUND Approach", "EASTBOUND Approach")):
            current = {"rows": {}, "first": line.split()[0]}
            tables.append(current)
            continue
        match = row.match(line + " ") if current is not None else None
        if match:
            first, second = _ints(match.group(2).split()), _ints(match.group(3).split())
            combined, *peds = _ints(match.groups()[3:])
            _check(match.group(1) not in current["rows"], "Duplicate hour or TOTAL row in manual count.")
            current["rows"][match.group(1)] = (first, second, combined, peds)
    _check(len(tables) == 2 and tables[0]["first"] == "NORTHBOUND" and tables[1]["first"] == "EASTBOUND",
           "Expected north/south and east/west approach tables.")
    approaches, crossings, hours = {}, {}, None
    for table, (one, two), (ped_one, ped_two) in zip(
            tables, (("nb", "sb"), ("eb", "wb")), (("south_leg", "north_leg"), ("west_leg", "east_leg"))):
        rows = table["rows"]
        _check("TOTAL" in rows and len(rows) >= 2, "Approach table rows missing.")
        table_hours = [h for h in rows if h != "TOTAL"]
        hours = hours or table_hours
        _check(table_hours == hours, "Approach tables cover different hours.")
        for name in (one, two):
            approaches[name] = {}
        crossings[ped_one], crossings[ped_two] = {}, {}
        for hour in table_hours:
            first, second, combined, peds = rows[hour]
            for name, values in ((one, first), (two, second)):
                _check(sum(values[:3]) == values[3], f"{name.upper()} {hour}: movements do not sum to the printed total.")
                approaches[name][hour] = dict(zip(MOVES, values[:3]))
            _check(first[3] + second[3] == combined, f"{hour}: approach totals do not sum to the printed combined total.")
            crossings[ped_one][hour], crossings[ped_two][hour] = peds[0], peds[2]
        first, second, combined, peds = rows["TOTAL"]
        for name, values in ((one, first), (two, second)):
            _check(sum(values[:3]) == values[3], f"{name.upper()}: printed TOTAL movement columns do not sum to its total.")
            for index, move in enumerate(MOVES):
                _check(sum(approaches[name][h][move] for h in table_hours) == values[index],
                       f"{name.upper()} {move}: hourly values do not sum to the printed column total.")
        _check(first[3] + second[3] == combined and sum(rows[h][2] for h in table_hours) == combined,
               "Combined column total does not reproduce.")
        _check(all(sum(rows[h][3][i] for h in table_hours) == peds[i] for i in range(4)),
               "Pedestrian or school-crossing totals do not reproduce.")
    heavy = {}
    for label, key in (("DUAL-\nWHEELED", "dual_wheeled"), ("BUSES", "buses"), ("BIKES", "bikes")):
        found = re.search(re.escape(label) + r"\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)", text)
        if found:
            heavy[key] = dict(zip(("nb", "sb", "eb", "wb"), _ints(found.groups())))
    return {"kind": "manual", "north_south": ns.group(1).strip(), "east_west": ew.group(1).strip(),
            "date": counted.isoformat(), "weekday": found_date.group(2), "hours": hours,
            "approaches": approaches, "pedestrians": crossings, "heavy_vehicles": heavy,
            "units": "vehicles per counted hour"}


def parse_auto(text: str) -> dict:
    """Return 24 hourly totals per direction, checked against quarter and day totals."""
    _check("24 Hours Traffic Volume" in text, "Not a 24-hour automatic count.")
    location = re.search(r"Location\s+(.+?)\s+Day of Week", text)
    stamp = re.search(r"Date\s+(\d{2}/\d{2}/\d{2})", text)
    direction = re.search(r"Direction\s+(N/S|E/W)\s+STREET", text)
    _check(location and stamp and direction, "Sheet header incomplete.")
    first, second = ("nb", "sb") if direction.group(1) == "N/S" else ("wb", "eb")
    pattern = re.compile(r"^(\d{1,2}) (AM|PM|NN)\s+" + r"\s+".join([r"([\d,]+)"] * 11) + r"\s*$")
    hourly = {first: [], second: []}
    seen_hours = []
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        hour, suffix = int(match.group(1)), match.group(2)
        _check(1 <= hour <= 12 and (suffix != "NN" or hour == 12), "Invalid automatic count hour.")
        clock_hour = hour % 12 + (12 if suffix in ("PM", "NN") else 0)
        seen_hours.append(clock_hour)
        values = _ints(match.groups()[2:])
        _check(sum(values[0:4]) == values[4] and sum(values[5:9]) == values[9], "Quarter-hours do not sum to the hour.")
        _check(values[4] + values[9] == values[10], "Directions do not sum to the hourly total.")
        hourly[first].append(values[4])
        hourly[second].append(values[9])
    _check(seen_hours == list(range(24)), "Expected one chronological row for each of the 24 hours.")
    totals = re.search(r"24 HOUR VEHICLES TOTAL\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)", text)
    _check(totals, "Daily totals missing.")
    day_first, day_second, day_all = _ints(totals.groups())
    _check(sum(hourly[first]) == day_first and sum(hourly[second]) == day_second and day_first + day_second == day_all,
           "Hourly values do not reproduce the 24-hour totals.")
    return {"kind": "automatic", "location": location.group(1).strip(),
            "date": datetime.strptime(stamp.group(1), "%m/%d/%y").date().isoformat(),
            "street_direction": direction.group(1), "hourly": hourly,
            "daily": {first: day_first, second: day_second, "total": day_all},
            "units": "vehicles per hour, 24-hour automatic count"}


def load_sheet(filename: str, cache: Path) -> dict:
    data = fetch_sheet(filename, cache)
    text = sheet_text(data)
    parsed = parse_manual(text) if filename.endswith("-MAN.pdf") else parse_auto(text)
    parsed.update(filename=filename, url=sheet_url(filename), sha256=sha256(data).hexdigest())
    return parsed


def find_sheet(primary: str, cross: str, count_date: str, kind: str, cache: Path) -> dict:
    """Try both street orders; return the first sheet that downloads and passes every check."""
    errors = []
    for name in sheet_names(primary, cross, count_date, kind):
        try:
            sheet = load_sheet(name, cache)
            _check(sheet["date"] == count_date[:10], "Count date does not match the source record.")
            if kind == "MAN":
                expected = {street_token(primary), street_token(cross)}
                actual = {street_token(sheet["north_south"]), street_token(sheet["east_west"])}
                _check(actual == expected, "Counted streets do not match the source record.")
            return sheet
        except SheetError as error:
            errors.append(f"{name}: {error}")
    raise SheetError("; ".join(errors))


def peak_hour(sheet: dict, period: str) -> str:
    """Busiest counted hour in the AM (before noon) or PM window of a manual sheet."""
    _check(period in ("am", "pm"), "Choose a counted AM or PM period.")
    window = [h for h in sheet["hours"] if (h in ("7-8", "8-9", "9-10", "10-11", "11-12")) == (period == "am")]
    _check(window, f"No {period.upper()} hours on this sheet.")
    return max(window, key=lambda h: sum(sum(a[h].values()) for a in sheet["approaches"].values()))
