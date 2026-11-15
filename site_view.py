"""Resolve selected-property tours from local CSV and attachment associations.

No external request is made. A linked tour does not verify playback, exterior
coverage, camera position, acquisition date or proposal registration.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime
from functools import lru_cache
import json
import math
from pathlib import Path
import re

from property_address import display_text, format_property_address

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
    result["name"] = display_text(result["name"], result["address"])
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
        model, property_id = row.get("MatterportModelId"), row.get("PropertyId")
        if isinstance(model, str) and model and isinstance(property_id, str) and property_id:
            owners.setdefault(model, set()).add(property_id)
    with (root / "data/commercial-property.jsonl").open(encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            identifier = str(record["id"])
            if identifier in records:
                raise SiteViewUnavailable(UNAVAILABLE)
            attachments = record.get("attachments") or []
            malformed_attachments = not isinstance(attachments, list)
            if malformed_attachments:
                attachments = []
            records[identifier] = {"address": record.get("primaryAddress") or {}, "attachments": attachments,
                                   "malformedAttachments": malformed_attachments}
            for item in attachments:
                if (isinstance(item, dict) and item.get("videoExternalReferenceType") in (36, 234)
                        and isinstance(item.get("videoKey"), str) and item["videoKey"]):
                    owners.setdefault(item["videoKey"], set()).add(identifier)
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
        raw_address = format_property_address(address)
        if (_normalized(raw_address) != _normalized(prop["address"])
                or not math.isclose(float(address["latitude"]), prop["lat"], rel_tol=0, abs_tol=1e-8)
                or not math.isclose(float(address["longitude"]), prop["lon"], rel_tol=0, abs_tol=1e-8)):
            raise SiteViewUnavailable(UNAVAILABLE)
        attachments = record["attachments"]
        if not isinstance(attachments, list):
            raise SiteViewUnavailable(UNAVAILABLE)
        scans, exclusions = {}, Counter()
        candidates = defaultdict(list)
        for row in rows:
            if row.get("PropertyId") == property_id:
                candidates[row.get("MatterportModelId", "")].append(row)
        messages = {
            "invalid_model_id": "A listed tour has no valid Matterport model identifier.",
            "address_mismatch": "A listed tour's address does not match this property.",
            "missing_attachment": "A listed tour has no confirming property attachment.",
            "invalid_attachment_collection": "The property's attachment list could not be read.",
            "unsupported_attachment": "A listed tour has no supported Matterport attachment.",
            "ambiguous_model": "A tour model is associated with multiple properties and was excluded.",
        }
        for model, model_rows in candidates.items():
            if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9]{11}", model):
                exclusions["invalid_model_id"] += 1
                continue
            if not any(_normalized(row.get("Address")) == _normalized(prop["address"])
                       and _normalized(row.get("City")) == "los angeles"
                       and _normalized(row.get("State")) == "ca" for row in model_rows):
                exclusions["address_mismatch"] += 1
                continue
            matching = [item for item in attachments if isinstance(item, dict) and item.get("videoKey") == model]
            if not matching:
                exclusions["invalid_attachment_collection" if record.get("malformedAttachments") else "missing_attachment"] += 1
                continue
            supported = [item for item in matching if item.get("videoExternalReferenceType") in (36, 234)]
            if not supported:
                exclusions["unsupported_attachment"] += 1
                continue
            if owners.get(model) != {property_id}:
                exclusions["ambiguous_model"] += 1
                continue
            # The same verified property/model may have several listing records.
            # Optional titles and dates describe the link, not its identity.
            titles = sorted({display_text(item.get("caption"), limit=500) for item in supported} - {""})
            dates = set()
            for item in supported:
                date = item.get("originationDate")
                if isinstance(date, str):
                    try:
                        datetime.fromisoformat(date)
                        dates.add(date)
                    except ValueError:
                        pass
            dates = sorted(dates)
            title = titles[0] if titles else "3D property tour"
            title_context = " ".join(titles)
            exterior_hint = bool(re.search(r"\b(?:exterior|courtyard|loading|outdoors?|roof(?:top)?)\b", title_context, re.I))
            context = ("Exterior" if exterior_hint else
                       "Interior" if re.search(r"\b(?:interior|suite|apartment|[1-9]\s*br|bedroom)\b", title_context, re.I) else
                       "Amenity" if re.search(r"\b(?:pool|fitness|gym|lounge|theat(?:er|re)|clubhouse)\b", title_context, re.I) else "Unspecified")
            scans[model] = {"modelId": model, "title": title, "titles": titles,
                            "url": f"https://my.matterport.com/show/?m={model}",
                            "attachmentDate": dates[-1] if dates else None, "attachmentDates": dates,
                            "contextLabel": context, "exteriorHint": exterior_hint}
        choices = sorted(scans.values(), key=lambda scan: (not scan["exteriorHint"], scan["title"], scan["modelId"]))
        ambiguous = bool(exclusions["ambiguous_model"])
        result = {"property": prop, "status": "linked" if choices else "ambiguous" if ambiguous else "unavailable",
                  "scans": choices, "scan": choices[0] if choices else None, "tourCount": len(choices),
                  "excludedTourCount": sum(exclusions.values()),
                  "exclusions": [{"reason": reason, "count": count, "message": messages[reason]}
                                 for reason, count in sorted(exclusions.items()) if count],
                  "source": {"provider": "CoStar local property kit",
                             "association": "Matching property address, CSV model join and attachment metadata; cross-property model matches are excluded."},
                  "limitations": [
                      "Tours are linked to this property by listing metadata. Context labels are title hints only; actual coverage and playback require visual inspection.",
                      "Tour titles and attachment dates are listing metadata, not a verified scan date or current site survey.",
                      "No supported 2D proposal is registered to this scan. The proposed-design view is unavailable.",
                  ]}
        if choices:
            result["availabilityMessage"] = f"{len(choices)} linked property tour(s). Playback availability has not been verified."
        else:
            result["message"] = ("Tour links are ambiguous across properties; no scan was opened." if ambiguous else
                                 "No validated property tour is available. " + (" ".join(item["message"] for item in result["exclusions"]) if candidates else "No tour links are supplied for this property."))
            result["availabilityMessage"] = result["message"]
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, csv.Error):
        raise SiteViewUnavailable(UNAVAILABLE) from None
