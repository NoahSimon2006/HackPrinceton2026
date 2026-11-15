"""Keep live-feed inspection out of the durable project archive.

TomTom snapshots and model text derived from them stay in the active run.
Canonical planner inputs, local sponsor facts and independent simulation
artifacts can persist; continuation refreshes live evidence.
"""
import json

NOTICE = "The live traffic review is not archived. Continue to refresh current conditions; saved inputs and local design evaluations are retained."


def without_live_facts(facts):
    return [item for item in facts if "tomtom" not in json.dumps(item.get("source", {})).lower()]


def archive_artifact(path, content):
    if path == '/project/designs/road-concept.json':
        # Only the compiler's validated structured design is durable. Plans,
        # source reports and free-form prose may contain live traffic values.
        from road_concept import validate_road_concept
        return json.dumps(validate_road_concept(json.loads(content)), allow_nan=False)
    if path in ("/project/brief.json", "/project/source-brief.json", "/project/constraints.json", "/project/history/previous-traffic-evaluation.json", "/project/evaluations/traffic.json", "/project/comparison.json"):
        return content
    if path.startswith("/project/evidence/") or path == "/project/evidence.json":
        return json.dumps(without_live_facts(json.loads(content)))
    if path in ("/project/review.json", "/project/history/previous-review.json"):
        return json.dumps({"status":"refresh_live_evidence", "message":NOTICE})
    # Plans, notes and specialist prose may incorporate live traffic numbers.
    return None


def archive_result(result):
    if result is None:
        return None
    return {**result, "report":None, "facts":without_live_facts(result.get("facts", [])),
            "sourceWarnings":[], "resumeNotice":NOTICE}


def archive_event(event):
    if "facts" not in event:
        return event
    facts=without_live_facts(event["facts"])
    return {**event,"facts":facts,"fact_ids":[item["id"] for item in facts]}
