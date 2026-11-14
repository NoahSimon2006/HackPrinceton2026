"""Serve Crossing Lab and its integrations on the local machine."""
import json
import math
import mimetypes
import os
import re
from collections import Counter
from functools import cache, lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from dotenv import load_dotenv
from investigations import Investigations, JobError

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
PUBLIC = ROOT / "public"
STATIC = {
    "/": "index.html", "/index.html": "index.html", "/styles.css": "styles.css",
    "/app.js": "app.js", "/data/la.json": "data/la.json", "/data/ccrs.json": "data/ccrs.json",
    "/investigator.js": "investigator.js",
    "/vendor/leaflet.css": "vendor/leaflet.css",
    "/vendor/leaflet.js": "vendor/leaflet.js",
    "/vendor/leaflet-heat.js": "vendor/leaflet-heat.js",
}
VEXCEL_URL = "https://api.vexcelgroup.com/v2/ortho/extract"
VEXCEL_TILE_URL = "https://api.vexcelgroup.com/v2/ortho/tile"
CRASH_SOURCE = "LA Open Data historical collisions (d5tf-ez2w)"
MAX_IMAGE = 5 * 1024 * 1024
EXPENSIVE_RUNS = BoundedSemaphore(2)
TILE_RUNS = BoundedSemaphore(4)
MAX_TILE = 512 * 1024
COSTAR_RADIUS_M = 250


class RequestError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@cache
def collision_sites():
    sites = json.loads((PUBLIC / "data/la.json").read_text())["sites"]
    return {site["name"]: site for site in sites}


