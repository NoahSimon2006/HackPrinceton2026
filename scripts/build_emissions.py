"""Build the transparent, precomputed DTLA tailpipe-emissions pilot.

Inputs under sim/sources are public data downloads. SUMO's passenger-car
random-OD run supplies relative speed/delay and route pressure; CARB EMFAC
supplies the regional fleet-average running-exhaust rate. Historical LADOT
counts anchor a small number of road volumes. This is a scenario, not a
current measured inventory or a statistically calibrated traffic forecast.
"""
from __future__ import annotations

import csv
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import sumolib

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "sim"
SOURCES = SIM / "sources"
OUT = ROOT / "public" / "data" / "emissions.json"
BBOX = [-118.268, 34.034, -118.219, 34.070]
PERIODS = {"midday": {"label": "Weekday midday", "share": .060, "seed": 26},
           "pm_peak": {"label": "Weekday PM peak", "share": .085, "seed": 27}}
ROAD_TYPES = {"motorway", "motorway_link", "trunk", "trunk_link", "primary",
              "primary_link", "secondary", "secondary_link", "tertiary",
              "tertiary_link", "residential", "unclassified", "living_street"}
BASE_DAILY = {"motorway": 70000, "motorway_link": 21000, "trunk": 32000,
              "trunk_link": 12000, "primary": 22000, "primary_link": 9500,
              "secondary": 14000, "secondary_link": 7000, "tertiary": 8500,
              "tertiary_link": 4500, "residential": 2500,
              "unclassified": 3000, "living_street": 1200}


def street_key(name):
    text = name.upper().replace("’", "'")
    text = re.sub(r"\b(NORTH|SOUTH|EAST|WEST|N|S|E|W)\b", "", text)
    text = re.sub(r"\b(AVENUE|AVE|AV)\b", "AV", text)
    text = re.sub(r"\b(STREET|STR|ST)\b", "ST", text)
    text = re.sub(r"\b(BOULEVARD|BLVD|BL)\b", "BL", text)
    text = re.sub(r"\b(PLACE|PL)\b", "PL", text)
    text = re.sub(r"\b(DRIVE|DR)\b", "DR", text)
    text = re.sub(r"\b(ROAD|RD)\b", "RD", text)
    text = re.sub(r"\b(FREEWAY|FWY)\b", "FWY", text)
    text = re.sub(r"\b(\d+)\s+(ST|ND|RD|TH)\b", r"\1", text)
    return " ".join(re.findall(r"[A-Z0-9]+", text))


def emfac_rates():
    with (SOURCES / "emfac2025-la-2026.csv").open(newline="") as file:
        while line := file.readline():
            if line.startswith('Region,"Calendar Year"'):
                file.seek(file.tell() - len(line))
                break
        rows = list(csv.DictReader(file))
    vmt = sum(float(row["Total VMT"] or 0) for row in rows)
    if not vmt:
        raise ValueError("EMFAC VMT is empty")
    return {pollutant: sum(float(row["Total VMT"] or 0) *
                           float(row[f"{pollutant}_RUNEX"] or 0) for row in rows) / vmt
            for pollutant in ("CO2", "NOx")}, len(rows)


def edge_data(path):
    tree = ET.parse(path)
    return {element.get("id"): {key: float(value) for key, value in element.attrib.items()
                                  if key != "id"}
            for element in tree.findall(".//interval/edge")}


def direction(edge):
    shape = edge.getShape()
    if len(shape) < 2:
        return None
    dx = shape[-1][0] - shape[0][0]
    dy = shape[-1][1] - shape[0][1]
    return ("e_b" if dx > 0 else "w_b") if abs(dx) > abs(dy) else (
        "n_b" if dy > 0 else "s_b")


