"""Revision-bound proposals for traffic, stormwater and development fixtures.

Traffic metrics come from local simulations. Stormwater metrics come from local
screening calculations. Unassessed values stay null.
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
    kind: Literal["test_island", "test_bioretention", "lane_reallocation", "rain_garden", "bioretention"]
    length_m: float | None = Field(default=None, gt=0, le=200)
    width_m: float | None = Field(default=None, gt=0, le=10)
    storage_depth_m: float | None = Field(default=None, gt=0, le=1)
    approach: Literal["nb", "sb", "eb", "wb"] | None = None
    lanes_removed: int | None = Field(default=None, ge=1, le=2)
    new_use: Literal["curb_extension", "bike_lane", "bus_lane", "pedestrian_space"] | None = None

    @model_validator(mode="after")
    def kind_fields(self):
        street = (self.approach, self.lanes_removed, self.new_use)
        if self.kind == "bioretention":
            if self.storage_depth_m is None or any(v is not None for v in (*street, self.length_m, self.width_m)):
                raise ValueError("Bioretention uses its drawn polygon and explicit storage depth, not rectangle dimensions.")
            return self
        if self.length_m is None or self.width_m is None:
            raise ValueError("This design needs length and width.")
        if (self.storage_depth_m is not None) != (self.kind == "rain_garden"):
            raise ValueError("Only stormwater designs use storage depth.")
        if self.kind == "lane_reallocation":
            if None in street:
                raise ValueError("Lane reallocation needs approach, lanes_removed and new_use.")
        else:
            if any(v is not None for v in street):
                raise ValueError("Only lane reallocation takes approach, lanes_removed and new_use.")
            if self.kind.startswith("test_") and self.length_m > 30:
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
        if self.status == "calculated" and self.proposed is None:
            raise ValueError("A calculated metric needs a proposed value.")
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
    status: Literal["fixture", "draft", "conditional", "recommended", "tested", "rejected"]
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
        workflow, statuses = {
            "test_island": ("street", {"fixture"}),
            "test_bioretention": ("water", {"fixture"}),
            "lane_reallocation": ("street", {"recommended", "tested", "rejected"}),
            "rain_garden": ("water", {"draft"}),
            "bioretention": ("water", {"conditional"}),
        }[self.design.kind]
        if self.workflow != workflow or self.status not in statuses or self.development_fixture != (self.status == "fixture"):
            raise ValueError("Design kind, workflow and proposal status must agree.")
        ids = [g.id for g in self.geometry]
        if len(set(ids)) != len(ids) or not self.proposed_geometry_ids:
            raise ValueError("Proposal geometry IDs must be unique and nonempty.")
        if not set(self.existing_geometry_ids + self.proposed_geometry_ids) <= set(ids):
            raise ValueError("Missing referenced geometry.")
        if set(self.existing_geometry_ids) & set(self.proposed_geometry_ids):
            raise ValueError("Existing and proposed geometry must be distinct.")
        for geometry in self.geometry:
            if geometry.properties.get("revision") != self.revision:
                raise ValueError("Geometry revision mismatch.")
            from site_measurements import projected
            projected(geometry.geometry, kinds=("Polygon", "MultiPolygon", "LineString"))
        if any(m.revision != self.revision or m.input_hash != self.input_hash for m in self.metrics):
            raise ValueError("Metric revision or input mismatch.")
        evidence_ids = {e.id for e in self.evidence}
        if len(evidence_ids) != len(self.evidence) or len({m.id for m in self.metrics}) != len(self.metrics):
            raise ValueError("Evidence and metric IDs must be unique.")
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
        input_hash=fingerprint, development_fixture=True, status="fixture",
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
     "Emissions of the offered peak-hour cohort through 15-minute clearance divided by completed trips from that cohort; includes unfinished emissions, not an individual-trip average."),
    ("co2_per_hour", "kg CO₂ / demand hour", "co2_kg_per_hour", "Emissions of one hour of offered demand, including unfinished trips through 15-minute clearance. Not an instantaneous rate. Uses the calibration stated in the comparison."),
    ("nox_per_hour", "g NOₓ / demand hour", "nox_g_per_hour", "NOₓ from the same offered cohort and clearance window as CO₂; calibration is stated in the comparison."),
    ("mean_delay", "s / offered vehicle", "mean_delay_s", "Time loss plus entry waiting for every offered peak-hour trip, including unentered waiting and unfinished-trip lower bounds through clearance."),
    ("completion", "share of offered demand", "completion_share", "Measured-hour scheduled trips completed by the end of 15-minute clearance ÷ offered trips."),
    ("unable_to_enter", "share of offered demand", "unable_to_enter_share", "Measured-hour scheduled trips still unable to enter at clearance end ÷ offered trips."),
]


def comparison_fingerprint(comparison: dict, *, site_id: str, revision: int, input_revision: int):
    """Bind the local publication to all geometry, sources, inputs and results.

    Identity metadata is excluded from the comparison payload so the same hash
    can be attached before or after the proposal without changing its meaning.
    """
    metadata = {"site_id", "workflow", "revision", "input_revision", "input_hash"}
    payload = {k: v for k, v in comparison.items() if k not in metadata}
    identity = dict(site_id=site_id, revision=revision, input_revision=input_revision, comparison=payload)
    return sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _maximum(values: dict):
    # A maximum over a partial set is only a lower bound, not the reported
    # maximum across all modeled approaches.
    return max(values.values()) if values and all(v is not None for v in values.values()) else None


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
    fingerprint = comparison_fingerprint(comparison, site_id=site_id, revision=revision, input_revision=input_revision)
    common = dict(revision=revision, input_hash=fingerprint)
    metrics = []
    for i, u, k, m in METRICS:
        complete = base.get(k) is not None and proposed.get(k) is not None
        metrics.append(Metric(id=i, unit=u, baseline=base[k] if complete else None,
                              proposed=proposed[k] if complete else None,
                              status="calculated" if complete else "unassessed", method=m, **common))
    queue_before, queue_after = _maximum(base["max_queue_m"]), _maximum(proposed["max_queue_m"])
    queues = None not in (queue_before, queue_after)
    metrics.append(Metric(id="max_queue", unit="m", baseline=queue_before if queues else None, proposed=queue_after if queues else None,
                          status="calculated" if queues else "unassessed", method="Maximum over time and paired seeds of the simultaneous sum of longest-lane queues along a fixed approach chain; queues beyond the study boundary are not measured.", **common))
    noise_before, noise_after = _maximum(base["max_noise_db"]), _maximum(proposed["max_noise_db"])
    metrics.append(Metric(id="roadway_noise", unit="dB(A)", baseline=noise_before, proposed=noise_after,
                          status="calculated" if None not in (noise_before, noise_after) else "unassessed",
                          method="Spatial maximum of hourly mean SUMO Harmonoise source levels on approach edges across paired seeds; not a temporal noise peak or building exposure.", **common)
                   if None not in (noise_before, noise_after) else
                   Metric(id="roadway_noise", unit="dB(A)", baseline=None, proposed=None, status="unassessed",
                          method="Noise output unavailable.", **common))
    metrics.append(Metric(id="footprint_area", unit="m²", baseline=None, proposed=checks["footprint_m2"], status="calculated",
                          method="Area of reallocated lane footprint from the simulated network's lane shapes, UTM 11N.", **common))
    ids = source_ids or {}
    evidence = [EvidenceReference(id="ladot-sheet", source=comparison["sheet_url"], classification="reported"),
                EvidenceReference(id="simulation", source="SUMO 1.28, counted demand, generated actuated signal timing", classification="modeled")]
    if checks["parcel_overlap_m2"] is not None and checks["building_overlap_m2"] is not None:
        evidence.append(EvidenceReference(id=ids.get("outlines", "vexcel-outlines"), source="Vexcel parcel and building outlines", classification="observed"))
    if checks["access_conflicts"] is not None:
        evidence.append(EvidenceReference(id=ids.get("property", "costar-frontage"), source="CoStar frontage and curb cuts", classification="reported"))
    overlap = (Finding(status="unassessed", text="Complete Vexcel parcel and building checks were not available for this run; an unavailable check is not zero overlap.", evidence_ids=[])
               if checks["parcel_overlap_m2"] is None or checks["building_overlap_m2"] is None else
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
    status = "recommended" if recommended else "tested" if verdict["eligible"] else "rejected"
    return Proposal(site_id=site_id, workflow="street", revision=revision, input_revision=input_revision, input_hash=fingerprint,
                    development_fixture=False, status=status, evidence=evidence,
                    design=Design(kind="lane_reallocation", length_m=params["length_m"], width_m=checks["footprint_m2"] / params["length_m"],
                                  approach=params["approach"], lanes_removed=params["lanes_removed"], new_use=params["new_use"]),
                    geometry=geometry, existing_geometry_ids=[], proposed_geometry_ids=[geometry[0].id], metrics=metrics,
                    assumptions=list(comparison["assumptions"]), access=access, overlap=overlap, recommendation=text)


def from_water_comparison(comparison: dict, layout_name: str, *, site_id: str, revision: int,
                          input_revision: int) -> Proposal:
    """Publish only the locally ranked conditional storage screening alternative."""
    if (comparison.get('status') != 'ready' or comparison['ranking']['recommended'] != layout_name or
            not comparison['ranking']['verdicts'].get(layout_name, {}).get('eligible')):
        raise ValueError('Only an eligible, ranked stormwater treatment can be published.')
    fingerprint = comparison_fingerprint(comparison, site_id=site_id, revision=revision, input_revision=input_revision)
    base, result = comparison['results']['baseline'], comparison['results'][layout_name]
    common = dict(revision=revision, input_hash=fingerprint)
    definitions = [('runoff_m3', 'm³'), ('captured_m3', 'm³'), ('excess_m3', 'm³'),
                   ('capacity_m3', 'm³'), ('direct_rain_m3', 'm³'), ('direct_excess_m3', 'm³'), ('footprint_m2', 'm²')]
    metrics = [Metric(id='footprint_area' if key == 'footprint_m2' else key, unit=unit, baseline=base[key], proposed=result[key], status='calculated',
                      method=comparison['method'], **common) for key, unit in definitions]
    treatment_id, drainage_id = f'{layout_name}-footprint', 'contributing-surface'
    geometry = [GeometryFeature(id=treatment_id, geometry=comparison['geometry'][layout_name]['geometry'],
                                properties={'revision': revision, 'role': 'proposed', 'layout': layout_name}),
                GeometryFeature(id=drainage_id, geometry=comparison['contributing_geometry']['geometry'],
                                properties={'revision': revision, 'role': 'contributing', 'layout': layout_name})]
    return Proposal(site_id=site_id, workflow='water', revision=revision, input_revision=input_revision,
                    input_hash=fingerprint, development_fixture=False, status="conditional",
                    design=Design(kind='bioretention', storage_depth_m=comparison['design']['storage_depth_m']),
                    evidence=[EvidenceReference(id='vexcel-outlines', source='Vexcel parcel and mapped building outlines', classification='observed'),
                              EvidenceReference(id='costar-context', source='Selected CoStar property use and reported operations', classification='reported'),
                              EvidenceReference(id='planner-water-inputs', source='Planner drawings, depth, coefficient and site confirmations', classification='user_provided'),
                              EvidenceReference(id='water-rainfall', source=comparison['rainfall']['label'], classification='user_provided' if comparison['rainfall']['basis']=='user_provided' else 'modeled')],
                    geometry=geometry, existing_geometry_ids=[drainage_id], proposed_geometry_ids=[treatment_id], metrics=metrics,
                    assumptions=comparison['assumptions'],
                    access=Finding(status='checked', text='Planner confirmed access preservation; drawn keep-clear and available CoStar frontage checks found no conflict. Missing frontage geometry remains unassessed, and physical access is not independently verified.', evidence_ids=['planner-water-inputs','costar-context']),
                    overlap=Finding(status='checked', text='Treatment lies within the mapped parcel, outside mapped buildings, the external contributing area and drawn keep-clear areas.', evidence_ids=['vexcel-outlines','planner-water-inputs']),
                    recommendation='Conditional screening preference: greatest external runoff stored, then smallest footprint. Confirm grades, soils, utilities, setbacks, drainage and overflow before detailed design. This is not construction feasibility or permanent runoff removal.')
