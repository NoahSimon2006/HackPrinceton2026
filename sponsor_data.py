"""Read selected CoStar fields and resolve the corresponding Matterport tour."""
import base64
import csv
import json
import math
import os
import re
from collections import Counter, defaultdict
from functools import cache, lru_cache
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from street_geometry import to_local

ROOT = Path(__file__).resolve().parent
RADIUS_M = 250
MODEL_ID = re.compile(r"[A-Za-z0-9]{11,22}")
EXTERIOR = re.compile(r"exterior|outdoor|loading|dock|storefront|parking|entrance|entry", re.I)
MATTERPORT_GRAPH = "https://api.matterport.com/api/models/graph"


class SponsorError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@cache
def commercial_properties(directory):
    types = json.loads((directory / "schemas/enums.json").read_text())["PropertyType"]
    entries = defaultdict(dict)
    with (directory / "commercial-properties.csv").open(encoding="utf-8", newline="") as rows:
        for row in csv.DictReader(rows):
            entries[int(row["PropertyId"])][row["MatterportModelId"]] = row["Address"]

    def model_captions(record, ids):
        return {item["videoKey"]: item.get("caption") for item in record.get("attachments") or []
                if item.get("videoKey") in ids and item.get("caption")}

    listing_captions = defaultdict(dict)
    with (directory / "data/commercial-listing-summary.jsonl").open(encoding="utf-8") as records:
        for line in records:
            listing = json.loads(line)
            id_ = listing.get("propertyId")
            if id_ in entries:
                listing_captions[id_].update(model_captions(listing, entries[id_]))

    properties = []
    with (directory / "data/commercial-property.jsonl").open(encoding="utf-8") as records:
        for line in records:
            record = json.loads(line)
            address = record.get("primaryAddress") or {}
            lat, lon = address.get("latitude"), address.get("longitude")
            if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                    and -90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            id_ = record["id"]
            models = entries[id_]
            captions = listing_captions[id_] | model_captions(record, models)
            scans = [{"id": key, "label": label} for key, label in captions.items()
                     if MODEL_ID.fullmatch(key) and EXTERIOR.search(label)]
            scans.sort(key=lambda scan: ("dock" not in scan["label"].lower(), scan["label"]))
            building = record.get("propertyIndustrial") or record.get("propertyFlex") or {}
            surface = [p["totalSpaces"] for p in record.get("parking") or []
                       if p.get("parkingType") == 1 and p.get("totalSpaces") is not None]
            properties.append({
                "id": id_, "lat": lat, "lon": lon,
                "address": next(iter(models.values()), ""),
                "use": types.get(str(record.get("propertyType")), "Unknown"),
                "surface_spaces": sum(surface) if surface else None,
                "loading_docks": building.get("numExternalLoadingDocks"),
                "drive_in_bays": (building.get("driveInBays") or {}).get("numDriveInBays"),
                "height_ft": record.get("buildingHeightInFeet"),
                "parcel_count": len(record.get("parcelReferences") or []),
                "scans": scans,
            })
    return properties


def nearby_properties(site):
    value = os.getenv("COSTAR_KIT_DIR", "").strip()
    if not value:
        raise SponsorError(503, "Set COSTAR_KIT_DIR to the extracted CoStar kit.")
    try:
        directory = (ROOT / Path(value).expanduser()).resolve()
        properties = commercial_properties(directory)
    except (OSError, KeyError, ValueError):
        raise SponsorError(503, "The CoStar property kit could not be read.") from None
    nearby = []
    for prop in properties:
        distance = math.hypot(*to_local(site, prop["lon"], prop["lat"]))
        if distance <= RADIUS_M:
            nearby.append(dict(prop, distance_m=round(distance)))
    counts = Counter(prop["use"] for prop in nearby)
    nearby.sort(key=lambda prop: (not prop["scans"], prop["distance_m"]))
    return {"radius_m": RADIUS_M, "total": len(nearby), "types": dict(counts.most_common()),
            "properties": nearby[:6]}


@lru_cache(maxsize=24)
def verified_scan(model_id):
    if not MODEL_ID.fullmatch(model_id):
        raise SponsorError(400, "Select a valid Matterport model.")
    key, token = (os.getenv(name, "").strip() for name in ("MATTERPORT_API_KEY", "MATTERPORT_API_TOKEN"))
    if not key or not token:
        raise SponsorError(503, "Add the Matterport API key and token to .env.")
    auth = base64.b64encode(f"{key}:{token}".encode()).decode()
    request = Request(MATTERPORT_GRAPH, data=json.dumps({
        "query": "query SiteScan($id: ID!) {model(id: $id) {id name visibility}}",
        "variables": {"id": model_id},
    }).encode(), headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            payload = json.loads(response.read(64_000))
    except (HTTPError, URLError, TimeoutError, ValueError):
        raise SponsorError(502, "Matterport could not verify this scan. Check the event credentials and model access.") from None
    model = (payload.get("data") or {}).get("model")
    if not model or model.get("visibility") != "public":
        raise SponsorError(422, "This Matterport model is unavailable for public Showcase viewing.")
    params = urlencode({"m": model_id, "play": 1, "qs": 1})
    return {"name": model.get("name"), "url": f"https://my.matterport.com/show/?{params}"}
