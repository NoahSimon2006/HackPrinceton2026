"""Read locally built, source-backed discovery snapshots. Never use fixtures."""
import json
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "private" / "discovery"
NETWORK = ROOT / "sim" / "dtla.net.xml"


def load_discovery(workflow):
    if workflow not in ("street", "water"):
        raise ValueError("Choose traffic or stormwater discovery.")
    path = DATA / f"{workflow}.json"
    if not path.exists():
        raise FileNotFoundError("Discovery data has not been built. Run scripts/build_discovery.py; no substitute data is displayed.")
    data = json.loads(path.read_text())
    if (not isinstance(data, dict) or data.get("schema") != 1 or data.get("workflow") != workflow
            or not isinstance(data.get("layers"), list) or not isinstance(data.get("sources"), dict)):
        raise ValueError("Discovery snapshot is invalid. Rebuild the source data.")
    # A cached feature may have changed without its reference/version changing.
    # Validate the builder's content hash before exposing it as sourced evidence.
    payload = {key:value for key,value in data.items() if key != "version"}
    expected = sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()[:16]
    if data.get("version") != expected:
        raise ValueError("Discovery snapshot content changed. Rebuild the source data.")
    return data


def map_discovery(workflow):
    """Attach an independently versioned, short-lived current traffic layer."""
    data = load_discovery(workflow)
    if workflow == 'street':
        from traffic_flow import get_snapshot
        live = get_snapshot()
        data['layers'] = live['layers']
        data['sources'] = dict(live['sources'])
        data['sources'].update(live['sources'])
        data['flow_expires_at'] = live.get('expires_at')
        data['flow_expires_epoch'] = live.get('expires_epoch')
        data['flow_audit'] = live['audit']
    return data


def _resolve(workflow, reference, lon=None, lat=None):
    if reference is None:
        return None
    if (not isinstance(reference, dict) or set(reference) != {"version", "layer", "feature"}
            or any(not isinstance(value, str) or not value for value in reference.values())):
        raise ValueError("Invalid discovery reference.")
    if workflow == 'street' and reference['layer'] in ('flow','approaches'):
        from traffic_flow import resolve_snapshot
        data = resolve_snapshot(reference['version'])
    else:
        data = load_discovery(workflow)
    if reference["version"] != data["version"]:
        raise ValueError("Discovery data changed. Select the feature again.")
    layer = next((x for x in data["layers"] if x["id"] == reference["layer"]), None)
    feature = next((f for f in (layer or {}).get("features", []) if f["id"] == reference["feature"]), None)
    if not feature or layer.get("status") not in ("ready", "partial"):
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
            "source":{**data["sources"][layer["source"]], "observed_at":p.get("period") if layer['id'] in ('counts','turning') else data["sources"][layer["source"]].get("observed_at")}, "method":layer["method"],
            "limitations":layer["limitations"], "detail":p.get("scalar_detail",{})}


def query_area(workflow, bounds, limit=12, *, data=None):
    """Bounded local spatial query; returns the same records the map displays."""
    import math
    from shapely.geometry import shape, box
    if (workflow not in ('street','water') or not isinstance(bounds,(list,tuple)) or len(bounds)!=4
            or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in bounds)
            or not -180<=bounds[0]<bounds[2]<=180 or not -90<=bounds[1]<bounds[3]<=90
            or bounds[2]-bounds[0]>.1 or bounds[3]-bounds[1]>.1
            or isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=50):
        raise ValueError('Choose a bounded discovery area and a limit from 1 to 50.')
    data = data if data is not None else map_discovery(workflow)
    boundary=box(*bounds); pilot=box(*data['bbox'])
    results=[]
    for layer in data['layers']:
        matching=[f for f in layer['features'] if shape(f['geometry']).intersects(boundary)] if layer['status'] in ('ready','partial') else []
        results.append({'layer':layer['id'],'status':layer['status'],'unit':layer['unit'],
                        'method':layer['method'],'limitations':layer['limitations'],'period':layer['period'],
                        'version':layer.get('version',data['version']),'source':data['sources'][layer['source']],
                        'total':len(matching),'truncated':len(matching)>limit,'features':matching[:limit],
                        'error':layer.get('error')})
    return {'workflow':workflow,'coverage':'outside_pilot' if not pilot.intersects(boundary) else
            'inside_pilot' if pilot.covers(boundary) else 'partial_pilot','layers':results}


