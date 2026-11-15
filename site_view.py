"""Resolve selected-property tours from local CSV and attachment associations.

No external request is made. A linked tour does not verify playback, exterior
coverage, camera position, acquisition date or proposal registration.
"""
from __future__ import annotations

import csv
from datetime import datetime
from functools import lru_cache
import json
import math
from pathlib import Path
import re

UNAVAILABLE = "The existing-site view is unavailable because its local source association could not be confirmed."


class SiteViewUnavailable(ValueError):
    """Safe public error; source paths and records must not enter API failures."""


def _normalized(value):
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def _property(items, property_id):
    matches = [item for item in items if isinstance(item, dict) and item.get("id") == property_id]
    if len(matches) != 1:
        raise SiteViewUnavailable(UNAVAILABLE)
    result = {key: matches[0][key] for key in ("id", "lat", "lon", "name", "address", "type")}
    for key in ("id", "name", "address", "type"):
        value = result[key]
        if not isinstance(value, str) or not value.strip() or len(value) > 240 or any(ord(char) < 32 for char in value):
            raise SiteViewUnavailable(UNAVAILABLE)
    for key, lower, upper in (("lon", -118.67, -118.10), ("lat", 33.70, 34.35)):
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
            raise SiteViewUnavailable(UNAVAILABLE)
    return result


@lru_cache(maxsize=4)
def _associations(directory, signature):
    root = Path(directory)
    with (root / "commercial-properties.csv").open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not {"PropertyId", "MatterportModelId", "Address", "City", "State"} <= set(reader.fieldnames or []):
            raise SiteViewUnavailable(UNAVAILABLE)
        rows = list(reader)
    records, owners = {}, {}
    for row in rows:
        owners.setdefault(row.get("MatterportModelId"), set()).add(row.get("PropertyId"))
    with (root / "data/commercial-property.jsonl").open(encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            identifier = str(record["id"])
            if identifier in records:
                raise SiteViewUnavailable(UNAVAILABLE)
            attachments = record.get("attachments") or []
            records[identifier] = {"address": record.get("primaryAddress") or {}, "attachments": attachments}
            for item in attachments:
                if isinstance(item, dict) and item.get("videoExternalReferenceType") in (36, 234):
                    owners.setdefault(item.get("videoKey"), set()).add(identifier)
    return rows, records, owners


def site_view_descriptor(directory, catalog_items, property_id):
    """Require a unique property/model association and construct only trusted URLs."""
    try:
        if not isinstance(directory, (str, Path)) or not str(directory).strip():
            raise SiteViewUnavailable(UNAVAILABLE)
        root = Path(directory).expanduser()
        prop = _property(catalog_items, property_id)
        files = (root / "commercial-properties.csv", root / "data/commercial-property.jsonl")
        signature = tuple((p.stat().st_mtime_ns, p.stat().st_size) for p in files)
        rows, records, owners = _associations(str(root), signature)
        record = records[property_id]
        address = record["address"]
        raw_address = " ".join(str(address.get(key) or "") for key in
                               ("streetNumber", "streetDirection", "streetName", "streetType"))
        if (_normalized(raw_address) != _normalized(prop["address"])
                or not math.isclose(float(address["latitude"]), prop["lat"], rel_tol=0, abs_tol=1e-8)
                or not math.isclose(float(address["longitude"]), prop["lon"], rel_tol=0, abs_tol=1e-8)):
            raise SiteViewUnavailable(UNAVAILABLE)
        attachments = record["attachments"]
        if not isinstance(attachments, list):
            raise SiteViewUnavailable(UNAVAILABLE)
        scans, ambiguous, excluded = {}, False, set()
        for row in rows:
            model = row.get("MatterportModelId", "")
            if row.get("PropertyId") != property_id or not re.fullmatch(r"[A-Za-z0-9]{11}", model):
                continue
            if (_normalized(row.get("Address")) != _normalized(prop["address"])
                    or _normalized(row.get("City")) != "los angeles" or _normalized(row.get("State")) != "ca"):
                continue
            matching = [item for item in attachments if isinstance(item, dict) and item.get("videoKey") == model]
            if len(matching) != 1:
                continue
            item = matching[0]
            title = item.get("caption")
            if (item.get("videoExternalReferenceType") not in (36, 234) or not isinstance(title, str)
                    or not title.strip() or len(title) > 500 or any(ord(c) < 32 for c in title)):
                continue
            date = item.get("originationDate")
            if date is not None:
                try:
                    datetime.fromisoformat(date)
                except (TypeError, ValueError):
                    continue
            exterior_hint = bool(re.search(r"\b(?:exterior|courtyard|loading|outdoors?|roof(?:top)?)\b", title, re.I))
            if not exterior_hint:
                excluded.add(model)
                continue
            if owners.get(model) != {property_id}:
                ambiguous = True
                continue
            scans[model] = {"modelId": model, "title": title, "url": f"https://my.matterport.com/show/?m={model}",
                            "attachmentDate": date, "exteriorHint": exterior_hint}
        choices = sorted(scans.values(), key=lambda scan: (not scan["exteriorHint"], scan["title"], scan["modelId"]))
        result = {"property": prop, "status": "linked" if choices else "ambiguous" if ambiguous else "unavailable",
                  "scans": choices, "scan": choices[0] if choices else None,
                  "excludedInteriorOrUnspecified": len(excluded),
                  "source": {"provider": "CoStar local property kit",
                             "association": "Matching property address, CSV model join and attachment metadata; cross-property model matches are excluded."},
                  "limitations": [
                      "The selected property's listing metadata links this tour and its title suggests exterior or site context. Actual coverage and a suitable viewpoint require visual inspection.",
                      "Tour titles and attachment dates are listing metadata, not a verified scan date or current site survey.",
                      "No supported 2D proposal is registered to this scan. The proposed-design view is unavailable.",
                  ]}
        if not choices:
            result["message"] = ("Tour links are ambiguous across properties; no scan was opened." if ambiguous else
                                 "No relevant exterior tour is linked to this property. Interior-only and unspecified tours are excluded; continue with the map and site evidence.")
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, csv.Error):
        raise SiteViewUnavailable(UNAVAILABLE) from None