@cache
def commercial_properties(directory):
    root = Path(directory).expanduser()
    types = json.loads((root / "schemas/enums.json").read_text())["PropertyType"]
    properties = []
    with (root / "data/commercial-property.jsonl").open(encoding="utf-8") as records:
        for line in records:
            record = json.loads(line)
            address = record.get("primaryAddress") or {}
            try:
                lat = float(address["latitude"])
                lon = float(address["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            label = types.get(str(record.get("propertyType")), "Unknown")
            properties.append((lat, lon, label))
    return properties


def nearby_properties(site):
    directory = os.getenv("COSTAR_KIT_DIR", "").strip()
    if not directory:
        raise RequestError(503, "Set COSTAR_KIT_DIR to the extracted CoStar kit.")
    try:
        properties = commercial_properties(directory)
    except (OSError, KeyError, ValueError):
        raise RequestError(503, "The CoStar property file or its type lookup could not be read.") from None
    # Local distance approximation over a 250 m radius from the reported point.
    meters_per_degree = math.pi * 6_371_000 / 180
    lon_scale = math.cos(math.radians(site["lat"]))
    counts = Counter(
        label for lat, lon, label in properties
        if meters_per_degree * math.hypot(lat - site["lat"], (lon - site["lon"]) * lon_scale)
        <= COSTAR_RADIUS_M
    )
    return {"radius_m": COSTAR_RADIUS_M, "total": counts.total(), "types": dict(counts.most_common())}


def vexcel_image(request, max_bytes=MAX_IMAGE):
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            if response.status != 200 or response.headers.get_content_type() != "image/jpeg":
                raise RequestError(502, "Vexcel did not return aerial imagery for this area.")
            image = response.read(max_bytes + 1)
    except HTTPError as error:
        messages = {
            401: "Vexcel rejected the API key.",
            403: "Vexcel denied access to this imagery. Check the key and event coverage.",
            404: "Vexcel has no imagery for this location.",
            429: "Vexcel’s request limit was reached. Try again shortly.",
        }
        raise RequestError(502, messages.get(error.code, "Vexcel imagery is temporarily unavailable.")) from None
    except (URLError, TimeoutError):
        raise RequestError(502, "The Vexcel request timed out or could not connect.") from None
    if len(image) > max_bytes or not image.startswith(b"\xff\xd8\xff"):
        raise RequestError(502, "Vexcel returned an invalid or oversized image.")
    return image


@lru_cache(maxsize=128)
def aerial_tile(zoom, tile_x, tile_y):
    """Proxy fixed XYZ tiles; retain at most 64 MiB in RAM, never on disk."""
    if (any(type(value) is not int for value in (zoom, tile_x, tile_y))
            or not 10 <= zoom <= 20
            or not 0 <= tile_x < 2 ** zoom or not 0 <= tile_y < 2 ** zoom):
        raise RequestError(400, "Invalid map tile.")
    key = os.getenv("VEXCEL_API_KEY", "").strip()
    if not key:
        raise RequestError(503, "A Vexcel API key is required. Set VEXCEL_API_KEY in the local .env and restart the server.")
    query = urlencode({
        "layer": "urban,urban-r,wide-area,urban-g", "zoom": zoom,
        "tile-x": tile_x, "tile-y": tile_y, "image-format": "jpeg",
    })
    request = Request(f"{VEXCEL_TILE_URL}?{query}", headers={
        "X-API-KEY": key, "Accept": "image/jpeg",
    })
    if not TILE_RUNS.acquire(timeout=10):
        raise RequestError(429, "Vexcel tiles are still loading. Try again shortly.")
    try:
        return vexcel_image(request, MAX_TILE)
    finally:
        TILE_RUNS.release()


def aerial_image(site):
    key = os.getenv("VEXCEL_API_KEY", "").strip()
    if not key:
        raise RequestError(503, "A Vexcel API key is required.")
    lat, lon = site["lat"], site["lon"]
    offset_lat = 90 / 111_195
    offset_lon = offset_lat / math.cos(math.radians(lat))
    west, east, south, north = lon - offset_lon, lon + offset_lon, lat - offset_lat, lat + offset_lat
    corners = [(west, south), (east, south), (east, north), (west, north), (west, south)]
    polygon = ", ".join(f"{x:.7f} {y:.7f}" for x, y in corners)
    payload = {
        "wkt": f"POLYGON(({polygon}))", "srid": 4326,
        "layer": "urban,urban-r,wide-area,urban-g", "crop": "bounding_box",
        "image-format": "jpeg", "destination-dimensions": "800,800",
    }
    request = Request(VEXCEL_URL, data=json.dumps(payload).encode(), headers={
        "X-API-KEY": key, "Content-Type": "application/json", "Accept": "image/jpeg",
    })
    return vexcel_image(request)


INVESTIGATIONS = Investigations(aerial_image)


class Handler(BaseHTTPRequestHandler):
    def send_data(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        self.send_data(status, "application/json", json.dumps(payload).encode())

    def local_request(self):
        return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}",
                                            f"localhost:{self.server.server_port}"}

    def do_GET(self):
        if not self.local_request():
            self.send_error(404)
            return
        tile = re.fullmatch(r"/api/vexcel/tiles/(\d{1,2})/(\d{1,7})/(\d{1,7})\.jpg", self.path)
        if tile:
            origin = self.headers.get("Origin")
            if (self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none")
                    or origin not in (None, f"http://{self.headers.get('Host')}")):
                self.send_json(403, {"error": "Use the local Crossing Lab map."})
                return
            try:
                image = aerial_tile(*(int(value) for value in tile.groups()))
                self.send_data(200, "image/jpeg", image)
            except RequestError as error:
                self.send_json(error.status, {"error": str(error)})
            except (BrokenPipeError, ConnectionResetError):
                pass  # Panning can cancel a tile that is no longer visible.
            except Exception as error:
                self.log_error("Vexcel tile error (%s)", type(error).__name__)
                self.send_json(502, {"error": "Vexcel imagery could not load. Try again shortly."})
            return
        if self.path not in STATIC:
            self.send_error(404)
            return
        path = PUBLIC / STATIC[self.path]
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404)
            return
        self.send_data(200, mimetypes.guess_type(path.name)[0] or "application/octet-stream", data)

    def read_payload(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise ValueError
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict) or not isinstance(payload.get("site"), str):
                raise ValueError
        except (ValueError, UnicodeError):
            raise RequestError(400, "Select a valid intersection.") from None
        site = collision_sites().get(payload["site"])
        if site is None:
            raise RequestError(400, "Select a valid intersection.")
        return site, payload

    def do_POST(self):
        origin = self.headers.get("Origin")
        if (not self.local_request() or origin != f"http://{self.headers.get('Host')}"
                or self.headers.get_content_type() != "application/json"):
            self.send_json(403, {"error": "Use the local Crossing Lab page."})
            return
        try:
            site, payload = self.read_payload()
            if self.path == "/api/investigate":
                if type(payload.get("refresh", False)) is not bool:
                    raise RequestError(400, "Refresh must be true or false.")
                self.send_json(200, INVESTIGATIONS.start(site, payload.get("refresh", False)))
                return
            if self.path in {"/api/investigation", "/api/cancel", "/api/followup"}:
                id_ = payload.get("run_id")
                if not isinstance(id_, str) or not re.fullmatch(r"[a-f0-9]{32}", id_):
                    raise RequestError(400, "Select a valid investigation.")
                if self.path == "/api/investigation":
                    result = INVESTIGATIONS.snapshot(id_, site["name"])
                elif self.path == "/api/cancel":
                    result = INVESTIGATIONS.cancel(id_, site["name"])
                else:
                    result = INVESTIGATIONS.followup(id_, site["name"], payload.get("question"))
                self.send_json(200, result)
                return
            if self.path == "/api/costar":
                self.send_json(200, nearby_properties(site))
                return
            if self.path != "/api/vexcel":
                raise RequestError(404, "Unknown feature.")
            if not EXPENSIVE_RUNS.acquire(blocking=False):
                raise RequestError(429, "Two requests are already running. Try again shortly.")
            try:
                self.send_data(200, "image/jpeg", aerial_image(site))
            finally:
                EXPENSIVE_RUNS.release()
        except (RequestError, JobError) as error:
            self.send_json(error.status, {"error": str(error)})
        except FileNotFoundError:
            self.send_json(503, {"error": "Run python3 scripts/import_la.py to load LA collision totals."})
        except Exception as error:
            # Provider exceptions can include request details. Log only the class.
            self.log_error("Integration error (%s)", type(error).__name__)
            self.send_json(502, {"error": "This integration could not complete the request."})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"Crossing Lab is listening at http://127.0.0.1:{port}", flush=True)
        server.serve_forever()