def area_facts(workflow, lon, lat, *, data=None):
    """Curated site-neighborhood tool output. No names, coordinates or raw records."""
    import math
    from site_measurements import fact
    dy=350/111320; dx=dy/math.cos(math.radians(lat))
    result=query_area(workflow,[lon-dx,lat-dy,lon+dx,lat+dy],3,data=data)
    facts=[]
    for layer in result['layers']:
        origin=layer['source']
        source={'provider':origin['label'],'url':origin['url'],'observed_at':origin.get('observed_at'),
                'retrieved_at':origin.get('retrieved_at'),'collection':origin.get('product')}
        note=f"{layer['period']}. {layer['limitations']}"
        facts.append(fact('area-'+layer['layer']+'-coverage','Neighborhood '+layer['layer']+' coverage',
                          layer['status']+'; '+result['coverage']+'; '+str(layer['total'])+' intersecting features',
                          '',source,basis='availability',method='Local intersection within a bounded 350 m neighborhood.',note=note))
        for index,feature in enumerate(layer['features']):
            p=feature['properties']; prefix='area-'+layer['layer']+'-'+str(index+1)
            facts.append(fact(prefix,'Nearby '+layer['layer']+' signal',p['value'],layer['unit'],source,
                              basis='estimated' if layer['layer'] in ('flow','approaches','terrain','rainfall') else 'reported',method=layer['method'],note=note))
            d=p.get('scalar_detail',{})
            if layer['layer'] in ('flow','approaches'):
                for name,label,unit in [('speed_kmh','Estimated speed','km/h'),('free_flow_kmh','Derived free-flow reference','km/h'),('length_m','Displayed length','m'),('time_penalty_s','Screened excess travel time','seconds')]:
                    if d.get(name) is not None:
                        facts.append(fact(prefix+'-'+name,label,d[name],unit,source,basis='estimated',method=d['baseline'],note=note))
    return facts, []


def traffic_context(reference, lon, lat):
    """Resolve a verified turning sheet for local simulation, never model context.

    Match the discovery version, site, original PDF bytes and a fresh parse. The
    browser supplies no file path, demand counts, network node or source claim.
    """
    resolved = _resolve("street", reference, lon, lat)
    if resolved is None or resolved[1]["id"] != "turning":
        return None
    data, _, feature = resolved
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
    from traffic_counts import load_sheet
    expected_network = data.get("sources", {}).get("osm", {}).get("input_sha256")
    if (not isinstance(expected_network, str) or not NETWORK.is_file()
            or sha256(NETWORK.read_bytes()).hexdigest() != expected_network):
        raise ValueError("Road network changed or is unavailable. Rebuild discovery before comparing traffic.")
    if sha256(pdf.read_bytes()).hexdigest() != p.get("sheet_sha256"):
        raise ValueError("Count source changed. Rebuild discovery and select the site again.")
    parsed = load_sheet(filename, DATA / "sheets")
    if parsed != sheet or parsed["url"] != p.get("sheet_url") or parsed["date"] != p.get("period"):
        raise ValueError("Count sheet does not match discovery. Rebuild source data.")
    return {"sheet": parsed, "period": "pm", "node_id": p["network_node"],
            "lon": p["center"][0], "lat": p["center"][1]}


def traffic_context_at_site(lon, lat):
    """Internal simulation input association, independent of retired map layers.

    Require exactly one verified counted intersection within 25 metres. Never
    substitute a distant intersection or move the selected property. Source
    hashes, sheet parsing and network checks remain in traffic_context.
    """
    from math import hypot, cos, radians
    try:
        data = load_discovery("street")
    except (OSError, ValueError):
        return None
    layer = next((layer for layer in data["layers"] if layer["id"] == "turning"), None)
    matches = []
    for feature in (layer or {}).get("features", []):
        x, y = feature["properties"]["center"]
        distance = hypot((lon-x)*cos(radians(lat)), lat-y)*111320
        if distance <= 25:
            matches.append((feature, distance))
    if len(matches) != 1:
        return None
    feature, distance = matches[0]
    reference = {"version":data["version"], "layer":"turning", "feature":feature["id"]}
    result = traffic_context(reference, *feature["properties"]["center"])
    result["association_distance_m"] = round(distance, 2)
    return result
