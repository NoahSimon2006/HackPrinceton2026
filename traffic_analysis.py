"""Local bridge from a selected LADOT sheet to bounded, cited traffic comparisons.

The agent sees scalar facts only. Count-sheet street names, source filenames, node
identifiers, coordinates and design/evidence geometry remain in the local adapter.
"""
from __future__ import annotations

from hashlib import sha256
from contextlib import contextmanager
import json
import logging
import math
from threading import RLock

from agent_activity import RunCancelled
from site_measurements import fact, source
from street_design import Layout, evaluate
from traffic_counts import peak_hour
from traffic_sim import Study

LADOT = "https://navigatela.lacity.org/dot/traffic_data/"
SUMO = "https://sumo.dlr.de/docs/"
OSM = "https://www.openstreetmap.org/copyright"
APPROACHES = ("nb", "sb", "eb", "wb")
MOVEMENTS = ("left", "through", "right")
SIMULATION_LOCK = RLock()


@contextmanager
def simulation_lock(activity):
    """Cached run folders have one writer; queued requests remain cancellable."""
    while not SIMULATION_LOCK.acquire(timeout=.2):
        activity.check()
    try:
        activity.check()
        yield
    finally:
        SIMULATION_LOCK.release()


def status_fact(message):
    return fact("traffic-comparison-status", "Traffic comparison availability", message, "",
                source("Local traffic comparison"), basis="availability",
                method="Input and execution checks in this analysis request.",
                note="Unavailable performance is not zero emissions, delay or traffic.")


def validate_layouts(layouts):
    """Require distinct network changes, not renamed copies or different paint labels."""
    values = [item if isinstance(item, Layout) else Layout.model_validate(item) for item in layouts]
    if not 2 <= len(values) <= 3 or len({item.name for item in values}) != len(values):
        raise ValueError("Evaluate two or three uniquely named alternatives together.")
    if any(item.name == "baseline" for item in values):
        raise ValueError("The baseline name is reserved for the existing network.")
    if any(item.new_use == "bus_lane" for item in values):
        raise ValueError("Bus-only operation is not modeled by this lane-reallocation template.")
    for index, first in enumerate(values):
        for second in values[index + 1:]:
            if (first.approach == second.approach and first.lanes_removed == second.lanes_removed
                    and abs(first.length_m - second.length_m) < 20):
                raise ValueError("Alternatives must change different approaches, lane counts, or lengths by at least 20 m. Changing the label or new use alone does not change simulated traffic.")
    return values


