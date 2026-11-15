"""Curated historical evaluation context and validated local traffic history.

Only deterministic simulation inputs/results enter this module. Live traffic
snapshots and agent prose are deliberately absent from its persistent records.
"""
import json

from proposal import comparison_fingerprint, from_traffic_comparison
from traffic_analysis import comparison_facts, validate_layouts


def latest_evaluation(project):
    history = (project or {}).get('trafficDesignHistory') or []
    if history:
        return history[-1]
    result = (project or {}).get('result') or {}
    return result if (result.get('comparison') or {}).get('status') == 'completed' else None


def prior_context(record):
    if not record:
        return None
    comparison = record['comparison']
    facts = [item for item in comparison_facts(comparison)
             if item['id'].endswith(('-co2', '-delay', '-completion', '-entry-failures', '-verdict', '-design'))
             or item['id'] == 'traffic-model-assumptions']
    return {
        'revision': comparison['revision'],
        'policy': comparison.get('ranking', {}).get('policy'),
        'layouts': list(comparison.get('layouts', {}).values()),
        'facts': [{**item, 'id': 'previous-' + item['id'],
                   'label': 'Earlier evaluation: ' + item['label'],
                   'note': f"Earlier revision {comparison['revision']}; not the current evaluation. " + item.get('note', '')}
                  for item in facts],
        'usage': 'Earlier historical simulation only. Preserve unchanged design parameters and planner constraints. Evaluate changed layouts together with the same baseline; do not claim current traffic benefits.'}


def revised_layouts(record, changes):
    if not record:
        raise ValueError('There is no completed prior evaluation to revise. Supply two or three complete layouts.')
    if not isinstance(changes, list) or not 1 <= len(changes) <= 3:
        raise ValueError('Provide one to three named layout changes.')
    layouts = {key: dict(value) for key, value in record['comparison']['layouts'].items()}
    seen, altered = set(), False
    allowed = {'name', 'approach', 'lanes_removed', 'length_m', 'new_use'}
    for change in changes:
        if not isinstance(change, dict) or set(change) - allowed or len(change) < 2:
            raise ValueError('Each revision needs a prior layout name and supported changed parameters.')
        name = change.get('name')
        if name not in layouts or name in seen:
            raise ValueError('Revise each existing layout at most once by its exact saved name.')
        seen.add(name)
        altered |= any(layouts[name].get(k) != v for k, v in change.items())
        layouts[name].update(change)
    if not altered:
        raise ValueError('The supplied changes leave every layout unchanged.')
    return validate_layouts(list(layouts.values()))


def revision_summary(comparison, previous):
    if not previous:
        return 'First saved evaluation at this selected site.'
    old = previous['comparison'].get('layouts', {})
    descriptions = []
    for name, params in comparison.get('layouts', {}).items():
        if name not in old:
            descriptions.append(f'{name}: new alternative')
            continue
        changes = [f'{key.replace("_", " ")} {old[name].get(key)} → {value}'
                   for key, value in params.items() if old[name].get(key) != value]
        if changes:
            descriptions.append(f'{name}: ' + ', '.join(changes))
    removed = set(old) - set(comparison.get('layouts', {}))
    descriptions.extend(f'{name}: removed from this evaluation' for name in sorted(removed))
    return (f"Compared with revision {previous['comparison']['revision']}: " + '; '.join(descriptions) + '.') if descriptions else 'Layout parameters retained; evaluation refreshed with current constraints and source checks.'


def evaluation_record(result, snapshot):
    """Validate the complete publication, including rejected layouts without a winner."""
    c = result['comparison']
    identity = {'site_id': snapshot['siteId'], 'revision': snapshot['proposalRevision'],
                'input_revision': snapshot['inputRevision']}
    if c.get('workflow') != 'street' or any(c.get(key) != value for key, value in identity.items()):
        raise ValueError('Traffic evaluation does not match the saved project revision.')
    if c.get('input_hash') != comparison_fingerprint(c, **identity):
        raise ValueError('Traffic evaluation inputs or results changed after publication.')
    alternatives = {name: from_traffic_comparison(c, name, **identity).model_dump(mode='json') for name in c['layouts']}
    supplied = json.loads(json.dumps(result.get('alternatives', {})))
    if supplied != alternatives:
        raise ValueError('Traffic alternative geometry and metrics do not match their evaluated revision.')
    proposal = alternatives.get(c['ranking'].get('recommended'))
    if json.loads(json.dumps(result.get('proposal'))) != proposal:
        raise ValueError('Traffic recommendation does not match the evaluated winner.')
    # trafficPlan is local deterministic metadata, never narrative or live evidence.
    return {'revision': c['revision'], 'inputRevision': c['input_revision'], 'comparison': c,
            'proposal': proposal, 'alternatives': alternatives, 'trafficPlan': result.get('trafficPlan')}
