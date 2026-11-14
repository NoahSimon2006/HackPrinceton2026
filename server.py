"""Local-only Vexcel map server. Keys and CoStar source records stay on this machine."""
from __future__ import annotations

import json
import math
import os
import re
import time
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from hydrology import RAINFALL, WATERSHEDS, rainfall_at, rainfall_contours, watershed_at
from site_evidence import imagery_evidence
from site_measurements import validate_inputs

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
LA_BOUNDS = (-118.67, 33.70, -118.10, 34.35)  # west, south, east, north
LAYERS = "urban,urban-r,wide-area,urban-g"
VEXCEL = "https://api.vexcelgroup.com/v2"
STATIC = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js",
          "/planner.js": "planner.js",
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
        if error.code in (401, 403):
            raise ValueError("Vexcel rejected the key or imagery access.") from None
        if error.code == 404:
            raise ValueError("No Vexcel imagery is available here.") from None
        raise ValueError(f"Vexcel request failed ({error.code}).") from None
    except (URLError, TimeoutError):
        raise ValueError("Vexcel could not be reached. Check the connection.") from None


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
    if not features:
        raise ValueError("Vexcel returned no coverage for Los Angeles.")
    # Only geometry is needed to enforce the chosen pan boundary.
    _coverage = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": feature["geometry"], "properties": {}}
        for feature in features if feature.get("geometry")
    ], "bounds": LA_BOUNDS}
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
            address = record.get("primaryAddress") or {}
            try:
                lat, lon = float(address["latitude"]), float(address["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (LA_BOUNDS[0] <= lon <= LA_BOUNDS[2]
                    and LA_BOUNDS[1] <= lat <= LA_BOUNDS[3]):
                continue
            address_text = " ".join(" ".join(str(address.get(key) or "") for key in
                                    ("streetNumber", "streetDirection", "streetName", "streetType")).split())
            item = {
                "id": str(record.get("id", "")), "lat": lat, "lon": lon,
                "name": str(record.get("buildingName") or address_text or "Unnamed property").strip(),
                "address": address_text,
                "type": types.get(str(record.get("propertyType")), "Unknown"),
            }
            items.append(item)
            apartment = record.get("propertyApartment") or {}
            vacancy = apartment.get("vacancyPercent")
            parking = [entry["totalSpaces"] for entry in (record.get("parking") or [])
                       if entry.get("totalSpaces") is not None]
            subtype = record.get("propertyIndustrial") or record.get("propertyRetail") or record.get("propertyFlex") or {}
            docks = [subtype[key] for key in ("numExternalLoadingDocks", "numInternalLoadingDocks")
                     if subtype.get(key) is not None]
            details[item["id"]] = {
                "propertyType": item["type"],
                "units": apartment.get("totalNumUnits"),
                "vacancyPercent": vacancy if isinstance(vacancy, (int, float)) and 0 <= vacancy <= 100 else None,
                "reportedParkingSpaces": sum(parking) if parking else None,
                "buildingAreaSqFt": record.get("grossBuildingAreaSquareFeet"),
                "reportedLoadingDocks": sum(docks) if docks else None,
            }
            lines = []
            for block in (record.get("propertyRetail"), record.get("land")):
                for entry in (block or {}).get("frontage") or []:
                    shape = (entry.get("footprint") or {}).get("shape")
                    if shape and shape.get("type") == "LineString":
                        lines.append({"geometry": shape, "street": entry.get("streetName"),
                                      "curbCuts": entry.get("numCurbCuts")})
            if lines:
                frontages[item["id"]] = lines
    return items, details, frontages


def nearby_frontages(lon, lat, property_id=None):
    items, _, frontages = property_catalog()
    scale = math.cos(math.radians(lat))
    matches = []
    for prop in items:
        if math.hypot((prop["lon"] - lon) * scale, prop["lat"] - lat) * 111_320 <= 110:
            matches.extend({**line, "selectedProperty": prop["id"] == property_id}
                           for line in frontages.get(prop["id"], ()))
    return matches[:12]


def site_coordinates(query):
    lat = float(query.get("lat", [""])[0])
    lon = float(query.get("lon", [""])[0])
    west, south, east, north = LA_BOUNDS
    if not (west <= lon <= east and south <= lat <= north):
        raise ValueError("Select a site within the Los Angeles map.")
    return lon, lat


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
        if urlsplit(self.path).path != "/api/site-analysis":
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
            lon, lat = site_coordinates({"lat": [data["lat"]], "lon": [data["lon"]]})
            workflow = data["workflow"]
            question = data["question"].strip()
            if workflow not in ("street", "water") or not 0 < len(question) <= 1500:
                raise ValueError("Choose a workflow and enter a question up to 1,500 characters.")
            markings, scenario = validate_inputs(data.get("markings", []), data.get("rainfallScenario"), workflow, lon, lat)
            property_id = data.get("propertyId")
            if property_id is not None and (not isinstance(property_id, str) or len(property_id) > 80):
                raise ValueError("Invalid property reference.")
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
            selected = next((item for item in items if item["id"] == property_id and
                             abs(item["lat"] - lat) < .00001 and abs(item["lon"] - lon) < .00001), None)
            return (details[property_id] if selected else None), nearby_frontages(lon, lat, property_id if selected else None)

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
        try:
            result = analyze_site(
                key, os.getenv("GROK_MODEL", "grok-4.7"), question, workflow, markings,
                lambda group: imagery_evidence(vexcel_request, LAYERS, lon, lat, workflow, group),
                property_context, hydrology_context,
                lon=lon, lat=lat, scenario=scenario,
            )
        except Exception as error:
            self.log_error("Planner agent failed (%s)", type(error).__name__)
            self.send_json(503, {"error": "The planning agent could not finish this request."})
            return
        self.send_json(200, result)

    def do_GET(self):
        path = urlsplit(self.path)
        try:
            if path.path in STATIC:
                file = PUBLIC / STATIC[path.path]
                mime = "text/html" if file.suffix == ".html" else (
                    "text/css" if file.suffix == ".css" else "text/javascript")
                # Local development reads assets from disk on every request.
                # Revalidate the page so reloads don't keep an older app bundle.
                cache = "public, max-age=3600" if file.parent.name == "vendor" else "no-cache"
                self.send(200, file.read_bytes(), mime, cache)
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
        except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
            self.send_json(503, {"error": str(error)})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"Sustainability Map: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