class TrafficAnalysis:
    """One request, one source sheet, and at most one bounded comparison."""

    def __init__(self, context, identity, activity, *, allow_generated_timing=False, policy=None):
        self.context = context
        self.identity = identity or {}
        self.activity = activity
        self.allowed = allow_generated_timing is True
        self.policy = policy
        self.study = None
        self.facts = []
        self.warnings = []
        self.ready = False
        self.evaluated = False
        self.comparison = None
        self.proposal = None
        self._prepared = False

    def _unavailable(self, message):
        item = status_fact(message)
        self.facts = [f for f in self.facts if f["id"] != item["id"]] + [item]
        return item

    def _identify(self, comparison):
        from proposal import comparison_fingerprint
        if self.identity:
            comparison.update(self.identity, workflow="street")
            comparison["input_hash"] = comparison_fingerprint(comparison, **self.identity)
        return comparison

    def unavailable_comparison(self, reason):
        sheet = (self.context or {}).get("sheet") or {}
        return self._identify({"status": "unavailable", "results": {}, "layouts": {}, "descriptions": {},
            "checks": {}, "geometry": {}, "ranking": {"recommended": None, "verdicts": {}, "reason": reason},
            "count_date": sheet.get("date"), "sheet_url": sheet.get("url"), "peak_hour": None,
            "period": (self.context or {}).get("period"), "assumptions": []})

    def prepare(self):
        if self._prepared:
            return self.facts, self.warnings
        self._prepared = True
        self.activity.check()
        if not self.context:
            self._unavailable("No verified manual turning-count sheet is linked to this selected site. Traffic performance remains unavailable; no assumed traffic demand is substituted.")
            return self.facts, self.warnings
        try:
            sheet = self.context["sheet"]
            period = self.context.get("period", "pm")
            if sheet.get("kind") != "manual" or period not in ("am", "pm"):
                raise ValueError("A verified manual sheet and a counted AM or PM period are required.")
            hour = peak_hour(sheet, period)
            counts = {f"{approach}-{move}": sheet["approaches"][approach][hour][move]
                      for approach in APPROACHES for move in MOVEMENTS}
            if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts.values()):
                raise ValueError("Turning counts must be reported nonnegative integers.")
            digest = sha256(json.dumps(sheet, sort_keys=True).encode()).hexdigest()
            origin = source("LADOT manual turning count", LADOT, date=sheet["date"], collection=f"verified-sheet-{digest[:12]}")
            note = f"Historical observation on {sheet['date']}, {hour} {period.upper()}; not current demand or a forecast. Printed row and column totals were checked when the sheet was parsed."
            self.facts = [fact("traffic-count-total", "Selected counted peak-hour vehicle movements", sum(counts.values()),
                               "vehicles / counted hour", origin, basis="reported",
                               method="Sum of the reported left, through and right movements in the busiest counted hour of the selected period.", note=note)]
            self.facts.extend(fact(f"traffic-count-{name}", f"{name.replace('-', ' ').upper()} counted movement", value,
                                   "vehicles / counted hour", origin, basis="reported",
                                   method="Reported movement from the selected verified manual count sheet.", note=note)
                              for name, value in counts.items())
            if not self.allowed:
                self._unavailable("Measured signal timing is not connected. A comparison using generated signal timing has not been authorized, so emissions, delay and design benefits remain unavailable.")
                return self.facts, self.warnings
            self.activity.event("domain-analysis", "traffic-network", "started", "Matching counted approaches to the local street network.")
            with simulation_lock(self.activity):
                self.study = Study(self.context["node_id"], self.context["lon"], self.context["lat"], sheet, period,
                                   activity=self.activity)
            self.activity.check()
            for approach, mapping in self.study.mapping.items():
                if approach not in APPROACHES:
                    continue
                lane_count = min(edge.getLaneNumber() for edge in mapping["chain"])
                chain_length = sum(edge.getLength() for edge in mapping["chain"])
                osm = source("OpenStreetMap imported road network", OSM)
                self.facts.append(fact(f"traffic-lanes-{approach}", f"{approach.upper()} minimum mapped approach lanes", lane_count,
                    "lanes", osm, basis="reported", method="Minimum lane count along the connected approach chain in the imported network.",
                    note="Mapped lane attributes are not a field survey. Leave at least one general-traffic lane on every affected segment."))
                self.facts.append(fact(f"traffic-length-{approach}", f"{approach.upper()} mapped approach length", chain_length,
                    "m", osm, method="Sum of approach-chain edge lengths in the imported local network.",
                    note="A candidate design dimension is an authored proposal, not an existing site measurement; it must fit inside this mapped approach."))
            self.ready = True
            self._unavailable("Verified historical turning counts and mapped approach geometry are ready for one bounded comparison. Generated signal timing and other simulation assumptions must be labeled; no design impacts have been calculated yet.")
            self.activity.event("domain-analysis", "traffic-network", "completed", "Counted movements and mapped approach dimensions are ready.")
        except RunCancelled:
            raise
        except Exception as error:
            logging.getLogger(__name__).warning("Traffic preparation failed (%s)", type(error).__name__)
            self._unavailable("The selected turning sheet or mapped street network could not support this comparison. Retrieved historical counts are preserved; no performance values are inferred.")
            self.warnings.append("Traffic comparison unavailable: verified inputs or approach matching could not be completed.")
            self.activity.event("domain-analysis", "traffic-network", "failed", "Traffic comparison inputs are incomplete; retrieved counts are preserved.")
        return self.facts, self.warnings

    def run(self, layouts, *, outlines=None, frontages=None, keep_clear=None, detections=None, crossings=None):
        self.activity.check()
        if self.evaluated:
            return {"status": "already_evaluated", "facts": self.facts,
                    "message": "This run already used its one comparison. Use the existing facts; another evaluation requires a new analysis request."}
        self.prepare()
        if not self.ready:
            self.comparison = self.unavailable_comparison(self.facts[-1]["value"])
            return {"status": "unavailable", "facts": self.facts}
        try:
            layouts = validate_layouts(layouts)
        except (ValueError, TypeError):
            return {"status": "invalid_layouts", "message": "Provide two or three distinct valid lane reallocations using existing mapped approaches. Leave a traffic lane; use distinct approaches, lane counts, or lengths separated by at least 20 m. Bus-only operation is unsupported."}
        self.evaluated = True
        input_facts = list(self.facts)
        self.activity.event("lead", "traffic-comparison", "started", "Testing baseline and bounded alternatives with the same counted demand.")
        try:
            with simulation_lock(self.activity):
                comparison = evaluate(self.study, layouts, outlines=outlines, frontages=frontages, keep_clear=keep_clear,
                                      activity=self.activity, policy=self.policy,
                                      extra_checks=lambda geometry: crossing_checks(geometry, detections, crossings))
            self.activity.check()
            comparison["status"] = "completed"
            if comparison.get("input_hash"):
                comparison["simulation_input_hash"] = comparison["input_hash"]
            comparison["source_input_hash"] = sha256(json.dumps({"context": self.context, "outlines": outlines,
                "frontages": frontages, "keep_clear": keep_clear, "detections": detections, "crossings": crossings},
                sort_keys=True).encode()).hexdigest()
            self._identify(comparison)
            self.comparison = comparison
            self.facts.extend(comparison_facts(comparison))
            recommended = comparison["ranking"].get("recommended")
            if recommended and not comparison["ranking"]["verdicts"].get(recommended, {}).get("eligible"):
                raise ValueError("A recommended alternative must be eligible.")
            if recommended and comparison["ranking"]["verdicts"].get(recommended, {}).get("eligible"):
                from proposal import from_traffic_comparison
                self.proposal = from_traffic_comparison(comparison, recommended, **self.identity).model_dump()
            # The root attaches request identity to the local response, never the model.
            self._unavailable("Comparison completed. " + ("The recommended eligible alternative is published as a proposal." if self.proposal else
                "No proposal was published. " + (comparison["ranking"].get("reason") or "No eligible recommended alternative was returned.")))
            self.activity.event("lead", "traffic-comparison", "completed", "Comparison complete; eligibility and tradeoffs are available.", facts=self.facts)
            return {"status": "completed", "facts": self.facts}
        except RunCancelled:
            raise
        except Exception as error:
            logging.getLogger(__name__).warning("Traffic comparison failed (%s)", type(error).__name__)
            self.facts = input_facts
            self.proposal = None
            item = self._unavailable("The bounded comparison could not finish or publish a validated proposal. Retrieved source facts are preserved; no missing performance values are inferred.")
            self.comparison = self.unavailable_comparison(item["value"])
            self.activity.event("lead", "traffic-comparison", "failed", "Comparison unavailable; retrieved source facts are preserved.", facts=[item])
            return {"status": "unavailable", "facts": self.facts}


