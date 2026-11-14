"""Serve an allowlisted Vexcel 3D tile tree without exposing upstream credentials."""
import json
import os
from pathlib import Path
from threading import BoundedSemaphore
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit
from urllib.request import Request, build_opener

from sponsor_data import NoRedirect, SponsorError

HOST = "api.vexcelgroup.com"
PREFIX = "/api/vexcel/scene/"
BASE = f"https://{HOST}/v2/3d/"
COLLECTION = "us-ca-losangeles-downey-2020-2021"
ROOT_QUERY = {"collection": COLLECTION, "layer": "3d-cities"}
TILE_PARAMS = {"collection", "layer", "zoom", "tile-x", "tile-y", "childAOI", "latest", "product-type", "v"}
REQUESTS = BoundedSemaphore(8)
MAX_TILE_BYTES = 12 * 1024 * 1024
CESIUM = Path(__file__).resolve().parent / "node_modules/cesium/Build/Cesium"


def provider_url(kind, query):
    if kind not in {"tileset", "tile"} or len(query) > 1000:
        raise SponsorError(400, "Invalid Vexcel scene resource.")
    args = dict(parse_qsl(query))
    if args.keys() - TILE_PARAMS or args.get("collection", COLLECTION) != COLLECTION:
        raise SponsorError(400, "Invalid Vexcel scene parameters.")
    args.pop("v", None)  # Cesium can append its tileset asset version.
    if not args:
        if kind != "tileset":
            raise SponsorError(400, "Invalid Vexcel tile address.")
        args = ROOT_QUERY
    return BASE + kind + "?" + urlencode(args)


def local_uri(uri, request_url):
    upstream = urlsplit(urljoin(request_url, uri))
    if (upstream.scheme != "https" or upstream.netloc != HOST
            or upstream.path not in {"/v2/3d/tileset", "/v2/3d/tile"}):
        raise SponsorError(502, "Vexcel returned an unexpected 3D tile address.")
    args = [(k, v) for k, v in parse_qsl(upstream.query) if k in TILE_PARAMS]
    return PREFIX + upstream.path.rsplit("/", 1)[1] + "?" + urlencode(args)


def rewrite_tileset(node, request_url):
    for content in [node.get("content", {}), *node.get("contents", [])]:
        for field in ("uri", "url"):
            if field in content:
                content[field] = local_uri(content[field], request_url)
    for child in node.get("children", []):
        rewrite_tileset(child, request_url)


def scene_resource(kind, query):
    url = provider_url(kind, query)
    key = os.getenv("VEXCEL_API_KEY", "").strip()
    if not key:
        raise SponsorError(503, "Set VEXCEL_API_KEY in the local .env to open the street scene.")
    if not REQUESTS.acquire(timeout=8):
        raise SponsorError(429, "The 3D tile queue is busy.")
    try:
        try:
            request = Request(url, headers={"X-API-KEY": key})
            with build_opener(NoRedirect()).open(request, timeout=18) as response:
                data = response.read(MAX_TILE_BYTES + 1)
        except HTTPError as error:
            if error.code in (401, 403):
                raise SponsorError(502, "Vexcel denied access to the 3D mesh.") from None
            if error.code == 404:
                raise SponsorError(404, "Vexcel has no 3D tile here.") from None
            raise SponsorError(502, "Vexcel could not serve this 3D tile.") from None
        except (URLError, TimeoutError):
            raise SponsorError(502, "The Vexcel 3D mesh request could not connect.") from None
        if len(data) > MAX_TILE_BYTES:
            raise SponsorError(502, "Vexcel returned an oversized 3D resource.")
        if kind == "tileset":
            try:
                document = json.loads(data)
                rewrite_tileset(document["root"], url)
                return "application/json", json.dumps(document).encode()
            except (ValueError, TypeError, KeyError):
                raise SponsorError(502, "Vexcel returned an invalid 3D tileset.") from None
        if data[:4] not in {b"glTF", b"b3dm", b"i3dm", b"pnts", b"cmpt"}:
            raise SponsorError(502, "Vexcel returned an invalid 3D tile.")
        return "application/octet-stream", data
    finally:
        REQUESTS.release()
