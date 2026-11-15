"""Durable area/choice history with expiring, memory-only live traffic evidence."""
from copy import deepcopy
import json
import math
from threading import RLock, Timer
import time
from uuid import uuid4

from project_store import ProjectConflict, identifier, now

REFRESH_NOTICE = "Live traffic evidence expired and is not archived. Run a new search to refresh this area; earlier choices remain in history."


def validate_search(value):
    if not isinstance(value, dict):
        raise ValueError("Supply a goal and a bounded map area.")
    workflow, goal, bounds = value.get('workflow'), value.get('goal'), value.get('bounds')
    if workflow not in ('street', 'water') or not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 1500:
        raise ValueError("Choose a workflow and enter a goal up to 1,500 characters.")
    if (not isinstance(bounds, list) or len(bounds) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
            or not -118.67 <= bounds[0] < bounds[2] <= -118.10
            or not 33.70 <= bounds[1] < bounds[3] <= 34.35
            or bounds[2] - bounds[0] > .1 or bounds[3] - bounds[1] > .1):
        raise ValueError("Choose a Los Angeles map area no wider or taller than 0.1 degrees. Zoom in or use a pilot area.")
    return {'workflow': workflow, 'goal': goal.strip(), 'bounds': bounds}


def expired_candidate(candidate):
    return {'id': candidate['id'], 'label': 'Previous traffic opportunity', 'available': False,
            'groupedCandidateIds': candidate.get('provenance', {}).get('groupedCandidateIds', [candidate['id']]),
            'resumeNotice': REFRESH_NOTICE}


def archive_batch(batch, workflow):
    if workflow != 'street':
        return deepcopy(batch)
    if not batch['candidates']:
        # An empty search has no live observation to expire. Keep actionable
        # application copy, without persisting source or model narratives.
        return {'id': batch['id'], 'created': batch['created'], 'candidates': [],
                'summary': 'No additional traffic locations could be confirmed in this map area. Try a smaller or nearby area, or pick a spot on the map to investigate it directly.',
                'agentStatus': batch.get('agentStatus'), 'exhausted': batch.get('exhausted', False), 'warnings': []}
    # Even model prose, provider geometry and derived metrics can encode feed history.
    return {'id': batch['id'], 'created': batch['created'], 'candidates': [expired_candidate(c) for c in batch['candidates']],
            'summary': REFRESH_NOTICE, 'agentStatus': batch.get('agentStatus'), 'exhausted': batch.get('exhausted', False),
            'methodology': 'Environmental screening first; feasibility and disruption next. Readiness is separate.',
            'warnings': [], 'resumeNotice': REFRESH_NOTICE}


