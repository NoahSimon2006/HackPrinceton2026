"""Bounded, geometry-only street context; no traffic demand or model requests.

Source coordinates and names remain in this local object. Only ``model_context``
is suitable for an agent prompt. Widths derived from tags are explicitly assumed;
an OSM road centerline is never represented as a surveyed curb line.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from pyproj import Transformer
from shapely import transform, unary_union
from shapely.geometry import LineString, Point, mapping
from shapely.ops import substring

from site_measurements import PROJECT, projected

ROOT = Path(__file__).resolve().parent
TO_GEO = Transformer.from_crs(32611, 4326, always_xy=True)
MAX_BYTES = 8_000_000
MAX_LOCAL_BYTES = 128_000_000
RADIUS_M = 180
MAX_ANCHORS = 16
VERSION = "road-context-v3-directions"
ROAD_KINDS = ["curb_extension", "crossing", "pedestrian_island", "bike_lane", "pedestrian_space", "lane_marking"]
MOTOR_ROADS = {"primary", "secondary", "tertiary", "residential", "unclassified", "living_street", "service",
              "primary_link", "secondary_link", "tertiary_link"}


def canonical_hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _check(activity):
    if activity is not None:
        activity.check()


def _geographic(geometry):
    return mapping(transform(geometry, TO_GEO.transform, interleaved=False))


def _xml(data, *, limit=MAX_BYTES):
    if len(data) > limit or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("The road source exceeds the bounded XML format.")
    return ET.fromstring(data)


def _source(provider, raw, *, retrieved_at=None, observed_at=None, url=None):
    return {"provider": provider, "url": url, "source_hash": sha256(raw).hexdigest(),
            "observed_at": observed_at, "retrieved_at": retrieved_at,
            "attribution": "© OpenStreetMap contributors", "license": "ODbL 1.0"}


def _length(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(m|meters|metres|ft|feet|')?\s*", value)
    if not match:
        return None
    number = float(match[1]) * (.3048 if match[2] in ("ft", "feet", "'") else 1)
    return number if 3 <= number <= 40 else None


def _width(tags):
    width = _length(tags.get("width"))
    if width is not None:
        return width, "OSM reported width; not a surveyed curb line."
    lanes = tags.get("lanes", "")
    if re.fullmatch(r"[1-8]", lanes):
        return int(lanes) * 3.2, "Illustrative road width: OSM reported lane count × assumed 3.2 m per lane."
    one_way = tags.get("oneway") in ("yes", "1", "true", "-1")
    return (3.5 if one_way else 7.0), "Illustrative road width: assumed " + ("3.5 m one-way" if one_way else "7 m two-way") + " corridor around the mapped centerline; verify curbs on site."


def _clip_line(line, origin):
    # Keep a contiguous segment and preserve the source's direction.
    distance = line.project(origin)
    return substring(line, max(0., distance - RADIUS_M), min(line.length, distance + RADIUS_M))


def _anchor(identifier, line, width, basis, origin, label, source_hash, *, surface=None, kind="road"):
    if not isinstance(line, LineString) or line.length < 4 or not line.is_simple or line.distance(origin) > 150:
        return None
    line = _clip_line(line, origin)
    if line.length < 4:
        return None
    corridor = line.buffer(width / 2, cap_style="flat", join_style="round")
    surface = corridor if surface is None else surface.intersection(corridor.buffer(.10))
    if surface.is_empty or not surface.is_valid or surface.geom_type not in ("Polygon", "MultiPolygon"):
        return None
    midpoint = line.project(origin)
    before, after = line.interpolate(max(0, midpoint - 2)), line.interpolate(min(line.length, midpoint + 2))
    angle = math.degrees(math.atan2(after.x - before.x, after.y - before.y)) % 360
    return {"id": "road-" + sha256(identifier.encode()).hexdigest()[:12], "kind": kind,
            "label": label, "geometry": _geographic(line), "surface": _geographic(surface),
            "length_m": round(line.length, 3), "width_m": round(width, 3), "width_basis": basis,
            "heading_deg": round(angle, 1), "selection_offset_m": round(midpoint, 2),
            "distance_m": round(line.distance(origin), 2), "source_hash": source_hash,
            "supported_kinds": ["crossing"] if kind == "marked_crossing" else ROAD_KINDS}


def _from_osm(raw, origin, *, local=False):
    root = _xml(raw, limit=MAX_LOCAL_BYTES if local else MAX_BYTES)
    nodes = {}
    for item in root.findall("node"):
        try:
            lon, lat = float(item.attrib["lon"]), float(item.attrib["lat"])
            if -119 < lon < -117 and 33 < lat < 35:
                nodes[item.attrib["id"]] = PROJECT.transform(lon, lat)
        except (KeyError, ValueError):
            continue
    digest = sha256(raw).hexdigest()
    anchors = []
    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        if tags.get("highway") not in MOTOR_ROADS or tags.get("access") in ("no", "private"):
            continue
        refs = [n.get("ref") for n in way.findall("nd")]
        if len(refs) < 2 or any(ref not in nodes for ref in refs):
            continue
        line = LineString([nodes[ref] for ref in refs])
        if tags.get("oneway") == "-1":
            line = LineString(list(line.coords)[::-1])
        width, basis = _width(tags)
        anchor = _anchor("osm-way:" + way.get("id", ""), line, width, basis, origin,
                         tags.get("name") or "Mapped " + tags["highway"].replace("_", " ") + " road", digest)
        if anchor:
            anchor["traffic_direction"] = "one_way" if tags.get("oneway") in ("yes", "1", "true", "-1") else "two_way"
            if re.fullmatch(r"[1-8]", tags.get("lanes", "")):
                anchor["lane_count"] = int(tags["lanes"])
            anchor["direction_basis"] = "Explicit OpenStreetMap one-way tag and source way orientation." if anchor["traffic_direction"] == "one_way" else "OpenStreetMap two-way road."
            anchor["topology"] = {"family": "osm", "way_id": way.get("id"),
                                  "node_refs": refs[::-1] if tags.get("oneway") == "-1" else refs,
                                  "road_class": tags["highway"], "junction_type": tags.get('junction')}
            anchors.append(anchor)
    timestamps = [way.get("timestamp") for way in root.findall("way") if way.get("timestamp")]
    return anchors, max(timestamps, default=None)


def _from_sumo(raw, origin, *, osm_raw=None):
    root = _xml(raw, limit=MAX_LOCAL_BYTES)
    # An unpaired simulation edge can also be one half of a divided road.
    # Confirm a one-way street with its original OSM tag before treating the
    # modeled carriageway as the whole road.
    one_way_ids = set()
    if osm_raw is not None:
        for way in _xml(osm_raw, limit=MAX_LOCAL_BYTES).findall("way"):
            tags = {tag.get("k"): tag.get("v") for tag in way.findall("tag")}
            if tags.get("oneway") in ("yes", "1", "true", "-1"):
                one_way_ids.add(way.get("id"))
    location = root.find("location")
    if location is None or location.get("projParameter") in (None, "!", "-", "."):
        raise ValueError("The network has no geographic projection.")
    offset = [float(v) for v in location.get("netOffset", "0,0").split(",")]
    if len(offset) != 2:
        raise ValueError("The network offset is invalid.")
    to_local = Transformer.from_crs(location.get("projParameter"), 32611, always_xy=True)
    records, digest = [], sha256(raw).hexdigest()
    for edge in root.findall("edge"):
        if edge.get("function") or edge.get("id", "").startswith(":"):
            continue
        highway = edge.get("type", "").removeprefix("highway.").split("|")[0]
        if highway and highway not in MOTOR_ROADS:
            continue
        lanes = []
        for lane in edge.findall("lane"):
            allowed = set((lane.get("allow") or "").split())
            if allowed and not allowed.intersection({"passenger", "private", "taxi", "bus", "truck", "delivery", "all"}):
                continue
            if "passenger" in (lane.get("disallow") or "").split():
                continue
            coords = []
            for pair in (lane.get("shape") or "").split():
                xy = [float(v) for v in pair.split(",")]
                coords.append(to_local.transform(xy[0] - offset[0], xy[1] - offset[1]))
            if len(coords) < 2:
                continue
            width = float(lane.get("width", "3.2"))
            if not math.isfinite(width) or not 1 <= width <= 6:
                continue
            line = LineString(coords)
            if line.length > 4 and line.is_simple:
                lanes.append((line, width))
        if not lanes:
            continue
        width = sum(item[1] for item in lanes)
        if width > 40:
            continue
        # SUMO lane 0 is rightmost. Its left offset locates the carriageway center.
        center = lanes[0][0].offset_curve((width - lanes[0][1]) / 2)
        if center.geom_type != "LineString":
            continue
        surface = unary_union([line.buffer(w / 2, cap_style="flat") for line, w in lanes])
        if center.distance(origin) <= 150:
            records.append({"edge_id": edge.get("id", ""), "from": edge.get("from"), "to": edge.get("to"),
                            "line": center, "width": width, "surface": surface,
                            "road_class": highway, "lane_count": len(lanes),
                            "label": edge.get("name") or "Mapped road approach"})
    # Opposite directed edges with reversed junction IDs represent the two
    # carriageways of one physical segment. Combine their span for crosswalks;
    # never draw a crossing ending at the middle of an opposing traffic lane.
    anchors, consumed = [], set()
    for record in sorted(records, key=lambda item: item["edge_id"]):
        if record["edge_id"] in consumed:
            continue
        reverse = next((other for other in records if record["from"] is not None and record["to"] is not None
                        and other["edge_id"] != record["edge_id"] and other["edge_id"] not in consumed
                        and other["from"] == record["to"] and other["to"] == record["from"]), None)
        if reverse is not None:
            first, second = record["line"], LineString(list(reverse["line"].coords)[::-1])
            samples = [(first.interpolate(i / 12, normalized=True), second.interpolate(i / 12, normalized=True)) for i in range(13)]
            separations = [a.distance(b) for a, b in samples]
            # Reject geometrically unrelated reverse topology or sharp splits.
            full_width = max(separations) + (record["width"] + reverse["width"]) / 2
            if full_width <= 40 and max(separations) - min(separations) <= 4:
                centers = []
                for (a, b), separation in zip(samples, separations):
                    # Unequal carriageway widths shift the outer-road midpoint
                    # away from the simple midpoint of their centerlines.
                    shift = (record["width"] - reverse["width"]) / (4 * separation) if separation > .01 else 0.
                    centers.append(((a.x + b.x) / 2 + (a.x - b.x) * shift,
                                    (a.y + b.y) / 2 + (a.y - b.y) * shift))
                center = LineString(centers)
                anchor = _anchor("sumo-road:" + "|".join(sorted((record["edge_id"], reverse["edge_id"]))), center,
                                 full_width, "Full road span combines opposing OSM-derived SUMO carriageways. Intervening median and curb positions are unverified.",
                                 origin, record["label"], digest)
                if anchor:
                    anchor["crossing_basis"] = "paired_opposing_carriageways"
                    anchor["traffic_direction"] = "two_way"
                    anchor["topology"] = {"family": "sumo", "from": record["from"], "to": record["to"],
                                          "edge_ids": [record["edge_id"], reverse["edge_id"]], "road_class": record["road_class"]}
                    anchors.append(anchor)
                    consumed.update((record["edge_id"], reverse["edge_id"]))
                    continue
        anchor = _anchor("sumo-edge:" + record["edge_id"], record["line"], record["width"],
                         "One directional OSM-derived SUMO carriageway; opposite roadway extent is unverified. Not surveyed curbs.",
                         origin, record["label"], digest, surface=record["surface"])
        if anchor:
            anchor["supported_kinds"] = [kind for kind in ROAD_KINDS if kind != "crossing"]
            anchor["crossing_basis"] = "unpaired_carriageway_use_a_marked_crossing"
            anchor["traffic_direction"] = "source_direction"
            source_way = re.fullmatch(r"-?(\d+)(?:#.*)?", record["edge_id"])
            if source_way and source_way.group(1) in one_way_ids:
                anchor["traffic_direction"] = "one_way"
                anchor["lane_count"] = record["lane_count"]
                anchor["direction_basis"] = "Explicit OSM one-way tag; vehicle direction and lane count from the corresponding directed local network edge."
                anchor["direction_source_hash"] = sha256(osm_raw).hexdigest()
            anchor["topology"] = {"family": "sumo", "from": record["from"], "to": record["to"],
                                  "edge_ids": [record["edge_id"]], "road_class": record["road_class"]}
            anchors.append(anchor)
        consumed.add(record["edge_id"])
    return anchors


def _public_osm(bbox):
    url = "https://api.openstreetmap.org/api/0.6/map?" + urlencode({"bbox": ",".join(f"{v:.7f}" for v in bbox)})
    request = Request(url, headers={"User-Agent": "SustainabilityMap/0.2 local conceptual street planning",
                                   "Accept": "application/xml"})
    with urlopen(request, timeout=12) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("The local OSM response exceeded the source size limit.")
    return raw


def _markings(markings, origin):
    anchors, keep_clear, crossing_lines = [], [], []
    for index, marking in enumerate(markings or []):
        kind = marking.get("kind")
        if kind not in ("access", "crossing", "road"):
            continue
        geometry = projected(marking.get("geometry"), ("Polygon",) if kind == "access" else ("LineString",))
        if not origin.buffer(1000).covers(geometry):
            raise ValueError("Keep concept markings within 1 km of the selected site.")
        if kind == "access":
            keep_clear.append({"type": "Feature", "id": f"keep-clear-{index + 1}", "geometry": _geographic(geometry),
                               "properties": {"kind": "access", "label": "User keep-clear area"}})
        else:
            width = 3.0 if kind == "crossing" else float(marking.get("width_m", 7.0))
            if not math.isfinite(width) or not 1 <= width <= 40:
                raise ValueError("A marked road needs a finite 1–40 m illustrative width.")
            digest = canonical_hash(marking)
            anchor = _anchor("marking:" + digest, geometry, width,
                             "User-marked crossing alignment; crosswalk thickness is a proposed dimension." if kind == "crossing" else "User-marked road centerline and assumed width.",
                             origin, "User-marked crossing" if kind == "crossing" else "User-marked road", digest,
                             kind="marked_crossing" if kind == "crossing" else "road")
            if anchor:
                anchors.append(anchor)
            if kind == "crossing":
                crossing_lines.append({"type": "Feature", "id": f"marked-crossing-{index + 1}",
                                       "geometry": _geographic(geometry), "properties": {"kind": "crossing"}})
    return anchors, keep_clear, crossing_lines


def prepare_street_context(lon, lat, markings=None, *, activity=None, network_path=None,
                           osm_path=None, fetch_osm=None, allow_public_fetch=True):
    """Return local source geometry plus a coordinate-free ``model_context``.

    ``fetch_osm`` is an injectable ``bbox -> bytes`` callable. Public retrieval is
    one bounded request only, after local source attempts; never a startup job.
    ``context.origin.lon/lat`` always equal the selected project coordinates.
    """
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lon, lat)) or not (-118.67 <= lon <= -118.10 and 33.70 <= lat <= 34.35):
        raise ValueError("Choose a site inside the Los Angeles planning area.")
    _check(activity)
    origin = Point(*PROJECT.transform(lon, lat))
    anchors, keep_clear, crossings = _markings(markings, origin)
    sources, source_status = [], []
    if anchors:
        sources.append({"provider": "Planner map markings", "source_hash": canonical_hash(markings),
                        "observed_at": None, "retrieved_at": None, "url": None})
    mapped, selected_raw, selected_family = [], None, None
    direction_raw = None
    direction_path = Path(osm_path) if osm_path is not None else ROOT / "sim/sources/dtla-roads.osm"
    if direction_path.is_file() and direction_path.stat().st_size <= MAX_LOCAL_BYTES:
        try:
            direction_raw = direction_path.read_bytes()
            _xml(direction_raw, limit=MAX_LOCAL_BYTES)
        except (OSError, ValueError, ET.ParseError):
            direction_raw = None
    for family, path in (("sumo", Path(network_path) if network_path is not None else ROOT / "sim/dtla.net.xml"),
                         ("osm", Path(osm_path) if osm_path is not None else ROOT / "sim/sources/dtla-roads.osm")):
        _check(activity)
        if not path.is_file():
            source_status.append({"source": family, "status": "not_present"})
            continue
        try:
            # Local full-city files may be larger; parse only bounded source sizes.
            if path.stat().st_size > MAX_LOCAL_BYTES:
                raise ValueError("The local road source is too large.")
            raw = path.read_bytes()
            parsed, observed = (_from_sumo(raw, origin, osm_raw=direction_raw), None) if family == "sumo" else _from_osm(raw, origin, local=True)
            if family == 'sumo' and direction_raw is not None and any(a.get('traffic_direction') == 'one_way' for a in parsed):
                # Simulation junctions split streets at lane/footway nodes.
                # Prefer the original whole-street topology for mixed-direction
                # designs when its explicit one-way tags are available locally.
                original, original_time = _from_osm(direction_raw, origin, local=True)
                if any(a.get('traffic_direction') == 'one_way' for a in original):
                    parsed, raw, family, observed = original, direction_raw, 'osm', original_time
            if parsed:
                mapped = parsed
                selected_raw, selected_family = raw, family
                sources.append(_source("OSM-derived local street network" if family == "sumo" else "OpenStreetMap local extract", raw,
                                       observed_at=observed, url="https://www.openstreetmap.org/copyright"))
                if family == "sumo" and any(a.get("direction_source_hash") for a in parsed):
                    sources.append(_source("OpenStreetMap one-way direction verification", direction_raw,
                                           url="https://www.openstreetmap.org/copyright"))
                source_status.append({"source": family, "status": "ready"})
                break
            source_status.append({"source": family, "status": "no_nearby_roads"})
        except (ValueError, OSError, ET.ParseError, KeyError, TypeError, IndexError):
            source_status.append({"source": family, "status": "unusable"})
    if not mapped and allow_public_fetch:
        _check(activity)
        # 250 m in each direction is a maximum 500 m-wide source window.
        delta_lat, delta_lon = 250 / 111_320, 250 / (111_320 * math.cos(math.radians(lat)))
        bbox = (lon - delta_lon, lat - delta_lat, lon + delta_lon, lat + delta_lat)
        try:
            raw = (fetch_osm or _public_osm)(bbox)
            if isinstance(raw, str):
                raw = raw.encode()
            _check(activity)
            mapped, observed = _from_osm(raw, origin)
            source_status.append({"source": "osm_public", "status": "ready" if mapped else "no_nearby_roads"})
            if mapped:
                selected_raw, selected_family = raw, 'osm'
                sources.append(_source("OpenStreetMap bounded map extract", raw, observed_at=observed,
                                       retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                       url="https://www.openstreetmap.org/copyright"))
        except (ValueError, OSError, ET.ParseError, KeyError, TypeError, IndexError):
            source_status.append({"source": "osm_public", "status": "unavailable"})
    _check(activity)
    from junction_context import build_junction_context
    junction_data = build_junction_context(selected_raw, selected_family, mapped, origin) if selected_raw else {"junctions": [], "anchors": []}
    # Preserve all legs of the selected connected junction before nearby
    # independent corridors. Otherwise a dense map can silently lose a leg.
    preferred = junction_data['anchors']
    preferred_ids = {a['id'] for a in preferred}
    anchors += (preferred + sorted((a for a in mapped if a['id'] not in preferred_ids), key=lambda a: (a["distance_m"], a["id"])))[:MAX_ANCHORS - len(anchors)]
    anchors = anchors[:MAX_ANCHORS]
    roads = [{"type": "Feature", "id": anchor["id"], "geometry": anchor["surface"],
              "properties": {"kind": "road", "role": "existing", "label": anchor["label"],
                             "width_basis": anchor["width_basis"]}} for anchor in anchors if anchor["kind"] == "road"]
    assumptions = ["Road geometry is a planning reference, not a surveyed carriageway or legal right-of-way boundary.",
                   "Concepts do not establish traffic performance, construction feasibility, signal timing, or permission.",
                   "Left and right refer to the source anchor direction; offsets are meters from that anchor's start."]
    reason = "" if anchors else "No usable road alignment was found near this selection. Mark a crossing on the map or choose a site closer to a mapped street."
    context = {"schema_version": 1, "compiler_version": VERSION, "status": "ready" if anchors else "unavailable", "reason": reason,
               "origin": {"lon": lon, "lat": lat, "crs": "EPSG:32611", "easting": origin.x, "northing": origin.y},
               "anchors": anchors, "roads": roads, "keep_clear": keep_clear, "crossings": crossings,
               "sources": sources, "source_status": source_status, "assumptions": assumptions,
               "junctions": junction_data['junctions']}
    # Retrieval time is provenance, not a geometry identity; identical extracts retain stable hashes.
    stable = {**context, "sources": [{k: v for k, v in source.items() if k != "retrieved_at"} for source in sources]}
    context["context_hash"] = canonical_hash(stable)
    curated = []
    compass = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")
    for anchor in anchors:
        curated.append({key: anchor[key] for key in ("id", "kind", "length_m", "width_m", "width_basis", "selection_offset_m", "distance_m", "supported_kinds")})
        curated[-1]["traffic_direction"] = anchor.get("traffic_direction", "unverified")
        curated[-1]["direction"] = compass[int((anchor["heading_deg"] + 22.5) // 45) % 8]
    context["model_context"] = {"status": context["status"], "context_hash": context["context_hash"], "reason": reason,
                                "anchors": curated, "limitations": assumptions,
                                "placement": "Road offset_m starts at anchor start; length_m is along-road length. Road crossing uses length_m for band thickness (1.5–6 m), width_m defaults to the road span. A marked_crossing anchor is the walking alignment; its length_m is the marked span and width_m is band thickness. Left/right are relative to anchor direction. Omit dimensions to use bounded conceptual defaults."}
    from junction_context import model_junction_context
    context['model_context'].update(model_junction_context(context['junctions'], anchors))
    return json.loads(json.dumps(context, allow_nan=False))
