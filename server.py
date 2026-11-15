"""Local-only Vexcel map server. Keys and CoStar source records stay on this machine."""
from __future__ import annotations

import json
import math
import os
import re
import time
from copy import deepcopy
from contextlib import nullcontext
from project_store import ProjectStore, ProjectConflict, validate_snapshot
from threading import BoundedSemaphore, Lock, Thread
from agent_activity import Activity, RunCancelled, TransientSourceError
from discovery import load_discovery, map_discovery, query_area, area_facts, discovery_context, traffic_context, traffic_context_at_site
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from hydrology import RAINFALL, WATERSHEDS, rainfall_at, rainfall_contours, watershed_at
from site_evidence import imagery_evidence
from site_measurements import validate_inputs
from site_identity import resolve_site
from property_address import display_text, format_property_address
from stormwater_settings import validate_settings

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
LA_BOUNDS = (-118.67, 33.70, -118.10, 34.35)  # west, south, east, north
LAYERS = "urban,urban-r,wide-area,urban-g"
VEXCEL = "https://api.vexcelgroup.com/v2"
ANALYSIS_SLOTS = BoundedSemaphore(2)
ACTIVE_ANALYSES = {}
ANALYSIS_LOCK = Lock()
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js",
          "/discovery.js": "discovery.js", "/analysis-stream.js": "analysis-stream.js", "/planner.js": "planner.js", "/proposal.js": "proposal.js",
          "/site-view.js": "site-view.js", "/projects.js": "projects.js", "/scouting.js": "scouting.js",
          "/concept-scene.js": "concept-scene.js", "/concept-scene-renderer.js": "concept-scene-renderer.js",
          "/vendor/three.module.js": "vendor/three.module.js", "/vendor/three.core.js": "vendor/three.core.js",
          "/vendor/OrbitControls.js": "vendor/OrbitControls.js", "/vendor/three.LICENSE": "vendor/three.LICENSE",
          "/vector-zoom.js": "vector-zoom.js", "/guide.js": "guide.js",
          "/styles.css": "styles.css", "/vendor/leaflet.js": "vendor/leaflet.js",
          "/vendor/leaflet.css": "vendor/leaflet.css"}


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def vexcel_request(path, params, accept, limit, *, post=False, timeout=18):
    key = os.getenv("VEXCEL_API_KEY", "").strip()
    if not key:
        raise ValueError("Vexcel key is missing from the local .env file.")
    headers = {"X-API-KEY": key, "Accept": accept}
    if post:
        headers["Content-Type"] = "application/json"
        request = Request(f"{VEXCEL}{path}", data=json.dumps(params).encode(), headers=headers)
    else:
        request = Request(f"{VEXCEL}{path}?{urlencode(params)}", headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError("Vexcel response exceeded the size limit.")
            return data
    except HTTPError as error:
        if error.code in (429, 502, 503, 504):
            raise TransientSourceError("Vexcel temporarily unavailable.") from None
        if error.code in (401, 403):
            raise ValueError("Vexcel rejected the key or imagery access.") from None
        if error.code == 404:
            raise ValueError("No Vexcel property outlines are available at this point." if path == "/property/extract"
                             else "No Vexcel imagery is available here.") from None
        raise ValueError(f"Vexcel request failed ({error.code}).") from None
    except (URLError, TimeoutError):
        raise TransientSourceError("Vexcel could not be reached. Check the connection.") from None


_coverage = None
_coverage_time = 0.0


def coverage():
    global _coverage, _coverage_time
    if _coverage is not None and time.time() - _coverage_time < 3600:
        return _coverage
    west, south, east, north = LA_BOUNDS
    wkt = (f"POLYGON(({west} {south},{east} {south},{east} {north},"
           f"{west} {north},{west} {south}))")
    raw = vexcel_request("/ortho/collections", {
        "wkt": wkt, "srid": 4326, "layer": LAYERS, "metadata-format": "JSON",
        "include": "layer,collection,geometry", "order-by": "default",
    }, "application/json", 5_000_000)
    data = json.loads(raw)
    features = data.get("features", [])
    if not isinstance(features, list) or not features:
        raise ValueError("Vexcel returned no coverage for Los Angeles.")
    from shapely.geometry import shape
    from shapely.errors import ShapelyError
    valid_features = []
    for feature in features:
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        try:
            polygon = shape(geometry)
        except (ShapelyError, TypeError, ValueError, KeyError, IndexError, OverflowError):
            continue
        if polygon.is_empty or not polygon.is_valid or not all(math.isfinite(value) for value in polygon.bounds):
            continue
        valid_features.append(feature)
    if not valid_features:
        raise ValueError("Vexcel returned no usable imagery coverage.")
    # A malformed historical collection must not disable other valid coverage.
    # Exclude it without repairing/expanding source geometry; disclose the gap.
    excluded = len(features) - len(valid_features)
    _coverage = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": feature["geometry"], "properties": {}}
        for feature in valid_features
    ], "bounds": LA_BOUNDS, "status": "partial" if excluded else "ready", "excludedFeatures": excluded}
    _coverage_time = time.time()
    return _coverage


