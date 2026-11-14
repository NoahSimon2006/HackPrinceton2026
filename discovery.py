"""Read locally built, source-backed discovery snapshots. Never use fixtures."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "private" / "discovery"


def load_discovery(workflow):
    if workflow not in ("street", "water"):
        raise ValueError("Choose traffic or stormwater discovery.")
    path = DATA / f"{workflow}.json"
    if not path.exists():
        raise FileNotFoundError("Discovery data has not been built. Run scripts/build_discovery.py; no substitute data is displayed.")
    data = json.loads(path.read_text())
    if data.get("schema") != 1 or data.get("workflow") != workflow or not isinstance(data.get("layers"), list):
        raise ValueError("Discovery snapshot is invalid. Rebuild the source data.")
    return data


def _resolve(workflow, reference, lon=None, lat=None):
    if reference is None:
        return None
    if not isinstance(reference, dict) or set(reference) != {"version", "layer", "feature"}:
        raise ValueError("Invalid discovery reference.")
    data = load_discovery(workflow)
    if reference["version"] != data["version"]:
        raise ValueError("Discovery data changed. Select the feature again.")
    layer = next((x for x in data["layers"] if x["id"] == reference["layer"]), None)
    feature = next((f for f in (layer or {}).get("features", []) if f["id"] == reference["feature"]), None)
    if not feature or layer.get("status") != "ready":
        raise ValueError("Selected discovery feature is unavailable.")
    p = feature["properties"]
    if lon is not None and lat is not None:
        from math import hypot, cos, radians
        center = p["center"]
        if hypot((lon-center[0])*cos(radians(lat)),lat-center[1])*111320 > 5:
            raise ValueError("Discovery selection does not match this site. Select the feature again.")
    return data, layer, feature


def discovery_context(workflow, reference, lon=None, lat=None):
    """Resolve IDs locally and expose only curated scalar facts to the model."""
    resolved = _resolve(workflow, reference, lon, lat)
    if resolved is None:
        return None
    data, layer, feature = resolved
    p = feature["properties"]
    return {"layer":layer["id"], "classification":layer["classification"], "value":p.get("value"),
            "unit":layer["unit"], "period":p.get("period",layer["period"]),
            "source":{**data["sources"][layer["source"]], "observed_at":p.get("period") if workflow == "street" else data["sources"][layer["source"]].get("observed_at")}, "method":layer["method"],
            "limitations":layer["limitations"], "detail":p.get("scalar_detail",{})}


def traffic_context(reference, lon, lat):
    """Resolve a verified turning sheet for local simulation, never model context.

    Match the discovery version, site, original PDF bytes and a fresh parse. The
    browser supplies no file path, demand counts, network node or source claim.
    """
    resolved = _resolve("street", reference, lon, lat)
    if resolved is None or resolved[1]["id"] != "turning":
        return None
    _, _, feature = resolved
    p = feature["properties"]
    path = DATA / "turning-sheets.json"
    if not path.exists():
        raise ValueError("Turning sheets are unavailable. Rebuild discovery data.")
    sheet = json.loads(path.read_text()).get(feature["id"])
    if not isinstance(sheet, dict):
        raise ValueError("This turning sheet is unavailable. Rebuild discovery data.")
    filename = sheet.get("filename", "")
    if not filename or Path(filename).name != filename or not filename.endswith("-MAN.pdf"):
        raise ValueError("Invalid turning-sheet reference.")
    pdf = DATA / "sheets" / filename
    if not pdf.is_file():
        raise ValueError("Original count sheet is unavailable. Rebuild discovery data.")
    from hashlib import sha256
    from traffic_counts import load_sheet
    if sha256(pdf.read_bytes()).hexdigest() != p.get("sheet_sha256"):
        raise ValueError("Count source changed. Rebuild discovery and select the site again.")
    parsed = load_sheet(filename, DATA / "sheets")
    if parsed != sheet or parsed["url"] != p.get("sheet_url") or parsed["date"] != p.get("period"):
        raise ValueError("Count sheet does not match discovery. Rebuild source data.")
    return {"sheet": parsed, "period": "pm", "node_id": p["network_node"],
            "lon": lon, "lat": lat}