def crossing_checks(design, detections, crossings):
    """Candidate boxes flag uncertainty; they never become confirmed crosswalks/driveways."""
    from site_measurements import projected
    result = {"candidate_crosswalk_overlaps": 0, "candidate_driveway_overlaps": 0,
              "candidate_evidence": [], "marked_crossing_conflict": False}
    for feature in detections or []:
        label = str(feature.get("properties", {}).get("label", "")).lower()
        kind = "crosswalk" if "crosswalk" in label else "driveway" if "driveway" in label else None
        if not kind:
            continue
        try:
            geometry = projected(feature["geometry"], ("Polygon", "MultiPolygon"))
        except (ValueError, KeyError):
            continue
        if design.intersects(geometry):
            result[f"candidate_{kind}_overlaps"] += 1
            identifier = feature.get("properties", {}).get("evidenceId")
            if identifier:
                result["candidate_evidence"].append(identifier)
    for geometry in crossings or []:
        try:
            if design.intersects(projected(geometry, ("LineString",))):
                result["marked_crossing_conflict"] = True
        except ValueError:
            continue
    return result


def comparison_facts(comparison):
    """Explicit whitelist: full local comparison never enters model messages/files."""
    origin = source("Local SUMO comparison with historical LADOT demand", SUMO, date=comparison.get("count_date"))
    method = "Calculated by paired local SUMO runs for the same offered historical counted-trip cohort through clearance, using generated signal timing. Model output, not a measurement or current forecast."
    caveat = "Model output; assumptions are listed in traffic-model-assumptions."
    metrics = (
        ("co2", "Tailpipe CO₂", "co2_kg_per_hour", "kg / demand-hour", 1),
        ("nox", "Tailpipe NOₓ", "nox_g_per_hour", "g / demand-hour", 1),
        ("delay", "Mean modeled delay", "mean_delay_s", "s / offered vehicle", 1),
        ("completion", "Completed counted demand", "completion_share", "%", 100),
        ("completed", "Completed counted cohort", "completed_per_hour", "vehicles / demand-hour", 1),
        ("entry-failures", "Unable to enter", "unable_to_enter_share", "%", 100),
        ("co2-per-vehicle", "CO₂ per completed vehicle", "co2_g_per_completed_vehicle", "g / completed vehicle", 1),
    )
    facts = [fact("traffic-model-assumptions", "Traffic comparison assumptions", " ".join(comparison.get("assumptions", [])), "",
                  origin, basis="assumption", method="Explicit simulation assumptions shared by baseline and alternatives.",
                  note="Historical demand is preserved; model outputs do not establish present-day traffic or construction feasibility.")]
    for name, values in comparison["results"].items():
        for suffix, label, key, unit, multiplier in metrics:
            value = values.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                facts.append(fact(f"traffic-{name}-{suffix}", f"{name}: {label}", value * multiplier, unit,
                                  origin, basis="modeled", method=method, note=caveat))
        for key, suffix, unit in (("max_queue_m", "maximum-queue", "m"), ("max_noise_db", "maximum-noise", "dB(A)")):
            numbers = [v for v in values.get(key, {}).values() if isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)]
            if numbers:
                facts.append(fact(f"traffic-{name}-{suffix}", f"{name}: {suffix.replace('-', ' ')}", max(numbers), unit,
                    origin, basis="modeled", method=method, note="Queue is a simultaneous fixed-chain total maximized over time/seeds. Noise is the spatial maximum of hourly mean edge source levels across seeds, not a temporal peak or building exposure. " + caveat))
    for name, params in comparison.get("layouts", {}).items():
        facts.append(fact(f"traffic-{name}-design", f"{name}: tested design", comparison["descriptions"][name], "",
            origin, basis="proposed", method="Bounded authored layout mapped onto the local network; dimensions are design choices, not observations.",
            note="The full footprint stays local; no construction feasibility is established."))
        check = comparison["checks"][name]
        for key, label, unit in (("footprint_m2", "Proposed footprint", "m²"), ("parcel_overlap_m2", "Mapped parcel overlap", "m²"),
                                 ("building_overlap_m2", "Mapped building overlap", "m²"), ("access_conflicts", "Reported access conflicts", "frontages")):
            if check.get(key) is not None:
                facts.append(fact(f"traffic-{name}-{key}", f"{name}: {label}", check[key], unit,
                    source("Local footprint and sponsor-evidence comparison"), basis="measured",
                    method="Deterministic local overlay of the authored footprint and available mapped outlines or reported frontages.",
                    note="Missing sponsor coverage remains unassessed. These checks do not establish ownership or construction feasibility.",
                    feature_ids=check.get("access_evidence" if key == "access_conflicts" else "parcel_evidence", [])))
        verdict = comparison["ranking"]["verdicts"][name]
        for kind in ("crosswalk", "driveway"):
            key = f"candidate_{kind}_overlaps"
            if key in check:
                facts.append(fact(f"traffic-{name}-{key}", f"{name}: overlapping {kind} candidate boxes", check[key], "candidates",
                    source("Vexcel detection"), basis="candidate", method="Local intersection test between proposed footprint and returned detector boxes.",
                    note="Boxes are unconfirmed candidates, not traced objects. An overlap requires verification before this design can be recommended; zero returned overlaps does not establish absence.",
                    feature_ids=check.get("candidate_evidence", [])))
        if check.get("marked_crossing_conflict"):
            facts.append(fact(f"traffic-{name}-marked-crossing", f"{name}: marked crossing conflict", "The footprint intersects a planner-marked crossing.", "",
                source("Planner map marking"), basis="user_marked", method="Local intersection test with the exact current crossing marking.",
                note="Preserve the crossing or revise the design; the marking is not field verified."))
        explanation = ("Eligible for ranking." if verdict["eligible"] else "Ineligible: " + "; ".join(verdict.get("ineligible_reasons", [])))
        if comparison["ranking"].get("recommended") == name:
            explanation += " Recommended by the fixed comparison policy."
        else:
            explanation += " Not recommended."
        facts.append(fact(f"traffic-{name}-verdict", f"{name}: comparison verdict", explanation, "", origin,
            basis="calculated", method="Fixed eligibility checks followed by the agreed CO₂-first ranking.",
            note="Policy rejects layouts without total CO₂ improvement, with too few completed vehicles, worse entry failures, excessive delay/queue/noise, or blocked building/keep-clear checks. " + "; ".join(verdict.get("tradeoffs", []))))
    ranking = comparison["ranking"]
    facts.append(fact("traffic-ranking", "Comparison decision", ranking.get("recommended") or ranking.get("reason") or "No layout recommended.", "",
                      origin, basis="calculated", method="Recommend only an eligible alternative selected by the fixed comparison policy.",
                      note="A negative result is valid: never force a winner or recommend a rejected alternative."))
    return facts