@lru_cache(maxsize=256)
def tile(z, x, y):
    data = vexcel_request("/ortho/tile", {
        "layer": LAYERS, "zoom": z, "tile-x": x, "tile-y": y,
        "image-format": "jpeg",
    }, "image/jpeg", 800_000)
    if not data.startswith(b"\xff\xd8\xff"):
        raise ValueError("Vexcel returned an invalid image tile.")
    return data


def reported_number(value, *, count=False):
    """A missing/invalid source value is unknown, never a coerced count."""
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 or (count and value != int(value))):
        return None
    return int(value) if count else value


def reported_total(values):
    """Report a total only when every supplied category has a valid count."""
    counts = [reported_number(value, count=True) for value in values]
    return sum(counts) if counts and all(value is not None for value in counts) else None


@lru_cache(maxsize=1)
def property_catalog():
    directory = os.getenv("COSTAR_KIT_DIR", "").strip()
    if not directory:
        raise ValueError("CoStar kit directory is not configured.")
    root = Path(directory).expanduser()
    types = json.loads((root / "schemas/enums.json").read_text())["PropertyType"]
    items = []
    details, frontages = {}, {}
    with (root / "data/commercial-property.jsonl").open(encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("CoStar property data is malformed.")
            address = record.get("primaryAddress") or {}
            try:
                lat, lon = float(address["latitude"]), float(address["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (LA_BOUNDS[0] <= lon <= LA_BOUNDS[2]
                    and LA_BOUNDS[1] <= lat <= LA_BOUNDS[3]):
                continue
            raw_id = record.get("id")
            if not ((type(raw_id) is int and raw_id > 0) or (isinstance(raw_id, str) and raw_id.strip())):
                raise ValueError("CoStar property identity is missing or invalid.")
            address_text = format_property_address(address)
            item = {
                "id": str(raw_id).strip(), "lat": lat, "lon": lon,
                "name": display_text(record.get("buildingName"), address_text or "Unnamed property"),
                "address": address_text,
                "type": types.get(str(record.get("propertyType")), "Unknown"),
            }
            if not item["id"] or item["id"] in details:
                raise ValueError("CoStar property identities are missing or duplicated.")
            items.append(item)
            apartment = record.get("propertyApartment") or {}
            parking = [entry.get("totalSpaces") if isinstance(entry, dict) else None
                       for entry in (record.get("parking") or [])]
            subtype = record.get("propertyIndustrial") or record.get("propertyRetail") or record.get("propertyFlex") or {}
            docks = [subtype.get(key) for key in ("numExternalLoadingDocks", "numInternalLoadingDocks")]
            details[item["id"]] = {
                "propertyType": item["type"],
                "units": reported_number(apartment.get("totalNumUnits"), count=True),
                "reportedParkingSpaces": reported_total(parking),
                "buildingAreaSqFt": reported_number(record.get("grossBuildingAreaSquareFeet")),
                "reportedLoadingDocks": reported_total(docks),
            }
            lines = []
            for block in (record.get("propertyRetail"), record.get("land")):
                for entry in (block or {}).get("frontage") or []:
                    shape = (entry.get("footprint") or {}).get("shape")
                    # Preserve missing/malformed geometry so measurement cannot
                    # mistake an incomplete frontage source for no constraints.
                    lines.append({"geometry": shape, "street": entry.get("streetName"),
                                  "curbCuts": entry.get("numCurbCuts")})
            if lines:
                frontages[item["id"]] = lines
    return items, details, frontages


def nearby_properties(items, lon, lat, radius):
    scale = math.cos(math.radians(lat))
    matches = [(math.hypot((p["lon"] - lon) * scale, p["lat"] - lat) * 111_320, p) for p in items]
    return [item for distance, item in sorted(matches, key=lambda match: match[0]) if distance <= radius]


def nearby_frontages(lon, lat, property_id=None, *, radius=110):
    items, _, frontage_catalog = property_catalog()
    return [{**line, "selectedProperty": item["id"] == property_id}
            for item in nearby_properties(items, lon, lat, radius)
            for line in frontage_catalog.get(item["id"], ())]


OUTLINE_LOCK = Lock()


@lru_cache(maxsize=128)
def _site_outlines(lon, lat, workflow, period):
    return imagery_evidence(vexcel_request, LAYERS, lon, lat, workflow, "outlines")


def site_outlines(lon, lat, workflow):
    # Resolution and parallel agent tools reuse the same bounded source request.
    # Measurements annotate their copy; never mutate the cached source evidence.
    with OUTLINE_LOCK:
        return deepcopy(_site_outlines(lon, lat, workflow, int(time.monotonic() // 300)))


def site_resolution(lon, lat, workflow, property_id=None):
    items = property_catalog()[0]
    radius = 200 if workflow == "street" else 110
    if property_id is not None and any(
            p["id"] == property_id and abs(p["lat"] - lat) < .00001 and abs(p["lon"] - lon) < .00001 for p in items):
        return resolve_site(items, lon, lat, [], property_id=property_id, radius=radius)
    try:
        outlines = site_outlines(lon, lat, workflow)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        if property_id is not None:
            raise ValueError("Property association could not be checked at this location.") from None
        return {**resolve_site(items, lon, lat, [], radius=radius), "status": "unavailable",
                "message": "Parcel evidence is unavailable. Nearby properties remain separate choices; this point has not been assigned to one."}
    return resolve_site(items, lon, lat, outlines, property_id=property_id, radius=radius)


def site_coordinates(query):
    lat = float(query.get("lat", [""])[0])
    lon = float(query.get("lon", [""])[0])
    west, south, east, north = LA_BOUNDS
    if not (west <= lon <= east and south <= lat <= north):
        raise ValueError("Select a site within the Los Angeles map.")
    return lon, lat


def analysis_identity(data):
    site_id = data.get("siteId")
    revision, input_revision = data.get("proposalRevision"), data.get("inputRevision")
    if (not isinstance(site_id, str) or not site_id.strip() or len(site_id) > 160
            or type(revision) is not int or not 1 <= revision <= 100
            or type(input_revision) is not int or not 0 <= input_revision <= 10000):
        raise ValueError("Invalid site revision. Reload the map and select the site again.")
    return {"site_id": site_id, "revision": revision, "input_revision": input_revision}


@lru_cache(maxsize=1)
def project_store():
    store = ProjectStore(ROOT / "private" / "agent-workspace")
    store.recover_interrupted()
    return store


@lru_cache(maxsize=1)
def scout_store():
    from scout_store import ScoutStore
    return ScoutStore(project_store())


def start_scout(data):
    from scout_store import validate_search
    validate_search(data)
    key = os.getenv('GROK_API_KEY', '').strip()
    if not key:
        raise ValueError('Set GROK_API_KEY to use the planning agent.')
    if not ANALYSIS_SLOTS.acquire(blocking=False):
        raise ProjectConflict('Two planning investigations are already running. Try again shortly.')
    store = scout_store()
    activity = Activity(seconds=240)
    try:
        search = store.begin(data, activity.id)
    except Exception:
        ANALYSIS_SLOTS.release()
        raise
    search_id = search['id']
    activity.current = lambda: store.is_current(search_id, activity.id)
    activity.emit = lambda event: store.event(search_id, event)
    with ANALYSIS_LOCK:
        ACTIVE_ANALYSES[activity.id] = activity

    def run():
        try:
            from opportunity_scout import research_candidates, refresh_traffic_candidates
            from scout_agent import review_scout
            excluded = list({item for batch in search['batches'] for c in batch['candidates']
                for item in [c['id'], *c.get('provenance', {}).get('groupedCandidateIds', c.get('groupedCandidateIds', []))]})
            def research():
                return research_candidates(search['workflow'], search['bounds'], excluded,
                    check=activity.check, emit=lambda event: activity.event('lead', 'source-screen', 'running',
                        event.get('summary', event.get('message', 'Researching candidate source evidence.'))))
            result = review_scout(key, os.getenv('GROK_MODEL', 'grok-4.7'), search['goal'], search['workflow'],
                research, activity, lambda path, content: store.artifact(search_id, activity.id, path, content))
            activity.check()
            if search['workflow'] == 'street':
                result = refresh_traffic_candidates(result, search['bounds'], check=activity.check)
                if result.get('reviewStale'):
                    result['summary'] = 'Current flow was refreshed after investigation. The source screen is current; earlier agent commentary has been discarded.'
                    result.pop('review', None)
                    result.pop('agentReview', None)
            activity.event('lead', 'shortlist', 'completed', 'Location investigation finished. Choose a location to develop it.')
            store.finish(search_id, activity.id, result)
        except RunCancelled:
            store.finish(search_id, activity.id, status='canceled', error='Investigation canceled or time budget reached.')
        except Exception as error:
            # Provider messages may contain request URLs/credentials. Never return them.
            print('Location investigation failed:', type(error).__name__, flush=True)
            store.finish(search_id, activity.id, status='failed', error='The investigation could not finish. Retry the area search; earlier history is preserved.')
        finally:
            with ANALYSIS_LOCK:
                ACTIVE_ANALYSES.pop(activity.id, None)
            ANALYSIS_SLOTS.release()
    Thread(target=run, name='area-scout-' + activity.id[:8], daemon=True).start()
    return store.get(search_id)


class Handler(BaseHTTPRequestHandler):
    def send(self, status, content, mime, cache="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status, data):
        self.send(status, json.dumps(data, separators=(",", ":")).encode(), "application/json")

    def do_POST(self):
        if urlsplit(self.path).path not in ("/api/site-analysis", "/api/site-analysis/cancel", "/api/projects", "/api/scouts", "/api/scouts/cancel", "/api/scouts/select"):
            self.send_json(404, {"error": "Not found."})
            return
        if self.headers.get_content_type() != "application/json" or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send_json(400, {"error": "Send a JSON request from the map."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32_000:
                raise ValueError("The site request is too large or empty.")
            data = json.loads(self.rfile.read(length))
            path = urlsplit(self.path).path
            if path == '/api/scouts':
                self.send_json(202, start_scout(data))
                return
            if path == '/api/scouts/cancel':
                run_id = scout_store().cancel(data.get('id'), data.get('runId'))
                with ANALYSIS_LOCK:
                    active = ACTIVE_ANALYSES.get(run_id)
                    if active:
                        active.cancelled.set()
                self.send_json(200, scout_store().get(data.get('id')))
                return
            if path == '/api/scouts/select':
                self.send_json(200, scout_store().select(data.get('id'), data.get('candidateId')))
                return
            if urlsplit(self.path).path == "/api/projects":
                saved = project_store().save(data.get("snapshot"), data.get("projectId"), data.get("expectedVersion"))
                self.send_json(200, saved)
                return
            if urlsplit(self.path).path == "/api/site-analysis/cancel":
                run_id = data.get("runId")
                if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
                    raise ValueError("Invalid analysis reference.")
                with ANALYSIS_LOCK:
                    active = ACTIVE_ANALYSES.get(run_id)
                    if active: active.cancelled.set()
                self.send_json(202, {"canceled": bool(active)})
                return
            lon, lat = site_coordinates({"lat": [data["lat"]], "lon": [data["lon"]]})
            workflow = data["workflow"]
            question = data["question"].strip()
            if workflow not in ("street", "water") or not 0 < len(question) <= 1500:
                raise ValueError("Choose a workflow and enter a question up to 1,500 characters.")
            markings, scenario = validate_inputs(data.get("markings", []), data.get("rainfallScenario"), workflow, lon, lat)
            water_settings = validate_settings(data.get('stormwaterSettings'), workflow, markings=markings, for_analysis=True)
            if data.get("waterDesign") is not None:
                raise ValueError("The separate placement comparison has been retired. Analyze the site and add optional map constraints instead.")
            try:
                selected_discovery = discovery_context(workflow, data.get("discoveryReference"), lon, lat)
            except ValueError as error:
                if workflow != "street" or "Traffic snapshot expired" not in str(error):
                    raise
                # Keep the chosen site. The bounded neighborhood tool will read
                # a fresh snapshot; expired measurements are never reused.
                selected_discovery = None
            reference = data.get("discoveryReference")
            traffic = (traffic_context(reference, lon, lat) if reference and reference.get("layer") == "turning"
                       else traffic_context_at_site(lon, lat)) if workflow == "street" else None
            identity = analysis_identity(data)
            property_id = data.get("propertyId")
            if property_id is not None and (not isinstance(property_id, str) or len(property_id) > 80):
                raise ValueError("Invalid property reference.")
            project = project_store().get(data["projectId"]) if data.get("projectId") else None
            if project:
                snapshot = validate_snapshot({key: data.get(key) for key in project["snapshot"]})
                if data.get("projectVersion") != project["version"] or snapshot != project["snapshot"]:
                    raise ProjectConflict("Project inputs changed. Save the latest inputs before continuing.")
                try:
                    project['scouting'] = json.loads(project_store().artifact(project['id'], '/project/scouting-selection.json'))
                except ValueError:
                    pass
        except ProjectConflict as error:
            self.send_json(409, {"error": str(error)})
            return
        except OSError:
            self.send_json(503, {"error": "The local analysis source is unavailable. Check the source configuration and retry."})
            return
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
            return
        except (AttributeError, KeyError, TypeError):
            self.send_json(400, {"error": "Select a site and enter a planning question up to 1,500 characters."})
            return

        key = os.getenv("GROK_API_KEY", "").strip()
        if not key:
            self.send_json(503, {"error": "Set GROK_API_KEY to use the planning agent."})
            return

        def property_context():
            items, details, _ = property_catalog()
            selected = site_resolution(lon, lat, workflow, property_id)["property"]
            selected_id = selected["id"] if selected else None
            radius = 200 if workflow == "street" else 110
            frontages = nearby_frontages(lon, lat, selected_id, radius=radius)
            nearby = nearby_properties(items, lon, lat, radius)
            if workflow == 'water':
                # Host association must inspect every catalog point within a
                # possible parcel, not only the radius-limited nearby inventory.
                catalog = [{k: item[k] for k in ('id', 'lon', 'lat', 'type')} | {'details': details[item['id']]} for item in items]
                nearby = [{k: item[k] for k in ('id', 'lon', 'lat', 'type')} | {'details': details[item['id']]} for item in nearby]
                return (details[selected_id] if selected else None), frontages, nearby, catalog
            return (details[selected_id] if selected else None), frontages, nearby

        def hydrology_context():
            result = {"unavailable": []}
            for name, fetch in (
                ("estimate", lambda: rainfall_at(lon, lat, rainfall_contours(LA_BOUNDS))),
                ("watershed", lambda: {"type": "FeatureCollection", "features": watershed_at(lon, lat)}),
            ):
                try:
                    result[name] = fetch()
                except (OSError, ValueError, KeyError, TypeError):
                    result["unavailable"].append("rainfall" if name == "estimate" else name)
            return result

        try:
            from site_agent import analyze_site
        except ImportError:
            self.send_json(503, {"error": "Install requirements.txt in the Python environment that runs the map."})
            return
        if not ANALYSIS_SLOTS.acquire(blocking=False):
            self.send_json(429, {"error":"Two site analyses are already running. Try again shortly."})
            return
        streaming = "application/x-ndjson" in self.headers.get("Accept", "")
        def write_event(event):
            self.wfile.write(json.dumps(event, separators=(",", ":")).encode() + b"\n")
            self.wfile.flush()
        def emit(event):
            if project:
                project_store().event(project["id"], event)
            if streaming:
                write_event(event)
        activity = Activity(emit, seconds=420 if traffic else 240,
                            current=(lambda: project_store().is_current(project["id"], activity.id)) if project else None)
        activity.project_id = project["id"] if project else None
        with ANALYSIS_LOCK:
            if project:
                try:
                    if any(getattr(run, "project_id", None) == project["id"] for run in ACTIVE_ANALYSES.values()):
                        raise ProjectConflict("This project's previous run is still stopping. Try continuing again shortly.")
                    project_store().begin(project["id"], project["version"], activity.id)
                except ProjectConflict as error:
                    ANALYSIS_SLOTS.release()
                    self.send_json(409, {"error":str(error)})
                    return
            ACTIVE_ANALYSES[activity.id] = activity
        try:
            if streaming:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
            with project_store().checkpointer() if project else nullcontext() as saver:
                result = analyze_site(
                    key, os.getenv("GROK_MODEL", "grok-4.7"), question, workflow, markings,
                    lambda group: site_outlines(lon, lat, workflow) if group == "outlines" else imagery_evidence(vexcel_request, LAYERS, lon, lat, workflow, group),
                    property_context, hydrology_context,
                    lon=lon, lat=lat, scenario=scenario, activity=activity, discovery=selected_discovery,
                    traffic_context=traffic, analysis_identity=identity, allow_generated_timing=True,
                    ranking_policy="environmental-priority-v1",
                    fetch_discovery=lambda: area_facts(workflow, lon, lat),
                    project=project, checkpointer=saver,
                    persist_artifact=(lambda path, content: project_store().artifact(project["id"], path, content, activity.id)) if project else None,
                    stormwater_settings=water_settings,
                )
            if activity.cancelled.is_set():
                result.update(proposal=None, comparison=None, alternatives={}, report=None, waterPlan=None, trafficPlan=None)
            if project:
                status = "canceled" if activity.cancelled.is_set() else "failed" if result.get("analysisError") else "needs_input" if result.get("draftQuestion") else "ready"
                if not project_store().finish(project["id"], activity.id, result, status):
                    result.update(proposal=None, comparison=None, alternatives={}, report=None, waterPlan=None, trafficPlan=None,
                                  analysisError="This run belongs to earlier inputs. Continue the latest saved project.")
                result["projectVersion"] = project["version"]
            if streaming:
                write_event({"type":"result", "run_id":activity.id, "result":result})
            else:
                self.send_json(200, result)
        except (BrokenPipeError, ConnectionResetError):
            activity.cancelled.set()
        except Exception as error:
            self.log_error("Planner agent failed (%s)", type(error).__name__)
            if streaming:
                try:
                    write_event({"type":"error", "run_id":activity.id, "error":"The planning agent could not finish. Retrieved facts remain available; retry analysis."})
                except OSError:
                    activity.cancelled.set()
            else:
                self.send_json(503, {"error":"The planning agent could not finish this request."})
        finally:
            if project and project_store().is_current(project["id"], activity.id):
                project_store().finish(project["id"], activity.id, None,
                                       "canceled" if activity.cancelled.is_set() else "failed")
            with ANALYSIS_LOCK:
                ACTIVE_ANALYSES.pop(activity.id, None)
            ANALYSIS_SLOTS.release()

    def do_GET(self):
        path = urlsplit(self.path)
        try:
            if path.path in ("/demo", "/demo.html"):
                self.send_response(302)
                self.send_header("Location", "/#stormwater")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif path.path in STATIC:
                file = PUBLIC / STATIC[path.path]
                mime = "text/html" if file.suffix == ".html" else (
                    "text/css" if file.suffix == ".css" else "text/javascript" if file.suffix == ".js" else "text/plain")
                # Local development reads assets from disk on every request.
                # Revalidate the page so reloads don't keep an older app bundle.
                cache = "public, max-age=3600" if file.parent.name == "vendor" else "no-cache"
                self.send(200, file.read_bytes(), mime, cache)
            elif path.path == "/api/projects":
                query = parse_qs(path.query)
                self.send_json(200, project_store().get(query["id"][0]) if "id" in query else {"projects":project_store().list()})
            elif path.path == "/api/concept-scene":
                from concept_scene import SceneUnavailable, build_scene, parse_scene_query
                try:
                    query = parse_scene_query(parse_qs(path.query, keep_blank_values=True))
                except SceneUnavailable as error:
                    self.send_json(400, {"error": str(error)})
                    return
                try:
                    project = project_store().get(query.pop("project_id"))
                    result = build_scene(project, **query)
                except ValueError as error:
                    self.send_json(404, {"error": str(error) if isinstance(error, SceneUnavailable)
                        else "The saved project is unavailable. Reopen a planning project."})
                    return
                self.send_json(200, result)
            elif path.path == '/api/scouts':
                query = parse_qs(path.query)
                self.send_json(200, scout_store().get(query['id'][0]) if 'id' in query else {'searches': scout_store().list()})
            elif path.path == "/api/project-artifact":
                query = parse_qs(path.query)
                self.send_json(200, {"path":query.get("path", [""])[0],
                    "content":project_store().artifact(query.get("id", [""])[0], query.get("path", [""])[0])})
            elif path.path == "/api/discovery":
                workflow = parse_qs(path.query).get("workflow", [""])[0]
                self.send_json(200, map_discovery(workflow))
            elif path.path == "/api/discovery-area":
                query = parse_qs(path.query)
                if set(query) - {'workflow','bbox','limit'} or any(len(values)!=1 for values in query.values()):
                    raise ValueError('Invalid discovery area query.')
                bounds = [float(value) for value in query.get('bbox',[''])[0].split(',')]
                self.send_json(200, query_area(query.get('workflow',[''])[0], bounds, int(query.get('limit',['12'])[0])))
            elif path.path == "/api/site-view":
                from site_view import site_view_descriptor, UNAVAILABLE
                query = parse_qs(path.query)
                if set(query) != {"propertyId"} or len(query["propertyId"]) != 1 or not query["propertyId"][0].strip():
                    self.send_json(400, {"error": "Select a property before opening its existing view."})
                    return
                try:
                    result = site_view_descriptor(os.getenv("COSTAR_KIT_DIR", ""), property_catalog()[0], query["propertyId"][0])
                except (OSError, ValueError, KeyError, TypeError):
                    self.send_json(503, {"error": UNAVAILABLE})
                    return
                self.send_json(200, result)
            elif path.path == "/api/site-resolution":
                query = parse_qs(path.query)
                lon, lat = site_coordinates(query)
                workflow = query.get("workflow", [""])[0]
                if workflow not in ("street", "water"):
                    self.send_json(400, {"error": "Choose a planning workflow."})
                    return
                self.send_json(200, site_resolution(lon, lat, workflow, query.get("propertyId", [None])[0]))
            elif path.path == "/api/proposal-fixture":
                from proposal import fixture
                qs = parse_qs(path.query)
                try:
                    result = fixture(float(qs.get("lon", [""])[0]), float(qs.get("lat", [""])[0]),
                        qs.get("workflow", [""])[0], qs.get("site_id", [""])[0],
                        int(qs.get("revision", ["1"])[0]), int(qs.get("input_revision", ["0"])[0]))
                except (ValueError, TypeError):
                    self.send_json(400, {"error": "Invalid development fixture request."})
                    return
                self.send_json(200, result.model_dump(mode="json"))
            elif path.path == "/api/coverage":
                self.send_json(200, coverage())
            elif path.path == "/api/emissions":
                file = PUBLIC / "data" / "emissions.json"
                self.send(200, file.read_bytes(), "application/json", "public, max-age=300")
            elif path.path == "/api/properties":
                qs = parse_qs(path.query)
                raw = qs.get("bbox", [""])[0].split(",")
                if len(raw) != 4:
                    raise ValueError("A bounding box is required.")
                west, south, east, north = map(float, raw)
                if not all(math.isfinite(v) for v in (west, south, east, north)) or west >= east or south >= north:
                    raise ValueError("Invalid bounding box.")
                visible = [p for p in property_catalog()[0] if west <= p["lon"] <= east and south <= p["lat"] <= north]
                self.send_json(200, {"properties": visible, "total": len(visible)})
            elif path.path == "/api/search":
                q = parse_qs(path.query).get("q", [""])[0].strip().casefold()[:100]
                if len(q) < 2:
                    self.send_json(200, {"results": []})
                else:
                    words = q.split()
                    results = [p for p in property_catalog()[0]
                               if all(word in (p["name"] + " " + p["address"]).casefold() for word in words)]
                    self.send_json(200, {"results": results[:8]})
            elif path.path == "/api/property-detail":
                property_id = parse_qs(path.query).get("id", [""])[0]
                detail = property_catalog()[1].get(property_id)
                if detail is None:
                    self.send_json(404, {"error": "Property not found."})
                else:
                    self.send_json(200, detail)
            elif path.path in ("/api/rainfall", "/api/watershed"):
                try:
                    lon, lat = site_coordinates(parse_qs(path.query))
                except ValueError:
                    self.send_json(400, {"error": "Select a valid location within the Los Angeles map."})
                    return
                try:
                    if path.path == "/api/rainfall":
                        self.send_json(200, {"estimate": rainfall_at(lon, lat, rainfall_contours(LA_BOUNDS)),
                                             "source": RAINFALL})
                    else:
                        self.send_json(200, {"type": "FeatureCollection", "features": watershed_at(lon, lat),
                                             "source": WATERSHEDS})
                except (OSError, ValueError, KeyError, TypeError):
                    self.send_json(503, {"error": "LA County hydrology data is temporarily unavailable."})
            elif re.fullmatch(r"/api/tiles/\d{1,2}/\d{1,7}/\d{1,7}\.jpg", path.path):
                _, _, _, z, x, filename = path.path.split("/")
                z, x, y = int(z), int(x), int(filename[:-4])
                if not (10 <= z <= 20 and 0 <= x < 2**z and 0 <= y < 2**z):
                    raise ValueError("Invalid tile coordinates.")
                self.send(200, tile(z, x, y), "image/jpeg")
            else:
                self.send_json(404, {"error": "Not found."})
        except (BrokenPipeError, ConnectionResetError):
            # Do not attempt a second HTTP response after a disconnected tile
            # request has already received its headers.
            return
        except (ValueError, OSError, KeyError, TypeError, AttributeError, OverflowError):
            self.send_json(503, {"error": "The requested local data or provider response is unavailable. Check the source configuration and retry."})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    # Recover interrupted work before concurrent requests can start new runs.
    project_store()
    scout_store()
    print(f"Sustainability Map: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
