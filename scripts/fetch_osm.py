"""Fetch the pinned downtown pilot OSM extract in small API tiles.

The OSM API limits large map requests. We collect complete ways, deduplicate
nodes/ways by ID, and retain the source timestamp in the resulting XML.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sim" / "sources" / "dtla-roads.osm"
WEST, SOUTH, EAST, NORTH = -118.268, 34.034, -118.219, 34.070
NX = NY = 3


def collect(root, nodes, ways, restrictions):
    for element in root:
        if element.tag == "node":
            nodes[element.attrib["id"]] = element
        elif element.tag == "way" and any(tag.get("k") == "highway" for tag in element.findall("tag")):
            ways[element.attrib["id"]] = element
        elif element.tag == "relation" and any(tag.get("k") == "type" and tag.get("v") == "restriction"
                                                for tag in element.findall("tag")):
            restrictions[element.attrib["id"]] = element


def missing_members(relation, nodes, ways):
    return [member for member in relation.findall("member")
            if member.get("type") not in ("node", "way") or
            member.get("ref") not in (nodes if member.get("type") == "node" else ways)]


def extract(nodes, ways, restrictions):
    """Retain turn restrictions and reject incomplete topology rather than dropping it."""
    used = {nd.get("ref") for way in ways.values() for nd in way.findall("nd")}
    if not used <= nodes.keys():
        raise ValueError("OSM extract has a road with missing nodes; refusing incomplete topology.")
    for relation in restrictions.values():
        if missing_members(relation, nodes, ways):
            raise ValueError("OSM turn restriction has missing members; refusing to silently allow that turn.")
        used.update(m.get("ref") for m in relation.findall("member") if m.get("type") == "node")
    used.update(node_id for node_id, node in nodes.items() if any(
        tag.get("k") == "highway" and tag.get("v") == "traffic_signals"
        for tag in node.findall("tag")))
    osm = ET.Element("osm", {"version": "0.6", "generator": "Sustainability Map OSM API tiler"})
    for node_id in sorted(used, key=int):
        osm.append(nodes[node_id])
    for way_id in sorted(ways, key=int):
        osm.append(ways[way_id])
    for relation_id in sorted(restrictions, key=int):
        osm.append(restrictions[relation_id])
    return osm


def main():
    nodes, ways, restrictions = {}, {}, {}
    for row in range(NY):
        for col in range(NX):
            bbox = (
                WEST + (EAST - WEST) * col / NX,
                SOUTH + (NORTH - SOUTH) * row / NY,
                WEST + (EAST - WEST) * (col + 1) / NX,
                SOUTH + (NORTH - SOUTH) * (row + 1) / NY,
            )
            url = "https://api.openstreetmap.org/api/0.6/map?" + urlencode(
                {"bbox": ",".join(f"{v:.7f}" for v in bbox)})
            print(f"OSM tile {row * NX + col + 1}/{NX * NY}: {bbox}", flush=True)
            request = Request(url, headers={"User-Agent": "SustainabilityMap/0.1 research prototype"})
            with urlopen(request, timeout=120) as response:
                root = ET.parse(response).getroot()
            collect(root, nodes, ways, restrictions)
    # The map API returns referring relations but not necessarily every member.
    # Resolve the finite set of relevant restrictions before writing the extract.
    restrictions = {key: relation for key, relation in restrictions.items() if any(
        m.get("type") == "way" and m.get("ref") in ways for m in relation.findall("member"))}
    for key, relation in list(restrictions.items()):
        if not missing_members(relation, nodes, ways):
            continue
        if not key.isdecimal():
            raise ValueError("Invalid OSM relation identifier.")
        request = Request(f"https://api.openstreetmap.org/api/0.6/relation/{key}/full",
                          headers={"User-Agent": "SustainabilityMap/0.1 research prototype"})
        with urlopen(request, timeout=120) as response:
            full = ET.parse(response).getroot()
        collect(full, nodes, ways, {})
    osm = extract(nodes, ways, restrictions)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pending = OUT.with_suffix(".pending.osm")
    ET.ElementTree(osm).write(pending, encoding="utf-8", xml_declaration=True)
    pending.replace(OUT)
    print(f"Wrote {len(ways)} ways, {len(osm.findall('node'))} nodes and {len(restrictions)} turn restrictions to {OUT}")


if __name__ == "__main__":
    main()
