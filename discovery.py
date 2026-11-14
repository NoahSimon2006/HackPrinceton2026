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


def discovery_context(workflow, reference, lon=None, lat=None):
    """Resolve client-selected IDs locally; return only curated scalar facts.

    The browser cannot supply an arbitrary source claim or geometry to the model.
    Names, coordinates and polygons from discovery stay in the local map.
    """
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
    # Properties exposed here were generated from checked source adapters.
    return {"layer":layer["id"], "classification":layer["classification"], "value":p.get("value"),
            "unit":layer["unit"], "period":p.get("period",layer["period"]),
            "source":{**data["sources"][layer["source"]], "observed_at":p.get("period") if workflow == "street" else data["sources"][layer["source"]].get("observed_at")}, "method":layer["method"],
            "limitations":layer["limitations"], "detail":p.get("scalar_detail",{})}
