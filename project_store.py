"""Local project records, canonical user inputs, and resumable agent checkpoints.

Only the HTTP application writes canonical inputs. Agent files are a separate,
curated namespace; neither a model note nor a late run can promote a proposal.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from site_measurements import validate_inputs


class ProjectConflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Invalid project reference.")
    return value


def validate_snapshot(value):
    if not isinstance(value, dict):
        raise ValueError("Supply the selected site and project inputs.")
    keys = {"workflow", "siteId", "lon", "lat", "propertyId", "question", "markings",
            "rainfallScenario", "inputRevision", "proposalRevision"}
    if set(value) - keys:
        raise ValueError("Unknown project input.")
    from server import site_coordinates, analysis_identity
    lon, lat = site_coordinates({"lon": [value.get("lon")], "lat": [value.get("lat")]})
    workflow = value.get("workflow")
    question = value.get("question", "")
    if workflow not in ("street", "water") or not isinstance(question, str) or len(question) > 1500:
        raise ValueError("Choose a workflow and a brief up to 1,500 characters.")
    analysis_identity(value)
    property_id = value.get("propertyId")
    if property_id is not None and (not isinstance(property_id, str) or len(property_id) > 80):
        raise ValueError("Invalid property reference.")
    markings, scenario = validate_inputs(value.get("markings", []), value.get("rainfallScenario"), workflow, lon, lat)
    return {**value, "lon": lon, "lat": lat, "markings": markings,
            "rainfallScenario": scenario, "propertyId": property_id}


class ProjectStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "projects.sqlite3"
        self.graph_path = self.directory / "checkpoints.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects (
                  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, version INTEGER NOT NULL,
                  snapshot TEXT NOT NULL, status TEXT NOT NULL, updated TEXT NOT NULL,
                  active_run TEXT, result TEXT, result_version INTEGER);
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, version INTEGER NOT NULL,
                  status TEXT NOT NULL, started TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                  run_id TEXT, sequence INTEGER, payload TEXT, PRIMARY KEY(run_id, sequence));
                CREATE TABLE IF NOT EXISTS artifacts (
                  project_id TEXT, path TEXT, content TEXT, run_id TEXT, updated TEXT,
                  PRIMARY KEY(project_id, path));
            """)
            if "instructions" not in {row[1] for row in db.execute("PRAGMA table_info(projects)")}:
                db.execute("ALTER TABLE projects ADD COLUMN instructions TEXT NOT NULL DEFAULT '[]'")
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover_interrupted(self):
        # Called once when the local server starts, never by a browser reload.
        with self.connect() as db:
            db.execute("UPDATE runs SET status='interrupted' WHERE status='running'")
            db.execute("UPDATE projects SET status='interrupted', active_run=NULL WHERE active_run IS NOT NULL")

    def save(self, snapshot, project_id=None, expected_version=None):
        snapshot = validate_snapshot(snapshot)
        encoded = json.dumps(snapshot, sort_keys=True, allow_nan=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if project_id:
                row = db.execute("SELECT * FROM projects WHERE id=?", (identifier(project_id),)).fetchone()
                if not row:
                    raise ValueError("Project not found.")
                if expected_version != row["version"]:
                    raise ProjectConflict("This project changed in another tab. Reopen its saved version before continuing.")
                previous = json.loads(row["snapshot"])
                if any(previous.get(key) != snapshot.get(key) for key in ("workflow", "siteId", "lon", "lat")):
                    raise ValueError("Start a new project when changing its selected site or workflow.")
                if encoded == row["snapshot"]:
                    return self.get(project_id)
                if row["active_run"]:
                    db.execute("UPDATE runs SET status='superseded' WHERE id=?", (row["active_run"],))
                db.execute("UPDATE projects SET snapshot=?, version=version+1, status='ready', updated=?, active_run=NULL WHERE id=?",
                           (encoded, now(), project_id))
            else:
                project_id = uuid4().hex
                db.execute("INSERT INTO projects(id,thread_id,version,snapshot,status,updated) VALUES(?,?,1,?,'ready',?)",
                           (project_id, uuid4().hex, encoded, now()))
        return self.get(project_id)

    def get(self, project_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM projects WHERE id=?", (identifier(project_id),)).fetchone()
            if not row:
                raise ValueError("Project not found.")
            run = db.execute("SELECT id FROM runs WHERE project_id=? ORDER BY started DESC LIMIT 1", (project_id,)).fetchone()
            events = [json.loads(r[0]) for r in db.execute("SELECT payload FROM events WHERE run_id=? ORDER BY sequence", (run[0],))] if run else []
            artifacts = [dict(r) for r in db.execute("SELECT path,updated FROM artifacts WHERE project_id=? ORDER BY path", (project_id,))]
        return {"id": row["id"], "threadId": row["thread_id"], "version": row["version"],
                "snapshot": json.loads(row["snapshot"]), "status": row["status"], "updated": row["updated"],
                "activeRun": row["active_run"], "result": json.loads(row["result"]) if row["result"] else None,
                "resultVersion": row["result_version"], "events": events, "artifacts": artifacts,
                "instructions": json.loads(row["instructions"])}

    def list(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,version,snapshot,status,updated FROM projects ORDER BY updated DESC LIMIT 50").fetchall()
        return [{"id": r["id"], "version": r["version"], "workflow": json.loads(r["snapshot"])["workflow"],
                 "question": json.loads(r["snapshot"])["question"], "status": r["status"], "updated": r["updated"]} for r in rows]

    def begin(self, project_id, version, run_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT version,active_run,snapshot,instructions FROM projects WHERE id=?", (identifier(project_id),)).fetchone()
            if not row or row["version"] != version or row["active_run"]:
                raise ProjectConflict("The saved project changed or is already running. Reopen it before continuing.")
            db.execute("INSERT INTO runs VALUES(?,?,?,'running',?)", (run_id, project_id, version, now()))
            instructions = json.loads(row["instructions"])
            question = json.loads(row["snapshot"])["question"]
            if not instructions or instructions[-1] != question:
                instructions.append(question)
            if len(instructions) > 100:
                raise ProjectConflict("This project reached its revision budget. Start a new project to continue.")
            db.execute("UPDATE projects SET active_run=?,status='investigating',updated=?,instructions=? WHERE id=?",
                       (run_id, now(), json.dumps(instructions), project_id))

    def is_current(self, project_id, run_id):
        with self.connect() as db:
            row = db.execute("SELECT active_run FROM projects WHERE id=?", (project_id,)).fetchone()
        return bool(row and row[0] == run_id)

    def event(self, project_id, event):
        with self.connect() as db:
            row=db.execute("SELECT active_run,snapshot FROM projects WHERE id=?", (project_id,)).fetchone()
            if row[0] != event["run_id"]:
                return
            if json.loads(row["snapshot"])["workflow"] == "street":
                from traffic_retention import archive_event
                event=archive_event(event)
            db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?)", (event["run_id"], event["sequence"], json.dumps(event)))

    def artifact(self, project_id, path, content=None, run_id=None):
        if not isinstance(path, str) or not path.startswith("/project/") or ".." in path or "\\" in path:
            raise ValueError("Invalid project artifact path.")
        with self.connect() as db:
            if content is None:
                row = db.execute("SELECT content FROM artifacts WHERE project_id=? AND path=?", (identifier(project_id), path)).fetchone()
                if not row:
                    raise ValueError("Artifact not found.")
                return row[0]
            db.execute("BEGIN IMMEDIATE")
            if run_id and db.execute("SELECT active_run FROM projects WHERE id=?", (project_id,)).fetchone()[0] != run_id:
                return
            row=db.execute("SELECT snapshot FROM projects WHERE id=?", (project_id,)).fetchone()
            if row and json.loads(row[0])["workflow"] == "street":
                from traffic_retention import archive_artifact
                content=archive_artifact(path, content)
                if content is None:
                    return
            if len(content) > 200_000:
                raise ValueError("Artifact exceeds the local workspace budget.")
            db.execute("INSERT OR REPLACE INTO artifacts VALUES(?,?,?,?,?)", (project_id, path, content, run_id, now()))

    def finish(self, project_id, run_id, result, status):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT active_run,version,snapshot FROM projects WHERE id=?", (project_id,)).fetchone()
            if not row or row[0] != run_id:
                return False
            if json.loads(row["snapshot"])["workflow"] == "street":
                from traffic_retention import archive_result
                result=archive_result(result)
            db.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))
            db.execute("UPDATE projects SET active_run=NULL,status=?,result=?,result_version=?,updated=? WHERE id=?",
                       (status, json.dumps(result, allow_nan=False), row[1], now(), project_id))
        return True

    @contextmanager
    def checkpointer(self):
        from langgraph.checkpoint.sqlite import SqliteSaver
        connection = sqlite3.connect(self.graph_path, check_same_thread=False, timeout=15)
        self.graph_path.chmod(0o600)
        try:
            yield SqliteSaver(connection)
        finally:
            connection.close()