def main():
    net = sumolib.net.readNet(str(SIM / "dtla.net.xml"))
    edges = []
    by_street = defaultdict(list)
    node_streets = defaultdict(set)
    for edge in net.getEdges():
        if edge.isSpecial() or not edge.allows("passenger"):
            continue
        kind = edge.getType().split("|")[-1].replace("highway.", "")
        if kind not in ROAD_TYPES or edge.getLength() < 15:
            continue
        shape = edge.getShape()
        coords = [net.convertXY2LonLat(*point) for point in shape]
        midpoint = coords[len(coords) // 2]
        if not (BBOX[0] <= midpoint[0] <= BBOX[2] and BBOX[1] <= midpoint[1] <= BBOX[3]):
            continue
        item = {"edge": edge, "id": edge.getID(), "name": edge.getName() or kind.replace("_", " ").title(),
                "kind": kind, "length_m": edge.getLength(),
                "coordinates": [[round(lon, 6), round(lat, 6)] for lon, lat in coords],
                "center": midpoint}
        edges.append(item)
        if edge.getName():
            key = street_key(edge.getName())
            by_street[key].append(item)
            node_streets[edge.getFromNode().getID()].add(key)
            node_streets[edge.getToNode().getID()].add(key)

    counts = json.loads((SOURCES / "ladot-traffic-counts.json").read_text())
    anchors = {}
    for record in counts:
        try:
            day_total = float(record["total"])
        except (ValueError, KeyError, TypeError):
            continue
        if day_total <= 0 or record.get("day") not in {"MON", "TUE", "WED", "THU", "FRI"}:
            continue
        primary, cross = street_key(record.get("primary_street", "")), street_key(record.get("cross_street", ""))
        if not primary or not cross or primary not in by_street:
            continue
        candidates = []
        for item in by_street[primary]:
            edge = item["edge"]
            for node in (edge.getFromNode(), edge.getToNode()):
                if cross in node_streets[node.getID()]:
                    candidates.append(item)
                    break
        if not candidates:
            continue
        for item in candidates:
            field = direction(item["edge"])
            try:
                directional = float(record.get(field) or 0)
            except (ValueError, TypeError):
                directional = 0
            if directional <= 0:
                directional = day_total / 2  # explicit direction-split assumption
            previous = anchors.get(item["id"])
            if previous is None or record.get("count_date", "") > previous["date"]:
                anchors[item["id"]] = {"daily": directional, "date": record["count_date"][:10],
                                        "street": record.get("primary_street", ""),
                                        "cross": record.get("cross_street", ""),
                                        "direction_assumed": not bool(record.get(field))}

    fleet, fleet_rows = emfac_rates()
    simulations = {}
    total_teleports = 0
    for period in PERIODS:
        traffic = edge_data(SIM / f"{period}.traffic.xml")
        emissions = edge_data(SIM / f"{period}.emissions.xml")
        stats = ET.parse(SIM / f"{period}.statistics.xml").getroot()
        total_teleports += int(stats.find("teleports").get("total"))
        # SUMO reports mg absolute and meters driven over the 3,000-second
        # measurement window. Normalize its road variation to the EMFAC fleet.
        distance = sum(traffic.get(item["id"], {}).get("distance", 0) for item in edges)
        simulations[period] = {"traffic": traffic, "emissions": emissions,
                               "sumo_g_per_mile": {
                                   p: sum(emissions.get(item["id"], {}).get(f"{p}_abs", 0)
                                          for item in edges) / 1000 / (distance / 1609.344)
                                   for p in ("CO2", "NOx")}}

    output = []
    for item in edges:
        edge_id, kind = item["id"], item["kind"]
        anchor = anchors.get(edge_id)
        daily = anchor["daily"] if anchor else BASE_DAILY[kind] / 2
        values = {}
        for period, params in PERIODS.items():
            sim = simulations[period]
            traffic = sim["traffic"].get(edge_id, {})
            emissions = sim["emissions"].get(edge_id, {})
            base_flow = daily * params["share"]
            # Relative route pressure is illustrative. A historical count,
            # where present, fixes the volume rather than being blended away.
            simulated_flow = traffic.get("flow", 0)
            assumed_flow = BASE_DAILY[kind] / 2 * params["share"]
            pressure = min(1.9, max(.55, .7 + .3 * simulated_flow / max(assumed_flow, 1)))
            volume = base_flow if anchor else base_flow * pressure
            distance_m = traffic.get("distance", 0)
            result = {"vehicles_h": round(volume),
                      "speed_kmh": round(traffic.get("speed", item["edge"].getSpeed()) * 3.6, 1)}
            for pollutant, output_key, divisor in (("CO2", "co2_kg_h", 1000), ("NOx", "nox_g_h", 1)):
                sumo_rate = (emissions.get(f"{pollutant}_abs", 0) / 1000 /
                             (distance_m / 1609.344)) if distance_m > 50 else sim["sumo_g_per_mile"][pollutant]
                multiplier = min(2.2, max(.5, sumo_rate / max(sim["sumo_g_per_mile"][pollutant], .001)))
                result[output_key] = round(volume * item["length_m"] / 1609.344 *
                                           fleet[pollutant] * multiplier / divisor, 2)
            values[period] = result
        output.append({"id": edge_id, "name": item["name"], "class": kind,
                       "length_m": round(item["length_m"]), "coordinates": item["coordinates"],
                       "basis": "historical_count" if anchor else "class_assumption",
                       "count": anchor, "periods": values})

    summary = {period: {key: round(sum(road["periods"][period][key] for road in output), 1)
                        for key in ("co2_kg_h", "nox_g_h")}
               for period in PERIODS}
    data = {"schema": 1, "title": "Downtown Los Angeles emissions pilot", "bbox": BBOX,
            "periods": PERIODS, "fleet_rates_g_per_mile": {k: round(v, 4) for k, v in fleet.items()},
            "summary": summary, "roads": output,
            "quality": {"road_edges": len(output), "historical_anchor_edges": len(anchors),
                        "emfac_fleet_rows": fleet_rows, "simulation_teleports": total_teleports,
                        "window_minutes": 50},
            "method": {
                "headline": "Illustrative tailpipe running-exhaust scenario, not a measured inventory.",
                "traffic": "SUMO 1.28 random origin–destination runs shape road speed and relative pressure. Routes are assumed, not observed.",
                "volume": "Latest matched weekday LADOT 2011–2016 directional count anchors; other streets use stated functional-class daily-volume assumptions. Midday 6% and PM peak 8.5% of daily traffic.",
                "emissions": "SUMO edge-level running-emissions variation normalized to 2026 Los Angeles EMFAC2025 v2.1.1 fleet VMT-weighted running-exhaust CO₂ and NOₓ rates. Excludes non-tailpipe and upstream emissions.",
                "uncertainty": "Illustrative sensitivity: approximately ±35% at historical anchors and ±60% on assumed-volume roads; these are judgmental ranges, not confidence intervals.",
                "signal": "OSM signal locations and SUMO generated timing; actual signal plans were unavailable."},
            "sources": [
                {"label": "CARB EMFAC2025 v2.1.1, Los Angeles (SC), 2026", "url": "https://emfac.arb.ca.gov/emissions-inventory/3b6469b056eb7e5a47b65c0c96415b33d5e20812"},
                {"label": "LADOT traffic counts, 2011–2016", "url": "https://data.lacity.org/Transportation/LADOT-Traffic-Counts-Summary/94wu-3ps3"},
                {"label": "OpenStreetMap contributors, road geometry", "url": "https://www.openstreetmap.org/copyright"},
                {"label": "Eclipse SUMO simulation", "url": "https://sumo.dlr.de/docs/"}]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print("Roads:", len(output), "historical anchor edges:", len(anchors))
    print("EMFAC rates g/mi:", fleet)
    print("SUMO rates g/mi:", {p: sim["sumo_g_per_mile"] for p, sim in simulations.items()})
    print("Summary:", summary)
    print("Teleports:", total_teleports, "output bytes:", OUT.stat().st_size)


if __name__ == "__main__":
    main()
