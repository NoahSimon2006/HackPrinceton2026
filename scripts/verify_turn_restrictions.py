"""Audit static, single-node OSM turn restrictions against actual SUMO connections.

This is deliberately a bounded verifier: conditional and via-way restrictions are
reported as unverified, never counted as passing. Build with
--output.original-names true to retain identities through joined junctions.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

CLASSES = ("passenger", "truck", "bus")
EXCEPTIONS = {"motorcar": {"passenger"}, "hgv": {"truck"}, "bus": {"bus"},
              "psv": {"bus"}, "taxi": set(), "bicycle": set(), "emergency": set(),
              "motorcycle": set(), "moped": set(), "agricultural": set()}


def allows(lane, vehicle):
    if lane.get("allow") is not None:
        permitted = lane.get("allow").split()
        return "all" in permitted or vehicle in permitted
    prohibited = lane.get("disallow", "").split()
    return "all" not in prohibited and vehicle not in prohibited


def original_ids(element):
    return {value for param in element.findall('.//param[@key="origId"]')
            for value in param.get("value", "").split()}


def audit(osm_path, network_path):
    osm = ET.parse(osm_path).getroot()
    net = ET.parse(network_path).getroot()
    edges = {e.get("id"): e for e in net.findall("edge") if e.get("function") != "internal"}
    lanes = {lane.get("id"): lane for e in net.findall("edge") for lane in e.findall("lane")}
    junctions = defaultdict(set)
    for node in net.findall("junction"):
        if node.get("type") != "internal":
            for ident in original_ids(node) | {node.get("id")}:
                junctions[ident].add(node.get("id"))
    by_way = defaultdict(set)
    for ident, edge in edges.items():
        for way in original_ids(edge):
            by_way[way].add(ident)
    connections = defaultdict(list)
    for connection in net.findall("connection"):
        if connection.get("from") in edges and connection.get("to") in edges:
            connections[connection.get("from")].append(connection)

    def accessible(connection, vehicle):
        first, last = edges[connection.get("from")], edges[connection.get("to")]
        return (allows(first.findall("lane")[int(connection.get("fromLane"))], vehicle)
                and allows(last.findall("lane")[int(connection.get("toLane"))], vehicle)
                and allows(connection, vehicle)
                and (not connection.get("via") or allows(lanes[connection.get("via")], vehicle)))

    rows = []
    for relation in osm.findall("relation"):
        tags = {t.get("k"): t.get("v") for t in relation.findall("tag")}
        if tags.get("type") != "restriction":
            continue
        members = defaultdict(list)
        for member in relation.findall("member"):
            members[member.get("role")].append((member.get("type"), member.get("ref")))
        row = {"id": relation.get("id"), "restriction": tags.get("restriction"),
               "conditional": tags.get("restriction:conditional"), "except": tags.get("except"),
               "members": dict(members)}
        rows.append(row)
        via = members["via"]
        if len(via) != 1 or via[0][0] != "node":
            # A via-way rule cannot affect a cutout without both endpoint ways.
            ends = members["from"] + members["to"]
            represented = len(ends) >= 2 and all(kind == "way" and by_way.get(ident) for kind, ident in ends)
            row["status"] = "unverified_via_way" if represented else "movement_not_represented"
            continue
        junction = junctions.get(via[0][1], set())
        if not junction:
            row["status"] = "via_not_represented"
            continue
        if (len(members["from"]) != 1 or len(members["to"]) != 1
                or members["from"][0][0] != "way" or members["to"][0][0] != "way"):
            row["status"] = "unverified_members"
            continue
        incoming = sorted(e for e in by_way[members["from"][0][1]] if edges[e].get("to") in junction)
        outgoing = sorted(e for e in by_way[members["to"][0][1]] if edges[e].get("from") in junction)
        row.update(incoming=incoming, outgoing=outgoing, junctions=sorted(junction))
        if not incoming or not outgoing:
            row["status"] = "movement_not_represented"
            continue
        rule = tags.get("restriction", "")
        if row["conditional"]:
            row["status"] = "unverified_conditional"
            continue
        if rule not in ("no_left_turn", "no_right_turn", "no_straight_on", "no_u_turn",
                        "only_left_turn", "only_right_turn", "only_straight_on"):
            row["status"] = "unverified_type"
            continue
        exceptions = set(filter(None, tags.get("except", "").split(";")))
        if exceptions - EXCEPTIONS.keys():
            row["status"] = "unverified_exception"
            continue
        if len(incoming) > 1 and rule != "no_u_turn":
            row["status"] = "unverified_direction"
            continue
        excluded = set().union(*(EXCEPTIONS[x] for x in exceptions))
        checks = {}
        for vehicle in CLASSES:
            if vehicle in excluded:
                checks[vehicle] = {"status": "exempt"}
                continue
            active = [e for e in incoming if any(allows(lane, vehicle) for lane in edges[e].findall("lane"))]
            if not active or not any(allows(lane, vehicle) for e in outgoing for lane in edges[e].findall("lane")):
                checks[vehicle] = {"status": "class_not_represented"}
                continue
            illegal = []
            missing_required = []
            for edge in active:
                links = [c for c in connections[edge] if accessible(c, vehicle)]
                targets = [c for c in links if c.get("to") in outgoing]
                if rule == "no_u_turn" and members["from"] == members["to"]:
                    targets = [c for c in targets if c.get("dir") in ("t", "T")]
                if rule.startswith("only_"):
                    bad = [c for c in links if c.get("to") not in outgoing]
                    if not targets:
                        missing_required.append(edge)
                else:
                    bad = targets
                illegal.extend(dict(c.attrib) for c in bad)
            checks[vehicle] = {"status": "failed" if illegal or missing_required else "passed",
                               "illegal_connections": illegal, "missing_required": missing_required}
        row["checks"] = checks
        statuses = {c["status"] for c in checks.values()}
        row["status"] = "failed" if "failed" in statuses else "passed" if "passed" in statuses else "class_not_represented"
    return {"osm_sha256": sha256(Path(osm_path).read_bytes()).hexdigest(),
            "network_sha256": sha256(Path(network_path).read_bytes()).hexdigest(),
            "scope": "Static single-via-node restrictions; passenger, truck and bus lane permissions. Unrepresented and unsupported relations are not passes.",
            "counts": dict(Counter(row["status"] for row in rows)), "relations": rows}


def correction_patch(report, network_path):
    """Restrict only verified illegal class/connection pairs, retaining other permissions.

    Source exceptions remain allowed. Never invent a missing required connection
    or resolve conditional/via-way/ambiguous relations by guessing.
    """
    denied = defaultdict(set)
    for row in report["relations"]:
        for vehicle, check in row.get("checks", {}).items():
            if check.get("missing_required"):
                raise ValueError(f"Restriction {row['id']} has no required permitted connection; inspect topology.")
            for connection in check.get("illegal_connections", []):
                key = tuple(connection[k] for k in ("from", "to", "fromLane", "toLane"))
                denied[key].add(vehicle)
    net = ET.parse(network_path).getroot()
    lanes = {lane.get("id"): lane for e in net.findall("edge") for lane in e.findall("lane")}
    original = {tuple(c.get(k) for k in ("from", "to", "fromLane", "toLane")): c
                for c in net.findall("connection")}
    patch = ET.Element("connections")
    for key, vehicles in sorted(denied.items()):
        attrs = dict(zip(("from", "to", "fromLane", "toLane"), key))
        existing = lanes.get(original[key].get("via"))
        if existing is not None and existing.get("allow") is not None and "all" not in existing.get("allow").split():
            allowed = set(existing.get("allow").split()) - vehicles
            attrs["allow"] = " ".join(sorted(allowed))
        else:
            prior = set(existing.get("disallow", "").split()) if existing is not None else set()
            attrs["disallow"] = " ".join(sorted(prior | vehicles))
        ET.SubElement(patch, "connection", attrs)
    return patch


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm", type=Path, default=Path("sim/sources/dtla-roads.osm"))
    parser.add_argument("--network", type=Path, default=Path("sim/dtla.net.xml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.osm, args.network)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result["counts"], sort_keys=True))
    raise SystemExit(1 if result["counts"].get("failed") else 0)