class ScoutStore:
    def __init__(self, projects):
        self.projects, self.lock, self.live = projects, RLock(), {}
        with projects.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS scouts (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            for row in db.execute('SELECT id,payload FROM scouts').fetchall():
                value = json.loads(row['payload'])
                if value['status'] == 'running':
                    value.update(status='interrupted', runId=None, error='The server restarted. Your search history is saved; run the search again.')
                    self._write(db, value)

    @staticmethod
    def _write(db, value):
        db.execute('INSERT OR REPLACE INTO scouts VALUES(?,?)', (value['id'], json.dumps(value, allow_nan=False)))

    def _read(self, db, search_id):
        row = db.execute('SELECT payload FROM scouts WHERE id=?', (identifier(search_id),)).fetchone()
        if not row:
            raise ValueError('Area search not found.')
        return json.loads(row[0])

    def _purge(self):
        current = time.time()
        for key, (expiry, _) in list(self.live.items()):
            if expiry <= current:
                del self.live[key]

    def get(self, search_id):
        with self.lock, self.projects.connect() as db:
            self._purge()
            value = self._read(db, search_id)
            value['batches'] = [deepcopy(self.live.get((search_id, b['id']), (0, b))[1]) for b in value['batches']]
            value['exhausted'] = bool(value['batches'] and value['batches'][-1].get('exhausted'))
            return value

    def list(self):
        with self.projects.connect() as db:
            values = [json.loads(row[0]) for row in db.execute('SELECT payload FROM scouts')]
        return [{k: v[k] for k in ('id', 'workflow', 'goal', 'bounds', 'status', 'updated', 'selected')}
                for v in sorted(values, key=lambda v: v['updated'], reverse=True)[:50]]

    def begin(self, request, run_id):
        inputs = validate_search(request)
        with self.lock, self.projects.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if request.get('searchId'):
                value = self._read(db, request['searchId'])
                if any(value[k] != v for k, v in inputs.items()):
                    raise ProjectConflict('The area or goal changed. Start a new search instead of extending this history.')
                if value['status'] == 'running':
                    raise ProjectConflict('This area search is still running.')
                if len(value['batches']) >= 10:
                    raise ProjectConflict('This search reached ten batches. Start a new area search.')
            else:
                value = {**inputs, 'id': uuid4().hex, 'batches': [], 'selected': None, 'artifacts': {}}
            value.update(status='running', runId=run_id, updated=now(), events=[], error=None)
            self._write(db, value)
        return value

    def is_current(self, search_id, run_id):
        with self.projects.connect() as db:
            value = self._read(db, search_id)
        return value['status'] == 'running' and value['runId'] == run_id

    def event(self, search_id, event):
        with self.lock, self.projects.connect() as db:
            value = self._read(db, search_id)
            if value['status'] != 'running' or value['runId'] != event['run_id']:
                return
            # Events are application-authored lifecycle messages, not model prose/facts.
            value['events'].append({k: event[k] for k in ('run_id', 'sequence', 'at', 'specialist', 'stage', 'status', 'summary') if k in event})
            value['events'] = value['events'][-160:]
            self._write(db, value)

    def artifact(self, search_id, run_id, path, content):
        if not isinstance(path, str) or not path.startswith('/project/') or '..' in path or '\\' in path or len(content) > 200_000:
            raise ValueError('Invalid scouting artifact.')
        with self.lock, self.projects.connect() as db:
            value = self._read(db, search_id)
            if value['runId'] != run_id or value['status'] != 'running' or value['workflow'] == 'street':
                return
            # Keep artifacts by run so show-more cannot erase earlier evidence.
            value['artifacts'].setdefault(run_id, {})[path] = content
            self._write(db, value)

    def finish(self, search_id, run_id, result=None, *, status='ready', error=None):
        with self.lock, self.projects.connect() as db:
            self._purge()
            value = self._read(db, search_id)
            if value['runId'] != run_id or value['status'] != 'running':
                return False
            if result is not None:
                batch = {**deepcopy(result), 'id': run_id, 'created': now()}
                for candidate in batch.get('candidates', []):
                    candidate.pop('modelContext', None)
                value['batches'].append(archive_batch(batch, value['workflow']))
                if value['workflow'] == 'street' and batch.get('candidates'):
                    expiry = min(c.get('expiresAt', 0) for c in batch['candidates'])
                    if expiry > time.time():
                        self.live[(search_id, run_id)] = (expiry, batch)
                        def expire():
                            with self.lock:
                                self._purge()
                        timer = Timer(max(.01, expiry - time.time() + .01), expire)
                        timer.daemon = True
                        timer.start()
                        if len(self.live) > 50:
                            del self.live[next(iter(self.live))]
            value.update(status=status, error=error, runId=None, updated=now())
            self._write(db, value)
            return True

    def cancel(self, search_id, expected_run=None):
        with self.lock, self.projects.connect() as db:
            value = self._read(db, search_id)
            run_id = value['runId']
            if expected_run is not None and run_id != expected_run:
                return None
            if value['status'] == 'running':
                value.update(status='canceled', runId=None, updated=now())
                self._write(db, value)
            return run_id

    def select(self, search_id, candidate_id):
        with self.lock:
            value = self.get(search_id)
            if value['status'] == 'running':
                raise ProjectConflict('Wait for this investigation to finish before choosing a location.')
            candidate = next((c for b in value['batches'] for c in b['candidates'] if c['id'] == candidate_id), None)
            if not candidate:
                raise ValueError('Choose a location from this search history.')
            if candidate.get('available') is False or not candidate.get('center'):
                raise ProjectConflict(REFRESH_NOTICE)
            selected = value.get('selected')
            selections = value.get('selections', {})
            if selected:
                selections.setdefault(selected['candidateId'], selected['projectId'])
            if candidate_id in selections:
                project = self.projects.get(selections[candidate_id])
                with self.projects.connect() as db:
                    durable = self._read(db, search_id)
                    durable.update(selected={'candidateId': candidate_id, 'projectId': project['id']}, selections=selections, updated=now())
                    self._write(db, durable)
                return {'project': project, 'candidate': candidate, 'search': self.get(search_id)}
            lon, lat = candidate['center']
            project = self.projects.save({'workflow': value['workflow'], 'siteId': 'scout-' + candidate_id,
                'lon': lon, 'lat': lat, 'propertyId': candidate.get('propertyId'), 'question': value['goal'],
                'markings': [], 'rainfallScenario': None, 'inputRevision': 0, 'proposalRevision': 1})
            origin = {'searchId': search_id, 'candidateId': candidate_id, 'goal': value['goal'],
                      'selection': 'Explicit user choice from researched opportunities; refresh source evidence before design.'}
            if value['workflow'] == 'water':
                origin.update(environmental=candidate.get('environmental'), direction=candidate.get('direction'),
                              feasibility=candidate.get('feasibility'), disruption=candidate.get('disruption'),
                              readiness=candidate.get('readiness'), evidence=candidate.get('evidence'), provenance=candidate.get('provenance'))
            # This canonical selection is application-authored; never copy raw geometry
            # or provider location labels into the agent's virtual filesystem.
            with self.projects.connect() as db:
                db.execute('INSERT OR REPLACE INTO artifacts VALUES(?,?,?,?,?)',
                           (project['id'], '/project/scouting-selection.json', json.dumps(origin), None, now()))
                durable = self._read(db, search_id)
                selections[candidate_id] = project['id']
                durable.update(selected={'candidateId': candidate_id, 'projectId': project['id']}, selections=selections, updated=now())
                self._write(db, durable)
            return {'project': self.projects.get(project['id']), 'candidate': candidate, 'search': self.get(search_id)}
