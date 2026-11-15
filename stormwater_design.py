"""Local siting and volume screening for a draft rain garden."""

from hashlib import sha256
import json

from pyproj import Transformer
from shapely import maximum_inscribed_circle, transform, unary_union
from shapely.geometry import Point, mapping

from proposal import Design, EvidenceReference, Finding, GeometryFeature, Metric, Proposal
from site_measurements import PROJECT, fact, number, projected, source

DISPLAY = Transformer.from_crs(32611, 4326, always_xy=True)
MIN_DIAMETER_M = 1.5
MAX_DIAMETER_M = 4


def polygons(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == "Polygon":
        yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from polygons(part)


def draft_rain_garden(*, lon, lat, evidence, markings, rainfall, scenario, storage_depth_m,
                      runoff_coefficient, protect_driveway, identity):
    """Return a local draft or one concrete gap, plus facts safe to cite in a review."""
    point = Point(*PROJECT.transform(lon, lat))
    outlines = [(f["properties"], projected(f["geometry"])) for f in evidence["outlines"]]
    selected = next(((props, g) for props, g in outlines
                     if props["label"] == "Parcel boundary" and g.covers(point)), None)
    if selected is None:
        return None, "Which nearby parcel or property should host the garden?", []
    parcel_props, parcel = selected
    buildings = [(p, g) for p, g in outlines if p["label"] == "Building footprint" and g.intersects(parcel)]
    if not buildings:
        return None, "Can you select a parcel with mapped buildings so the draft can avoid structures?", []

    zones = {kind: unary_union([projected(m["geometry"]) for m in markings if m["kind"] == kind])
             for kind in ("access", "treatment", "drainage")}
    detections = [(f["properties"], projected(f["geometry"])) for f in evidence["detections"]]
    driveways = [(p, g) for p, g in detections if p["label"] == "Driveway entrance" and g.intersects(parcel)]
    if protect_driveway and zones["access"].is_empty and not driveways:
        return None, "Can you outline the driveway or loading entrance to keep clear?", []
    parking = [(p, g) for p, g in detections if p["label"] == "Parking lot" and g.intersects(parcel)]
    landscape = unary_union([g for p, g in detections if p["label"] == "Landscaped strip" and g.intersects(parcel)])
    mapped_buildings = unary_union([g for _, g in buildings])
    frontages = [(f, projected(f["geometry"])) for f in evidence["frontages"] if (f.get("curbCuts") or 0) > 0]
    frontages = [(f, g) for f, g in frontages if g.distance(parcel) <= 3]
    protected = unary_union([mapped_buildings.buffer(1), zones["access"], zones["drainage"],
                             *[g for _, g in driveways + parking], *[g.buffer(3) for _, g in frontages]])
    available = parcel.buffer(-.5).difference(protected)
    if not zones["treatment"].is_empty:
        available = available.intersection(zones["treatment"])
    else:
        # Limit unmarked concepts to the immediate area around a mapped roof or
        # a positive landscaping cue. Neither one establishes flow or land cover.
        available = available.intersection(unary_union([mapped_buildings.buffer(12), landscape]))
    candidates = []
    for area in [*polygons(available.intersection(landscape)), *polygons(available)]:
        axis = maximum_inscribed_circle(area, tolerance=.05)
        radius = min(MAX_DIAMETER_M / 2, axis.length - .05)
        if radius < MIN_DIAMETER_M / 2:
            continue
        bed = Point(axis.coords[0]).buffer(radius)
        if area.covers(bed):
            candidates.append((bed.intersection(landscape).area / bed.area, radius, -point.distance(bed), bed))
    if not candidates:
        return None, "Is there another planting area we can consider outside the mapped buildings and protected access?", []
    landscape_share, radius, _, bed = max(candidates, key=lambda item: item[:3])

    area = bed.area
    storage = area * storage_depth_m
    rainfall_data = scenario or rainfall
    rain_id = "scenario-rainfall" if scenario else "county-rainfall"
    drainage_area = zones["drainage"].area
    runoff = None
    if rainfall_data is not None and drainage_area and runoff_coefficient is not None:
        rainfall_m = number(rainfall_data["inches"], maximum=100) * .0254
        runoff = rainfall_m * drainage_area * runoff_coefficient
    geometry = mapping(transform(bed, DISPLAY.transform, interleaved=False))
    fingerprint = sha256(json.dumps(dict(identity, geometry=geometry, evidence=evidence, markings=markings,
        rainfall=rainfall_data, rain_source=rain_id, storage_depth_m=storage_depth_m,
        runoff_coefficient=runoff_coefficient, protect_driveway=protect_driveway), sort_keys=True).encode()).hexdigest()
    revision = identity["revision"]
    method = "Footprint area × proposed effective ponding depth. No infiltration, underdrain flow, or overflow routing modeled."
    screened = "Event depth × union of planner-marked runoff areas × a scenario runoff coefficient."
    metric_values = [
        ("footprint_area", "m²", area, "Area of the proposed footprint in UTM 11N."),
        ("storage_volume", "m³", storage, method),
        ("runoff_volume", "m³", runoff, screened),
        ("captured_volume", "m³", min(runoff, storage) if runoff is not None else None, "Lesser of scenario runoff and ponding storage."),
        ("overflow_volume", "m³", max(0, runoff - storage) if runoff is not None else None, "Scenario runoff beyond ponding storage. Overflow path is unverified."),
    ]
    outline_ids = [p["evidenceId"] for p in [parcel_props, *[props for props, _ in buildings]]]
    access_ids = [p["evidenceId"] for p, _ in driveways + parking + frontages]
    access_ids += [f"marking-{i}" for i, item in enumerate(markings, 1) if item["kind"] == "access"]
    refs = [
        *[EvidenceReference(id=i, source="Vexcel mapped outlines", classification="observed") for i in outline_ids],
        *[EvidenceReference(id=p["evidenceId"], source="Vexcel candidate box", classification="modeled")
          for p, g in detections if g.intersects(parcel)],
        *[EvidenceReference(id=f["evidenceId"], source="CoStar reported frontage and curb cuts", classification="reported")
          for f, _ in frontages],
        *[EvidenceReference(id=f"marking-{i}", source="Planner map marking", classification="user_provided")
          for i, _ in enumerate(markings, 1)],
    ]
    if rainfall_data is not None:
        refs.append(EvidenceReference(id=rain_id, source="Planner scenario" if scenario else "LA County rainfall contours",
                                      classification="user_provided" if scenario else "modeled"))
    assumptions = [
        "The bed is a placement concept within the mapped parcel. Verify land cover, utilities, setbacks, grade, infiltration and property permission before design.",
        f"Storage assumes an effective ponding depth of {storage_depth_m:g} m. The placement buffers are screening choices.",
    ]
    if runoff is None:
        assumptions.append("Runoff, capture and overflow require a contributing area, event depth and runoff coefficient. A mapped roof does not establish contributing area.")
    else:
        rain_label = "planner rainfall scenario" if scenario else "county 85th-percentile, 24-hour rainfall"
        assumptions.append(f"Volumes assume the marked surfaces drain to the bed, the {rain_label}, and a runoff coefficient of {runoff_coefficient:g}. Verify the drainage connection and overflow path.")
    siting = ("The draft uses space near a mapped building and inside the parcel."
              if not landscape_share else "The draft uses part of a mapped landscaped-strip candidate inside the parcel.")
    runoff_source = ("The planner-marked area is a potential contributor." if drainage_area else
                     "A nearby roof or pavement could feed the bed if downspouts and grading support the connection.")
    statement = f"{siting} {runoff_source}"
    proposal = Proposal(**identity, workflow="water", input_hash=fingerprint, development_fixture=False,
        status="draft", design=Design(kind="rain_garden", length_m=2 * radius, width_m=2 * radius),
        evidence=refs, geometry=[GeometryFeature(id="rain-garden", geometry=geometry,
            properties={"revision": revision, "role": "proposed"})], existing_geometry_ids=[],
        proposed_geometry_ids=["rain-garden"], assumptions=assumptions, recommendation=statement,
        metrics=[Metric(id=i, unit=u, baseline=None, proposed=round(v, 3) if v is not None else None,
                        status="calculated" if v is not None else "unassessed", revision=revision,
                        input_hash=fingerprint, method=m) for i, u, v, m in metric_values],
        overlap=Finding(status="checked", text="Inside the mapped parcel and clear of returned building footprints. Verify property permission and unmapped structures.", evidence_ids=outline_ids),
        access=Finding(status="checked" if access_ids else "unassessed", evidence_ids=access_ids,
            text=("Avoids mapped access and parking constraints used in this check. Verify access on site." if access_ids
                  else "Driveway and service access remain unverified.")))
    origin = source("Local stormwater screening")
    facts = [fact("water-draft", "Mapped rain garden draft", statement, "", origin, basis="modeled",
                  method="Local placement within the selected parcel, avoiding mapped constraints.", feature_ids=["rain-garden"])]
    facts += [fact(f"water-{i}", i.replace("_", " ").capitalize(), round(v, 2), u, origin,
                   basis="modeled", method=m, note="Draft scenario. Drainage and performance are unverified.")
              for i, u, v, m in metric_values if v is not None]
    return proposal, None, facts
