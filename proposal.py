"""Local proposal contract, the synthetic CP1 rendering fixture, and real traffic proposals.

The fixture never recommends anything. Real proposals (from_traffic_comparison) are
built only from a simulated comparison in street_design.evaluate: every metric comes
from that run, and unassessed checks stay null.
Geometry is generated and measured in UTM 11N; only display geometry is WGS84.
"""
from hashlib import sha256
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pyproj import Transformer
from shapely.geometry import Polygon, mapping
from shapely import transform


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Design(StrictModel):
    kind: Literal["test_island", "test_bioretention", "lane_reallocation"]
    length_m: float = Field(gt=0, le=200)
    width_m: float = Field(gt=0, le=10)
    approach: Literal["nb", "sb", "eb", "wb"] | None = None
    lanes_removed: int | None = Field(default=None, ge=1, le=2)
    new_use: Literal["curb_extension", "bike_lane", "bus_lane", "pedestrian_space"] | None = None

    @model_validator(mode="after")
    def kind_fields(self):
        street = (self.approach, self.lanes_removed, self.new_use)
        if self.kind == "lane_reallocation":
            if None in street:
                raise ValueError("Lane reallocation needs approach, lanes_removed and new_use.")
        else:
            if any(v is not None for v in street):
                raise ValueError("Only lane reallocation takes approach, lanes_removed and new_use.")
            if self.length_m > 30:
                raise ValueError("Test fixtures are at most 30 m long.")
        return self


class EvidenceReference(StrictModel):
    id: str
    source: str
    classification: Literal["observed", "reported", "user_provided", "modeled", "fixture"]


class Metric(StrictModel):
    id: str
    unit: str
    baseline: float | None
    proposed: float | None
    status: Literal["calculated", "unassessed"]
    revision: int = Field(ge=1)
    input_hash: str
    method: str

    @model_validator(mode="after")
    def missing_is_not_zero(self):
        if self.status == "unassessed" and (self.baseline is not None or self.proposed is not None):
            raise ValueError("Unassessed metrics must have null values.")
        return self


