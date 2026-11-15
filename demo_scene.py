"""Curated, source-grounded presentation scene; separate from evaluated projects.

Sponsor outlines stay in ignored local storage. This endpoint never runs the
agent, changes a project, fetches sources or represents a design as approved.
"""
from pathlib import Path
import json

from shapely.geometry import box, mapping, shape

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "private" / "demo-hancock"
PROPERTY_ID = "4497305"
ORIGIN = (-118.3100104, 34.0641972)


def build_demo_scene(directory=DATA):
    directory = Path(directory)
    try:
        source = json.loads((directory / "context-local.geojson").read_text())
        context = json.loads((directory / "costar-design-context.json").read_text())
        origin = source["origin"]
        if (origin["lon"], origin["lat"]) != ORIGIN or origin["crs"] != "EPSG:32611":
            raise ValueError("Wrong source origin")
        if context["propertyId"] != PROPERTY_ID:
            raise ValueError("Wrong source property")
        stories = context["sourceFields"]["numStoriesAboveGrade"]
        homes = context["sourceFields"]["totalNumUnits"]
        if stories != 3 or homes != 28:
            raise ValueError("The curated story needs review against changed property evidence")
        features = source["features"]
        # Match the building containing the source property point, not a mutable
        # feature array position. Exclude overlapping alternative source outlines.
        from shapely.geometry import Point
        candidates = [f for f in features if f["properties"]["label"] == "Building footprint"
                      and shape(f["geometry"]).covers(Point(0, 0))]
        primary = min(candidates, key=lambda f: shape(f["geometry"]).area)
        primary_shape = shape(primary["geometry"])
        bounds = [-58, -67, 37, 42]
        extent = box(*bounds)
        buildings = []
        for feature in features:
            if feature["properties"]["label"] != "Building footprint":
                continue
            geom = shape(feature["geometry"])
            is_primary = feature is primary
            if not geom.is_valid or geom.is_empty or not geom.intersects(extent):
                continue
            if not is_primary and geom.intersection(primary_shape).area > 1:
                continue
            # Surroundings are clipped to the presentation board; the selected
            # property's footprint remains complete.
            if not is_primary:
                geom = geom.intersection(extent)
                if geom.geom_type not in ("Polygon", "MultiPolygon") or geom.area < 1:
                    continue
            buildings.append({"id": str(feature["id"]), "geometry": mapping(geom),
                              "primary": is_primary, "height": stories * 3.2 if is_primary else 7.2})
        cells = []
        for name, y_min, y_max in (("north", -9, 3), ("south", -40, -28)):
            geom = box(-25.4, y_min, -23, y_max)
            if any(geom.intersection(shape(b["geometry"])).area > .001 for b in buildings):
                raise ValueError("The authored garden conflicts with mapped buildings")
            cells.append({"id": name, "geometry": mapping(geom), "depthM": .15,
                          "areaM2": round(geom.area, 3)})
        area = round(sum(c["areaM2"] for c in cells), 3)
        props = primary["properties"]
        return {
            "schemaVersion": 1, "kind": "curated-demo", "units": "m", "origin": origin,
            "site": {"propertyId": PROPERTY_ID, "name": "Hancock Terrace Apartments",
                     "address": "538 S Manhattan Pl, Los Angeles", "homes": homes, "stories": stories},
            "buildings": buildings, "cells": cells, "bounds": bounds,
            "street": {"westX": -39, "eastX": -25.4, "minY": -67, "maxY": 42},
            "trees": [{"x": -18.9, "y": y, "existing": True} for y in (-43, -25, -13, 5)],
            "scenario": {"sourceAreaM2": 450, "coefficient": .9, "maxRainMm": 50,
                         "areaM2": area, "storageM3": round(area * .15, 3)},
            "sources": [{"provider": "Vexcel", "date": props.get("date"),
                         "collection": props.get("collection"), "use": "Mapped building outlines and parcel context"},
                        {"provider": "CoStar", "propertyId": PROPERTY_ID,
                         "use": "28 apartments, three stories, multifamily access and parking context"}],
            "assumptions": [
                "Curated design demonstration, separate from agent evaluations and saved proposals.",
                "Both gardens are outside the mapped parcel. Public-frontage permission, utilities, entry positions and street edges require verification.",
                "Street alignment, sidewalk, facade details, tree positions, materials and heights are illustrative. Main height assumes 3.2 m per reported story.",
                "450 m² of connected street area and runoff coefficient 0.9 are explicit what-if assumptions. The animation is not a hydraulic simulation.",
                "Gross ponding is area × 0.15 m. Direct rainfall occupies storage first; no infiltration, groundwater recharge or pollutant removal is calculated.",
                "Soil, gravel, inlet and overflow details explain a possible system; no existing drain connection is verified.",
                "The genuine exterior capture is a separate Matterport view. It is not registered to the authored design and has an independent camera.",
            ],
        }
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError("The Hancock demo source snapshot is unavailable. Prepare the local demo evidence before presenting.") from error
