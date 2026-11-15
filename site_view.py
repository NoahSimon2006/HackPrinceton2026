"""Resolve the fixed existing-site viewer from local CoStar association metadata.

This module makes no external request. A linked attachment is not a verification
of Matterport availability, exterior coverage, camera position or registration.
"""
from __future__ import annotations

import csv
from datetime import datetime
import json
import math
from pathlib import Path
import re

PROPERTY_ID = "6067080"
MODEL_ID = "35LT5s1GSfA"
ADDRESS = "510 E Olympic Blvd"
TITLE = "3D Tour of the Building Exterior & Loading Docks"
UNAVAILABLE = "The existing-site view is unavailable because its local source association could not be confirmed."


class SiteViewUnavailable(ValueError):
    """Safe public error; source paths and records must not enter API failures."""


def _normalized(value):
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def _property(items):
    matches = [item for item in items if isinstance(item, dict) and item.get("id") == PROPERTY_ID]
    if len(matches) != 1:
        raise SiteViewUnavailable(UNAVAILABLE)
    record = matches[0]
    result = {key: record[key] for key in ("id", "lat", "lon", "name", "address", "type")}
    for key in ("name", "address", "type"):
        value = result[key]
        if not isinstance(value, str) or not value.strip() or len(value) > 240 or any(ord(char) < 32 for char in value):
            raise SiteViewUnavailable(UNAVAILABLE)
    for key, lower, upper in (("lon", -118.67, -118.10), ("lat", 33.70, 34.35)):
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
            raise SiteViewUnavailable(UNAVAILABLE)
    if _normalized(result["address"]) != _normalized(ADDRESS):
        raise SiteViewUnavailable(UNAVAILABLE)
    return result


def site_view_descriptor(directory, catalog_items):
    """Require agreement between the local CSV join, property record and catalog.

    Only the chosen demo is supported. No request parameter or source URL can
    replace its model or destination; the viewer URL is constructed here.
    """
    try:
        if not isinstance(directory, (str, Path)) or not str(directory).strip():
            raise SiteViewUnavailable(UNAVAILABLE)
        root = Path(directory).expanduser()
        prop = _property(catalog_items)
        if not re.fullmatch(r"[A-Za-z0-9]{11}", MODEL_ID):
            raise SiteViewUnavailable(UNAVAILABLE)
        with (root / "commercial-properties.csv").open(encoding="utf-8-sig", newline="") as file:
            rows = csv.DictReader(file)
            if not {"PropertyId", "MatterportModelId", "Address", "City", "State"} <= set(rows.fieldnames or []):
                raise SiteViewUnavailable(UNAVAILABLE)
            matches = [row for row in rows if row.get("MatterportModelId") == MODEL_ID]
        if len(matches) != 1:
            raise SiteViewUnavailable(UNAVAILABLE)
        joined = matches[0]
        if (joined.get("PropertyId") != PROPERTY_ID or _normalized(joined.get("Address")) != _normalized(ADDRESS)
                or _normalized(joined.get("City")) != "los angeles" or _normalized(joined.get("State")) != "ca"):
            raise SiteViewUnavailable(UNAVAILABLE)
        records = []
        with (root / "data/commercial-property.jsonl").open(encoding="utf-8") as file:
            for line in file:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise SiteViewUnavailable(UNAVAILABLE)
                if str(record.get("id")) == PROPERTY_ID:
                    records.append(record)
        if len(records) != 1:
            raise SiteViewUnavailable(UNAVAILABLE)
        record = records[0]
        address = record.get("primaryAddress") or {}
        raw_address = " ".join(str(address.get(key) or "") for key in
                               ("streetNumber", "streetDirection", "streetName", "streetType"))
        if (_normalized(raw_address) != _normalized(prop["address"])
                or not math.isclose(float(address["latitude"]), prop["lat"], abs_tol=1e-8)
                or not math.isclose(float(address["longitude"]), prop["lon"], abs_tol=1e-8)):
            raise SiteViewUnavailable(UNAVAILABLE)
        attachments = record.get("attachments")
        if not isinstance(attachments, list):
            raise SiteViewUnavailable(UNAVAILABLE)
        matching = [item for item in attachments if isinstance(item, dict) and item.get("videoKey") == MODEL_ID]
        if len(matching) != 1:
            raise SiteViewUnavailable(UNAVAILABLE)
        attachment = matching[0]
        if attachment.get("caption") != TITLE or attachment.get("videoExternalReferenceType") not in (36, 234):
            raise SiteViewUnavailable(UNAVAILABLE)
        date = attachment.get("originationDate")
        if date is not None:
            if not isinstance(date, str):
                raise SiteViewUnavailable(UNAVAILABLE)
            datetime.fromisoformat(date)
        return {
            "property": prop,
            "scan": {"modelId": MODEL_ID, "title": TITLE, "url": f"https://my.matterport.com/show/?m={MODEL_ID}"},
            "source": {"provider": "CoStar local property kit",
                       "association": "Property-to-model CSV join and matching exterior/loading-docks attachment metadata",
                       "files": ["commercial-properties.csv", "data/commercial-property.jsonl"],
                       "attachmentDate": date},
            "status": "linked",
            "limitations": [
                "Local listing metadata links this tour to the selected property; actual exterior coverage and a suitable viewpoint still require visual inspection.",
                "The attachment date is listing metadata, not a verified scan acquisition date or a current site survey.",
                "No supported 2D proposal is registered to this scan. The proposed-design view is unavailable.",
            ],
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, csv.Error):
        raise SiteViewUnavailable(UNAVAILABLE) from None