class GeometryFeature(StrictModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: dict
    properties: dict


class Finding(StrictModel):
    status: Literal["unassessed", "checked"]
    text: str
    evidence_ids: list[str]


class Proposal(StrictModel):
    schema_version: Literal[1] = 1
    site_id: str
    workflow: Literal["street", "water"]
    revision: int = Field(ge=1, le=100)
    input_revision: int = Field(ge=0)
    input_hash: str
    development_fixture: bool
    evidence: list[EvidenceReference]
    design: Design
    projected_crs: Literal["EPSG:32611"] = "EPSG:32611"
    display_crs: Literal["EPSG:4326"] = "EPSG:4326"
    geometry: list[GeometryFeature]
    existing_geometry_ids: list[str]
    proposed_geometry_ids: list[str]
    metrics: list[Metric]
    assumptions: list[str]
    access: Finding
    overlap: Finding
    recommendation: str

    @model_validator(mode="after")
    def same_revision(self):
        ids = [g.id for g in self.geometry]
        if len(set(ids)) != len(ids) or not self.proposed_geometry_ids:
            raise ValueError("Proposal geometry IDs must be unique and nonempty.")
        if not set(self.existing_geometry_ids + self.proposed_geometry_ids) <= set(ids):
            raise ValueError("Missing referenced geometry.")
        for geometry in self.geometry:
            if geometry.properties.get("revision") != self.revision:
                raise ValueError("Geometry revision mismatch.")
            from site_measurements import projected
            projected(geometry.geometry, kinds=("Polygon", "MultiPolygon", "LineString"))
        if any(m.revision != self.revision or m.input_hash != self.input_hash for m in self.metrics):
            raise ValueError("Metric revision or input mismatch.")
        evidence_ids = {e.id for e in self.evidence}
        if not set(self.access.evidence_ids + self.overlap.evidence_ids) <= evidence_ids:
            raise ValueError("Unknown evidence reference.")
        return self


def fixture(lon: float, lat: float, workflow: str, site_id: str, revision: int = 1, input_revision: int = 0) -> Proposal:
    # Restrict this development endpoint to the app's LA study region.
    if not (-118.67 <= lon <= -118.10 and 33.70 <= lat <= 34.35):
        raise ValueError("Choose a site in the LA study region.")
    if workflow not in ("street", "water") or not site_id or len(site_id) > 100:
        raise ValueError("Invalid site or workflow.")
    design = Design(kind="test_island" if workflow == "street" else "test_bioretention",
                    length_m=12 if workflow == "street" else 8, width_m=2 + (revision - 1) % 3)
    identity = dict(lon=lon, lat=lat, workflow=workflow, site_id=site_id, revision=revision,
                    input_revision=input_revision, design=design.model_dump())
    fingerprint = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    forward = Transformer.from_crs(4326, 32611, always_xy=True)
    inverse = Transformer.from_crs(32611, 4326, always_xy=True)
    x, y = forward.transform(lon, lat)
    # Deliberately centered test rectangle, not an inferred treatment location.
    w, h = design.width_m / 2, design.length_m / 2
    polygon = Polygon([(x-w,y-h),(x+w,y-h),(x+w,y+h),(x-w,y+h),(x-w,y-h)])
    metric_args = dict(revision=revision, input_hash=fingerprint)
    return Proposal(site_id=site_id, workflow=workflow, revision=revision, input_revision=input_revision,
        input_hash=fingerprint, development_fixture=True,
        evidence=[EvidenceReference(id="ui-fixture", source="Synthetic UI test; no site suitability evidence", classification="fixture")],
        design=design, geometry=[GeometryFeature(id="test-footprint", geometry=mapping(transform(polygon, inverse.transform, interleaved=False)), properties={"revision":revision,"role":"proposed","fixture":True})],
        existing_geometry_ids=[], proposed_geometry_ids=["test-footprint"],
        metrics=[Metric(id="footprint_area",unit="m²",baseline=None,proposed=round(polygon.area,2),status="calculated",method="Synthetic footprint area in UTM 11N; not a real site measurement",**metric_args),
                 Metric(id="co2" if workflow == "street" else "captured_volume",unit="kg/h" if workflow == "street" else "m³",baseline=None,proposed=None,status="unassessed",method="No validated design or verified comparison inputs",**metric_args)],
        assumptions=["Synthetic rectangle centered on selected site solely to test rendering.","No existing geometry, feasible placement, access, drainage, traffic performance or ownership is established."],
        access=Finding(status="unassessed",text="Entrances and operations have not been checked.",evidence_ids=[]),
        overlap=Finding(status="unassessed",text="Parcel and structure overlaps have not been checked.",evidence_ids=[]),
        recommendation="UI test only. This is not a planning recommendation.")


METRICS = [  # (id, unit, result key, method)
    ("co2_per_vehicle", "g CO₂ / completed vehicle", "co2_g_per_completed_vehicle",
     "SUMO emissions over the measured hour, scaled to CARB 2026 LA fleet rate, divided by vehicles that completed their trip."),
    ("co2_per_hour", "kg CO₂ / hour", "co2_kg_per_hour", "SUMO emissions over the measured hour, scaled to CARB 2026 LA fleet rate."),
    ("mean_delay", "s / vehicle", "mean_delay_s", "Mean time loss plus waiting-to-enter time, trips departing in the measured hour."),
    ("completion", "share of counted demand", "completion_share", "Vehicles completing trips in the measured hour ÷ counted demand."),
    ("unable_to_enter", "share of vehicles", "unable_to_enter_share", "Vehicles never inserted ÷ vehicles generated, whole run."),
]


def _maximum(values: dict):
    numbers = [v for v in values.values() if v is not None]
    return max(numbers) if numbers else None


def from_traffic_comparison(comparison: dict, layout_name: str, *, site_id: str, revision: int,
                            input_revision: int, source_ids: dict | None = None) -> Proposal:
    """Publish one simulated layout as a validated proposal. Raises if the layout was not run."""
    results = comparison["results"]
    if layout_name not in results or layout_name not in comparison["layouts"]:
        raise ValueError("Only a simulated layout can be published.")
    params = comparison["layouts"][layout_name]
    base, proposed = results["baseline"], results[layout_name]
    checks = comparison["checks"][layout_name]
    verdict = comparison["ranking"]["verdicts"][layout_name]
    identity = dict(site_id=site_id, revision=revision, input_revision=input_revision, layout=params,
                    sheet=comparison["sheet_url"], period=comparison["period"], seeds=base["seeds"],
                    keep_clear=checks.get("keep_clear_conflict"))
    fingerprint = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    common = dict(revision=revision, input_hash=fingerprint)
    metrics = [Metric(id=i, unit=u, baseline=base[k], proposed=proposed[k], status="calculated", method=m, **common)
               for i, u, k, m in METRICS if base.get(k) is not None and proposed.get(k) is not None]
    metrics.append(Metric(id="max_queue", unit="m", baseline=_maximum(base["max_queue_m"]), proposed=_maximum(proposed["max_queue_m"]),
                          status="calculated", method="Longest queue on any counted approach lane, max over seeds.", **common))
    noise_before, noise_after = _maximum(base["max_noise_db"]), _maximum(proposed["max_noise_db"])
    metrics.append(Metric(id="roadway_noise", unit="dB(A)", baseline=noise_before, proposed=noise_after,
                          status="calculated" if None not in (noise_before, noise_after) else "unassessed",
                          method="SUMO Harmonoise source level on approach edges; not building exposure.", **common)
                   if None not in (noise_before, noise_after) else
                   Metric(id="roadway_noise", unit="dB(A)", baseline=None, proposed=None, status="unassessed",
                          method="Noise output unavailable.", **common))
    metrics.append(Metric(id="footprint_area", unit="m²", baseline=None, proposed=checks["footprint_m2"], status="calculated",
                          method="Area of reallocated lane footprint from the simulated network's lane shapes, UTM 11N.", **common))
    ids = source_ids or {}
    evidence = [EvidenceReference(id="ladot-sheet", source=comparison["sheet_url"], classification="reported"),
                EvidenceReference(id="simulation", source="SUMO 1.28, counted demand, generated actuated signal timing", classification="modeled")]
    if checks["parcel_overlap_m2"] is not None:
        evidence.append(EvidenceReference(id=ids.get("outlines", "vexcel-outlines"), source="Vexcel parcel and building outlines", classification="observed"))
    if checks["access_conflicts"] is not None:
        evidence.append(EvidenceReference(id=ids.get("property", "costar-frontage"), source="CoStar frontage and curb cuts", classification="reported"))
    overlap = (Finding(status="unassessed", text="Vexcel parcel and building outlines were not available for this run.", evidence_ids=[])
               if checks["parcel_overlap_m2"] is None else
               Finding(status="checked", text=f"Footprint overlaps mapped parcels by {checks['parcel_overlap_m2']} m² and buildings by {checks['building_overlap_m2']} m².",
                       evidence_ids=[evidence[2].id]))
    access = (Finding(status="unassessed", text="CoStar frontage and curb-cut data were not available for this run.", evidence_ids=[])
              if checks["access_conflicts"] is None else
              Finding(status="checked", text=f"{checks['access_conflicts']} CoStar frontage(s) with reported curb cuts within 3 m of the footprint.",
                      evidence_ids=[evidence[-1].id]))
    feature = comparison["geometry"][layout_name]
    geometry = [GeometryFeature(id=f"{layout_name}-footprint", geometry=feature["geometry"],
                                properties={"revision": revision, "role": "proposed", "layout": layout_name,
                                            "new_use": params["new_use"]})]
    recommended = comparison["ranking"]["recommended"] == layout_name
    text = comparison["descriptions"][layout_name] + (
        " Recommended: best eligible layout on the CO₂-first ranking." if recommended else
        f" Not recommended: {comparison['ranking']['reason'] or 'another layout ranks higher.'}" if verdict["eligible"] else
        " Not recommended: " + "; ".join(verdict["ineligible_reasons"]) + ".")
    return Proposal(site_id=site_id, workflow="street", revision=revision, input_revision=input_revision, input_hash=fingerprint,
                    development_fixture=False, evidence=evidence,
                    design=Design(kind="lane_reallocation", length_m=params["length_m"], width_m=3.2 * params["lanes_removed"],
                                  approach=params["approach"], lanes_removed=params["lanes_removed"], new_use=params["new_use"]),
                    geometry=geometry, existing_geometry_ids=[], proposed_geometry_ids=[geometry[0].id], metrics=metrics,
                    assumptions=list(comparison["assumptions"]), access=access, overlap=overlap, recommendation=text)
