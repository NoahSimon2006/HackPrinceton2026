"""Useful place guidance from current evidence, including when synthesis fails.

This is application-authored guidance, not an agent assessment or a benefit
estimate. It deliberately leaves candidate ordering and model context alone.
"""
from copy import deepcopy
from math import isfinite
import re


def _facts(candidate):
    prefix = candidate.get('id', '') + '-'
    return {item['id'].removeprefix(prefix): item for item in candidate.get('evidence', [])
            if isinstance(item, dict) and isinstance(item.get('id'), str)}


def _number(facts, key):
    value = facts.get(key, {}).get('value')
    return value if type(value) in (int, float) and isfinite(value) and value >= 0 else None


def _goal_checks(goal, workflow):
    """Mentioned topics guide questions, never assert that a goal is satisfied."""
    text = goal.lower()
    checks = []
    if re.search(r'\b(access|entrances?|driveways?|deliveries|loading|parking)\b', text):
        checks.append('For the access part of your goal, mark driveways and loading entrances that must stay clear.')
    if re.search(r'\b(safe|safer|safety|pedestrians?|walk\w*|crossings?)\b', text):
        checks.append('For the walking and safety part of your goal, check crossing routes and sight lines before changing the street.'
                      if workflow == 'street' else
                      'For the walking and safety part of your goal, keep the sidewalk and crossings clear of any planting or storage area.')
    if re.search(r'\b(low[ -]cost|cheap|budget|low[ -]disruption|minimal disruption|avoid construction)\b', text):
        checks.append('For your cost or disruption concern, compare a small reversible trial with a permanent change before committing to construction.')
    if workflow == 'water' and re.search(r'\b(trees?|shade|plant\w*|green\w*)\b', text):
        checks.append('For the planting part of your goal, check soil space and utilities where runoff could enter the planting area.')
    return checks


def _comparison(value, values, workflow):
    if value is None or len(values) < 2:
        return 'A place to investigate runoff collection' if workflow == 'water' else 'A place to investigate traffic delay'
    strongest = max(values) if workflow == 'water' else min(values)
    tied = values.count(strongest) > 1
    if value == strongest:
        return (('Joint largest' if tied else 'Largest') + ' potential collection area among these choices' if workflow == 'water' else
                ('Joint strongest' if tied else 'Strongest') + ' slowdown among these choices')
    return ('Another runoff collection location to compare' if workflow == 'water' else
            'Another slow approach to compare')


def _tradeoff(candidate, facts, workflow, citations):
    loading = _number(facts, 'costar-reportedLoadingDocks')
    parking = _number(facts, 'costar-reportedParkingSpaces')
    outside = _number(facts, 'parcel-outside-footprints')
    if loading is not None and loading > 0:
        citations.append(facts['costar-reportedLoadingDocks']['id'])
        return (f'The property record lists {loading:g} loading docks. Keep delivery paths clear when choosing a footprint; '
                'the record does not show when deliveries occur.')
    if parking is not None and parking > 0:
        citations.append(facts['costar-reportedParkingSpaces']['id'])
        return (f'The property record lists {parking:g} parking spaces. Check entrances and actual use before reallocating any space.')
    if outside is not None:
        citations.append(facts['parcel-outside-footprints']['id'])
        return (f'The map shows {outside:,.0f} m² outside building footprints on the parcel. '
                'Check whether it is occupied by access, parking or utilities before treating it as usable space.')
    return ('Check who uses the curb and nearby entrances; moving a queue could shift delay to another approach.'
            if workflow == 'street' else
            'Keep entrances and walking routes open, and check where overflow would go when the planting or storage area fills.')


def enrich_feedback(bundle, workflow, goal):
    """Return a copy with fresh, evidence-linked guidance for every live choice.

    Call after traffic refresh. Rebuilding prevents stale prose or comparisons
    from surviving a changed source snapshot. No raw labels/geometry are used.
    """
    result = deepcopy(bundle)
    candidates = [c for c in result.get('candidates', []) if c.get('available') is not False and not c.get('resumeNotice')]
    goal = goal if isinstance(goal, str) else ''
    result['feedbackGoal'] = goal
    values = [_number(_facts(c), 'signal') for c in candidates]
    values = [value for value in values if value is not None]
    checks = _goal_checks(goal, workflow)
    for candidate in candidates:
        facts = _facts(candidate)
        value = _number(facts, 'signal')
        citations = [facts['signal']['id']] if value is not None else []
        headline = _comparison(value, values, workflow)
        if workflow == 'street':
            observation = (f'Traffic is moving at {value:g}% of the estimated uncongested speed here.' if value is not None else
                           candidate.get('environmental', {}).get('summary') or 'This location is a starting point for checking traffic delay in your selected area.')
            speed = _number(facts, 'speed_kmh')
            free = _number(facts, 'free_flow_kmh')
            if speed is not None and free is not None and free > 0:
                observation += f' The current estimate is {speed:g} km/h; the estimated uncongested reference is {free:g} km/h.'
                citations.extend([facts['speed_kmh']['id'], facts['free_flow_kmh']['id']])
            relevance = ('For traffic and emissions, this points to a place to investigate stop-and-go driving. '
                         'A slowdown alone does not tell us which change would reduce emissions.')
            next_step = 'Check whether signal timing, turning queues or driveway conflicts explain the slowdown, then choose a change to test.'
            historical = facts.get('historical-demand-date')
            if historical and historical.get('value'):
                citations.append(historical['id'])
                next_step = (f'Use the linked turning counts from {historical["value"]} to set up a historical comparison, '
                             'then check today’s turning movements and network layout before testing a change.')
        else:
            observation = (f'Terrain suggests that water from about {value:,.0f} m² of land may collect near this point.' if value is not None else
                           candidate.get('environmental', {}).get('summary') or 'This location is a starting point for checking where runoff collects in your selected area.')
            relevance = ('For stormwater, this is a place to look for an inlet or a planting area that could intercept runoff. '
                         'The terrain estimate does not establish how much water a design would capture.')
            next_step = 'Trace the downhill route to the actual inlet, then mark a possible planting or storage area beside it.'
            path = _number(facts, 'path_length_m')
            drop = _number(facts, 'drop_m')
            if path is not None and path > 0:
                observation += f' The mapped downhill route is about {path:,.0f} m long.'
                citations.append(facts['path_length_m']['id'])
            if drop is not None and drop > 0:
                observation += f' Its estimated elevation drop is {drop:g} m.'
                citations.append(facts['drop_m']['id'])
        if checks:
            next_step += ' ' + ' '.join(checks)
        tradeoff = _tradeoff(candidate, facts, workflow, citations)
        candidate['feedback'] = {'headline': headline, 'observation': observation, 'relevance': relevance,
                                 'nextStep': next_step, 'tradeoff': tradeoff, 'factIds': list(dict.fromkeys(citations))}
    if candidates:
        count = len(candidates)
        compared = ('current slowdowns' if workflow == 'street' else 'terrain paths where runoff may collect')
        result['summary'] = (f'Found {count} {"location" if count == 1 else "locations"} in your selected map area by comparing {compared}. '
                             'Each option explains what we found and a next step for your goal. Choose one to develop a site proposal.')
    else:
        result['summary'] = ('No current traffic locations could be confirmed in this map area. Zoom into a nearby busy street and search again, or select a location on the map to investigate it directly.'
                             if workflow == 'street' else
                             'No additional runoff collection locations could be confirmed in this map area. Move to an area with terrain data and search again, or select a location on the map to investigate it directly.')
    return result
