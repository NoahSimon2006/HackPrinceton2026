"""Deterministic, local measurements. No geometry is passed to the model."""

import math
from decimal import Decimal
from datetime import datetime, timezone

from pyproj import Transformer
from shapely import transform, unary_union
from shapely.geometry import Point, shape
from shapely.errors import GEOSException

PROJECT = Transformer.from_crs("EPSG:4326", "EPSG:32611", always_xy=True)
METHOD = "Planar measurement in WGS 84 / UTM zone 11N (EPSG:32611); screening precision, not a survey."
MARKINGS = {"crossing": "Marked crossing", "access": "Marked keep-clear area",
            "drainage": "Marked potential runoff source", "treatment": "Marked potential treatment area"}
VEXCEL = "https://api.vexcelgroup.com/v2"


def source(provider, endpoint=None, *, date=None, collection=None):
    return {"provider": provider, "url": endpoint, "observed_at": date or None,
            "collection": collection or None,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def number(value, *, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        raise ValueError("Expected a finite, non-negative number.")
    if maximum is not None and value > maximum:
        raise ValueError("Value exceeds the site-screening limit.")
    return value


def projected(geometry, kinds=("Polygon", "MultiPolygon", "LineString")):
    if not isinstance(geometry, dict) or geometry.get("type") not in kinds:
        raise ValueError("Unsupported site geometry.")
    vertices = 0

    def check(coords):
        nonlocal vertices
        if not isinstance(coords, (list, tuple)) or not coords:
            raise ValueError("Empty or invalid coordinates.")
        if isinstance(coords[0], (int, float)):
            vertices += 1
            if len(coords) != 2 or vertices > 25_000:
                raise ValueError("Invalid coordinate dimensions or too many vertices.")
            lon, lat = coords
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in coords):
                raise ValueError("Coordinates must be finite numbers.")
            if not (-119 < lon < -117 and 33 < lat < 35):
                raise ValueError("Geometry is outside the Los Angeles measurement area.")
        else:
            for child in coords:
                check(child)
    check(geometry.get("coordinates"))
    try:
        geometry = shape(geometry)
    except (ValueError, TypeError, GEOSException) as error:
        raise ValueError("Invalid site geometry.") from error
    if geometry.is_empty or not geometry.is_valid or not geometry.is_simple:
        raise ValueError("Geometry is empty, self-intersecting, or invalid.")
    result = transform(geometry, PROJECT.transform, interleaved=False)
    if result.length <= 0 or (result.geom_type != "LineString" and result.area <= 0):
        raise ValueError("Geometry has no measurable area or length.")
    return result


def validate_inputs(markings, scenario, workflow, lon, lat):
    """Validate user geometry before any provider/model call; reject, never repair."""
    if not isinstance(markings, list) or len(markings) > 20:
        raise ValueError("Use at most 20 map markings.")
    point = Point(*PROJECT.transform(lon, lat))
    allowed = {"crossing", "access"} if workflow == "street" else {"drainage", "treatment", "access"}
    clean = []
    for marking in markings:
        if not isinstance(marking, dict) or marking.get("kind") not in allowed:
            raise ValueError("A marking does not belong to this workflow.")
        geometry = marking.get("geometry")
        expected = ("LineString",) if marking["kind"] == "crossing" else ("Polygon",)
        measured = projected(geometry, expected)
        if not point.buffer(1000).covers(measured):
            raise ValueError("Keep map markings within 1 km of the selected site.")
        clean.append({"kind": marking["kind"], "geometry": geometry})
    clean_scenario = None
    if scenario is not None:
        if workflow != "water" or not isinstance(scenario, dict):
            raise ValueError("Rainfall scenarios are only available in Stormwater.")
        depth = number(scenario.get("inches"), maximum=100)
        label = scenario.get("source")
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 160:
            raise ValueError("Give the rainfall scenario a source or assumption (up to 160 characters).")
        clean_scenario = {"inches": depth, "source": label.strip()}
    return clean, clean_scenario


def fact(identifier, label, value, unit, origin, *, basis="measured", method=METHOD, note="", feature_ids=(), precision=2):
    numeric = isinstance(value, (float, int))
    value = round(value, precision) if numeric and precision is not None else value
    # Explicit design inputs must retain their entered value: rounding a small
    # positive depth/coefficient to zero contradicts the calculation it drives.
    display = ((f"{value:,.{precision}f}" if precision is not None else format(Decimal(str(value)), "f"))
               + (f" {unit}" if unit else "")) if numeric else str(value)
    if unit in ("units", "spaces", "docks") and value == int(value):
        display = f"{int(value):,} {unit}"
    # Conversions are computed here, not guessed by the language model.
    if unit == "m²":
        display += f" / {value / .09290304:,.0f} sq ft"
    elif unit == "m" and precision is not None:
        display += f" / {value / .3048:,.1f} ft"
    return {"id": identifier, "label": label, "value": value, "unit": unit,
            "display": display, "basis": basis, "source": origin,
            "method": method, "note": note, "feature_ids": list(feature_ids)}


def measure_outlines(features, lon, lat, *, nearby=False):
    facts, warnings, valid = [], [], []
    point = Point(*PROJECT.transform(lon, lat))
    for index, feature in enumerate(features):
        props = feature["properties"]
        props["evidenceId"] = f"outline-{index + 1}"
        try:
            geometry = projected(feature["geometry"], ("Polygon", "MultiPolygon"))
            if not point.buffer(5000).covers(geometry):
                raise ValueError("Outside site scope")
            valid.append((feature, geometry))
        except ValueError:
            warnings.append(f"{props['evidenceId']}: invalid or out-of-scope outline; not measured.")
    features[:] = [feature for feature, _ in valid]
    if nearby and valid:
        origin = source("Vexcel parcel extraction", f"{VEXCEL}/property/extract")
        for label, identifier in (("Parcel boundary", "nearby-parcels"), ("Building footprint", "nearby-buildings")):
            ids = [f["properties"]["evidenceId"] for f, _ in valid if f["properties"]["label"] == label]
            if ids:
                facts.append(fact(identifier, f"Returned nearby {label.lower()} outlines", len(ids), "outlines",
                                  origin, note="Provider coverage is not a parcel survey or proof of ownership.", feature_ids=ids))
    parcels = [(f, g) for f, g in valid if f["properties"]["label"] == "Parcel boundary" and g.covers(point)]
    if not parcels:
        return facts, warnings + (["No valid parcel polygon containing the selected point. Parcel-relative areas unavailable."] if not nearby else [])
    selected, parcel = parcels[0]
    props = selected["properties"]
    origin = source("Vexcel parcel extraction", f"{VEXCEL}/property/extract", date=props.get("date"), collection=props.get("collection"))
    parcel_id = props["evidenceId"]
    facts.append(fact("parcel-area", "Selected parcel area", parcel.area, "m²", origin, feature_ids=[parcel_id]))
    clipped, ids = [], []
    for f, g in valid:
        if f["properties"]["label"] != "Building footprint":
            continue
        part = parcel.intersection(g)
        if part.area > 0:
            clipped.append(part)
            ids.append(f["properties"]["evidenceId"])
        elif not nearby:
            warnings.append(f"{f['properties']['evidenceId']}: footprint is outside the selected parcel; excluded from totals.")
    if clipped:
        area = unary_union(clipped).area
        note = "Union of returned footprints clipped to this parcel; overlaps counted once. Footprints are not gross floor area, and drainage is unverified."
        facts.extend([
            fact("footprint-area", "Mapped building footprint area within parcel", area, "m²", origin, note=note, feature_ids=ids),
            fact("footprint-coverage", "Mapped footprint coverage of parcel", area / parcel.area * 100, "%", origin, note=note, feature_ids=[parcel_id, *ids]),
            fact("parcel-outside-footprints", "Parcel area outside mapped footprints", parcel.area - area, "m²", origin,
                 note="This is not verified permeable, available, or buildable land. Unmapped structures may exist.", feature_ids=[parcel_id, *ids]),
        ])
    else:
        warnings.append("No valid building footprints inside the parcel. Missing footprints do not mean no buildings.")
    return facts, warnings


def measure_candidates(features, lon, lat):
    facts, warnings, valid = [], [], []
    point = Point(*PROJECT.transform(lon, lat))
    for index, feature in enumerate(features, 1):
        props = feature["properties"]
        identifier = props["evidenceId"] = f"candidate-{index}"
        try:
            geometry = projected(feature["geometry"], ("Polygon", "MultiPolygon"))
            if not point.buffer(200).covers(geometry):
                raise ValueError("Outside detector scope")
        except ValueError:
            warnings.append(f"{identifier}: invalid or distant detection box; not measured.")
            continue
        valid.append(feature)
        origin = source("Vexcel detection", f"{VEXCEL}/elements/detect", date=props.get("date"), collection=props.get("collection"))
        # A detection box is not a traced surface or crosswalk. Do not publish its
        # area or width as a pavement area, crossing length, or usable space.
        note = "Distance to the nearest edge of a detection box, not the object's center or a confirmed object. May belong to a neighboring property."
        score = props.get("score")
        if isinstance(score, (float, int)) and math.isfinite(score):
            note += f" Detector score {score:.2f}; not a calibrated probability."
        facts.append(fact(identifier, f"{props['label']} candidate distance from selected point", point.distance(geometry), "m", origin,
                          basis="candidate", note=note, feature_ids=[identifier]))
    features[:] = valid
    return facts, warnings


def measure_markings(markings, scenario):
    facts = []
    origin = source("Planner map marking")
    for index, marking in enumerate(markings, 1):
        geometry = projected(marking["geometry"])
        line = marking["kind"] == "crossing"
        facts.append(fact(f"marking-{index}", MARKINGS[marking["kind"]], geometry.length if line else geometry.area,
                          "m" if line else "m²", origin, basis="user_marked",
                          note="Measured from the planner's drawing; location and function are user-supplied, not field verified.",
                          feature_ids=[f"marking-{index}"]))
    if scenario:
        facts.append(fact("scenario-rainfall", "Planner rainfall scenario", scenario["inches"], "in", source("Planner scenario"),
                          basis="assumption", method="User-entered rainfall depth; no runoff calculation.",
                          note=f"Planner-supplied source or assumption: {scenario['source']}"))
    return facts


def property_facts(details, frontages, nearby=None):
    facts, warnings = [], []
    origin = source("CoStar local property kit")
    fields = {"propertyType": ("Property type", ""), "units": ("Reported apartment units", "units"),
              "reportedParkingSpaces": ("Reported parking spaces", "spaces"),
              "reportedLoadingDocks": ("Reported loading docks", "docks"),
              "buildingAreaSqFt": ("Reported gross building floor area", "sq ft")}
    for field, (label, unit) in fields.items():
        value = (details or {}).get(field)
        if value is None:
            continue
        if field != "propertyType":
            try:
                number(value)
            except ValueError:
                warnings.append(f"CoStar {label.lower()} is invalid; omitted.")
                continue
        facts.append(fact(f"costar-{field}", label, value, unit, origin, basis="reported",
                          method="Reported field from the selected CoStar property; observation date unavailable.",
                          note="Gross floor area may span multiple floors; do not substitute it for a roof footprint." if field == "buildingAreaSqFt" else "Reported snapshot; not a current field count."))
    if nearby:
        for use in sorted({item["type"] for item in nearby}):
            count = sum(item["type"] == use for item in nearby)
            facts.append(fact(f"costar-nearby-use-{len(facts) + 1}", f"Nearby CoStar records by property type: {use}", count,
                              "records", origin, basis="reported", method="Geocoded property records within 200 m of the selected intersection.",
                              note="Location and property use are a screening inventory. Coverage does not establish land ownership or parcel boundaries."))
    if not details:
        warnings.append("No selected CoStar property record. Nearby records and frontage do not establish site ownership or access.")
    valid_frontages = []
    for index, frontage in enumerate(frontages, 1):
        identifier = frontage["evidenceId"] = f"frontage-{index}"
        try:
            geometry = projected(frontage["geometry"], ("LineString",))
        except ValueError:
            warnings.append(f"{identifier}: invalid frontage line; not measured.")
            continue
        valid_frontages.append(frontage)
        facts.append(fact(identifier, "Selected-property frontage" if frontage.get("selectedProperty") else "Nearby-property frontage",
                          geometry.length, "m", origin, note="Source frontage line length; not road width or crossing distance. Ownership of nearby frontage is not inferred.", feature_ids=[identifier]))
    frontages[:] = valid_frontages
    return facts, warnings


def hydrology_facts(data):
    from hydrology import RAINFALL, WATERSHEDS
    facts = []
    estimate = data.get("estimate")
    if estimate:
        number(estimate["inches"], maximum=100)
        bounds = estimate["depth_range"]
        facts.append(fact("county-rainfall", "County 85th-percentile, 24-hour rainfall", estimate["inches"], "in",
                          source("LA County rainfall contours", RAINFALL), basis="estimated",
                          method="On contour" if estimate["method"] == "on_contour" else "Distance interpolation between adjacent contours bracketing the point",
                          note=f"Contour range {bounds[0]}–{bounds[1]} in. Not a forecast or flood-design storm."))
    names = sorted({f["properties"].get("WATERSHED", "").strip() for f in data.get("watershed", {}).get("features", [])} - {""})
    if names:
        label = " / ".join("Los Angeles River" if name.lower() == "lariver" else name.title() for name in names)
        facts.append(fact("county-watershed", "County watershed containing the selected point", label, "",
                          source("LA County watershed subbasins", WATERSHEDS), basis="reported",
                          method="Point intersection with county subbasin polygons.",
                          note="Membership does not establish parcel drainage, flow direction, flood exposure, or treatment feasibility."))
    return facts
