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


def main():
    nodes, ways = {}, {}
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
            for element in root:
                if element.tag == "node":
                    nodes[element.attrib["id"]] = element
                elif element.tag == "way" and any(
                    tag.get("k") == "highway" for tag in element.findall("tag")
                ):
                    ways[element.attrib["id"]] = element
    used = {nd.get("ref") for way in ways.values() for nd in way.findall("nd")}
    # Keep all traffic signals within the pilot even if OSM way segmentation omits one.
    used.update(node_id for node_id, node in nodes.items() if any(
        tag.get("k") == "highway" and tag.get("v") == "traffic_signals"
        for tag in node.findall("tag")))
    osm = ET.Element("osm", {"version": "0.6", "generator": "Sustainability Map OSM API tiler"})
    for node_id in sorted(used, key=int):
        if node_id in nodes:
            osm.append(nodes[node_id])
    for way_id in sorted(ways, key=int):
        osm.append(ways[way_id])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(osm).write(OUT, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {len(ways)} ways and {len(used)} nodes to {OUT}")


if __name__ == "__main__":
    main()
