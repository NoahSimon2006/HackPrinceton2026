"""Local proposal contract and explicitly synthetic CP1 rendering fixture.

This module does not recommend designs, call a model, or estimate benefits.
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
    kind: Literal["test_island", "test_bioretention"]
    length_m: float = Field(gt=0, le=30)
    width_m: float = Field(gt=0, le=10)


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
