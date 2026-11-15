"""Decision guidance from the evidence saved with a place search.

This is application-authored guidance, not a benefit estimate. Comparisons use
only the returned choices and never change their screening order.
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


def _goal_topics(goal):
    text = goal.lower()
    return {
        'access': bool(re.search(r'\b(access|entrances?|driveways?|deliveries|loading|parking)\b', text)),
        'walking': bool(re.search(r'\b(safe|safer|safety|pedestrians?|walk\w*|crossings?)\b', text)),
        'cost': bool(re.search(r'\b(low[ -]cost|cheap|budget|low[ -]disruption|minimal disruption|avoid construction)\b', text)),
        'planting': bool(re.search(r'\b(trees?|shade|plant\w*|green\w*)\b', text)),
    }


def _goal_checks(topics, workflow):
    """Shared constraints are shown once rather than repeated on every card."""
    checks = []
    if topics['access']:
        checks.append('Keep driveways and loading entrances clear when comparing changes.')
    if topics['walking']:
        checks.append('Check crossing routes and sight lines before changing the street.' if workflow == 'street' else
                      'Keep sidewalks and crossings clear of planting and storage areas.')
    if topics['cost']:
        checks.append('Compare a small reversible trial with a permanent change before committing to construction.')
    if workflow == 'water' and topics['planting']:
        checks.append('Check soil space and utilities where runoff could enter a planting area.')
    return checks


def _extreme(facts, all_facts, key, *, largest=True):
    value = _number(facts, key)
    others = [_number(item, key) for item in all_facts]
    values = [item for item in others if item is not None]
    if value is None or len(values) != len(all_facts) or len(values) < 2 or len(set(values)) < 2:
        return False
    return value == (max(values) if largest else min(values))


def _nearby_uses(facts):
    uses = []
    prefix = 'Nearby CoStar records by property type: '
    for key, item in facts.items():
        if not key.startswith('costar-nearby-use-') or not str(item.get('label', '')).startswith(prefix):
            continue
        count = _number(facts, key)
        if count is not None and count > 0:
            uses.append((item['label'][len(prefix):], item['id']))
    return uses


def _comparison(facts, all_facts, workflow):
    value = _number(facts, 'signal')
    values = [_number(item, 'signal') for item in all_facts]
    values = [item for item in values if item is not None]
    if value is None or len(values) != len(all_facts) or len(values) < 2:
        return 'Trace this potential runoff collection point' if workflow == 'water' else 'Locate the cause of this slowdown'
    strongest = max(values) if workflow == 'water' else min(values)
    tied = values.count(strongest) > 1
    if value == strongest:
        return (('Joint largest' if tied else 'Largest') + ' terrain collection signal among these choices' if workflow == 'water' else
                ('Joint strongest' if tied else 'Strongest') + ' slowdown among these choices')
    return ('A smaller terrain collection signal to compare' if workflow == 'water' else
            'A less severe slowdown to compare with the other locations')


def _tradeoff(facts, workflow, citations):
    loading = _number(facts, 'costar-reportedLoadingDocks')
    parking = _number(facts, 'costar-reportedParkingSpaces')
    outside = _number(facts, 'parcel-outside-footprints')
    if loading is not None and loading > 0:
        citations.append(facts['costar-reportedLoadingDocks']['id'])
        return (f'The property record lists {loading:g} loading docks. Keep delivery paths clear when choosing a footprint; '
                'the record does not show when deliveries occur.')
    if parking is not None and parking > 0:
        citations.append(facts['costar-reportedParkingSpaces']['id'])
        return f'The property record lists {parking:g} parking spaces. Check entrances and actual use before reallocating any space.'
    uses = _nearby_uses(facts)
    if uses:
        citations.extend(identifier for _, identifier in uses)
        names = ', '.join(use for use, _ in uses)
        lower = names.lower()
        if any(word in lower for word in ('multifamily', 'residential', 'apartment')):
            caution = 'Check resident driveways and walking routes; a curb change could affect access to homes.'
        elif any(word in lower for word in ('retail', 'restaurant', 'shopping')):
            caution = 'Check shop entrances and delivery or pickup activity before changing curb space.'
        elif any(word in lower for word in ('industrial', 'warehouse', 'manufactur')):
            caution = 'Check truck entrances and turning space before narrowing an approach or adding planting.'
        elif any(word in lower for word in ('office', 'medical', 'hospital')):
            caution = 'Check building entrances and arrival or pickup activity before changing access.'
        else:
            caution = 'Check entrances and operating needs with the affected properties before changing access.'
        return f'Nearby property records include {names}. {caution} Nearby records do not establish ownership of this site.'
    if outside is not None:
        citations.append(facts['parcel-outside-footprints']['id'])
        return (f'The map shows {outside:,.0f} m² outside building footprints on the parcel. '
                'Check whether access, parking or utilities occupy it before treating it as usable space.')
    length = _number(facts, 'length_m')
    if workflow == 'street' and length is not None:
        citations.append(facts['length_m']['id'])
        return (f'The traffic evidence covers {length:,.1f} m of mapped road. Check both ends before shifting a queue beyond this observed stretch.')
    return ('Check who uses the curb and nearby entrances; moving a queue could shift delay to another approach.'
            if workflow == 'street' else
            'Keep entrances and walking routes open, and check where overflow would go when the planting or storage area fills.')


def _traffic_next(facts, all_facts, topics, citations):
    historical = facts.get('historical-demand-date')
    length = _number(facts, 'length_m')
    uses = _nearby_uses(facts)
    names = ', '.join(use for use, _ in uses)
    lower = names.lower()
    if historical and historical.get('value'):
        citations.append(historical['id'])
        action = (f'Use the linked turning counts from {historical["value"]} to set up a historical comparison, '
                  'then check today’s turning movements and network layout before testing a change.')
    elif uses and any(word in lower for word in ('multifamily', 'residential', 'apartment')):
        citations.extend(identifier for _, identifier in uses)
        action = ('Start at the nearby housing entrances: mark where residents walk or drive across this approach, '
                  'and observe whether the queue blocks those routes before considering signal or curb changes.')
    elif uses and any(word in lower for word in ('retail', 'restaurant', 'shopping')):
        citations.extend(identifier for _, identifier in uses)
        action = ('Observe the curb beside the nearby shops during deliveries or pickups. Check whether stopped vehicles '
                  'interrupt through traffic before comparing loading management with signal changes.')
    elif uses and any(word in lower for word in ('industrial', 'warehouse', 'manufactur')):
        citations.extend(identifier for _, identifier in uses)
        action = ('Inspect the nearby industrial entrances and observe truck turns. Check whether access movements '
                  'explain the queue before proposing a narrower lane or a curb change.')
    elif length is not None:
        citations.append(facts['length_m']['id'])
        if _extreme(facts, all_facts, 'length_m'):
            action = (f'Walk the full {length:,.1f} m mapped stretch in sections and note where each queue begins. '
                      'Check each junction or driveway encountered before assuming one signal change would address the whole stretch.')
        elif _extreme(facts, all_facts, 'length_m', largest=False):
            action = (f'Start at the downstream end of this {length:,.1f} m mapped stretch. '
                      'Locate the first stopping point and check its signal, crossing or driveway before extending the study along the corridor.')
        else:
            action = (f'Walk this {length:,.1f} m mapped stretch from the downstream end, noting stopping points and access conflicts '
                      'before choosing a signal or curb change to test.')
    else:
        action = 'Check whether signal timing, turning queues or driveway conflicts explain the slowdown, then choose a change to test.'
    if not historical and uses and length is not None:
        citations.append(facts['length_m']['id'])
        if _extreme(facts, all_facts, 'length_m'):
            action += f' Cover the full {length:,.1f} m in sections to check whether several stopping points contribute.'
        elif _extreme(facts, all_facts, 'length_m', largest=False):
            action += f' Focus first on the downstream stopping point within this {length:,.1f} m stretch.'
    # One relevant goal check per candidate; shared requirements remain above the cards.
    if topics['walking']:
        action += ' Map crossing routes and sight lines at the stopping points.'
    elif topics['access']:
        action += ' Mark driveways and loading entrances that must remain clear.'
    elif topics['cost']:
        action += ' Start with a small reversible trial after identifying the cause.'
    return action


def enrich_feedback(bundle, workflow, goal):
    """Return a copy with evidence-linked guidance and shared goal constraints.

    The guidance describes the saved search snapshot, so it remains meaningful
    after the live feed changes. No model context or source order is changed.
    """
    result = deepcopy(bundle)
    candidates = [c for c in result.get('candidates', []) if c.get('available') is not False]
    goal = goal if isinstance(goal, str) else ''
    result['feedbackGoal'] = goal
    topics = _goal_topics(goal)
    result['goalChecks'] = _goal_checks(topics, workflow)
    all_facts = [_facts(candidate) for candidate in candidates]
    for candidate, facts in zip(candidates, all_facts):
        value = _number(facts, 'signal')
        citations = [facts['signal']['id']] if value is not None else []
        headline = _comparison(facts, all_facts, workflow)
        if workflow == 'street':
            observation = (f'At search time, traffic was moving at {value:g}% of the estimated uncongested speed here.' if value is not None else
                           'Use this saved location to observe where vehicles stop, then identify a signal or access change to compare.')
            speed = _number(facts, 'speed_kmh')
            free = _number(facts, 'free_flow_kmh')
            length = _number(facts, 'length_m')
            delay = _number(facts, 'time_penalty_s')
            if speed is not None and free is not None and free > 0:
                observation += f' The speed estimate was {speed:g} km/h against a {free:g} km/h reference.'
                citations.extend([facts['speed_kmh']['id'], facts['free_flow_kmh']['id']])
            if length is not None:
                observation += f' The mapped slow stretch covers {length:,.1f} m.'
                citations.append(facts['length_m']['id'])
            if delay is not None:
                observation += f' The constant-speed estimate adds {delay:g} seconds over the mapped portion; this is not a measured trip delay.'
                citations.append(facts['time_penalty_s']['id'])
            if _extreme(facts, all_facts, 'length_m'):
                relevance = ('This is the longest mapped slow stretch among these choices. Choose it to investigate how delay builds along the approach; '
                             'a corridor walk can reveal whether several stopping points need separate checks.')
            elif _extreme(facts, all_facts, 'length_m', largest=False):
                relevance = ('This is the shortest mapped slow stretch among these choices. Choose it for a focused check of the stopping point and nearby entrances '
                             'before deciding whether a wider corridor study is needed.')
            elif _extreme(facts, all_facts, 'time_penalty_s'):
                relevance = ('This has the largest screened excess travel time among these choices. It merits checking where the queue starts; '
                             'the estimate does not establish how often that delay occurs or which change would reduce emissions.')
            else:
                relevance = ('The observed slowdown gives you a concrete place to check signal operation, turning queues and access conflicts. '
                             'Use the site context below to decide what to inspect first; speed alone cannot identify an emissions-saving design.')
            next_step = _traffic_next(facts, all_facts, topics, citations)
        else:
            observation = (f'The terrain evidence suggests that water from about {value:,.0f} m² of land may collect near this point.' if value is not None else
                           'Use this saved location to trace the downhill route and locate the actual inlet before choosing a planting footprint.')
            path = _number(facts, 'path_length_m')
            drop = _number(facts, 'drop_m')
            if path is not None and path > 0:
                observation += f' The mapped downhill route is about {path:,.0f} m long.'
                citations.append(facts['path_length_m']['id'])
            if drop is not None and drop > 0:
                observation += f' Its estimated elevation drop is {drop:g} m.'
                citations.append(facts['drop_m']['id'])
            relevance = ('Use this collection signal to choose where to trace runoff on site. Confirm which surfaces reach the inlet before sizing storage; '
                         'the terrain estimate is not the amount of water a design would capture.')
            next_step = (f'Trace the {path:,.0f} m downhill route to the actual inlet, checking for curbs or drains that divert it. '
                         if path is not None and path > 0 else
                         'Trace the downhill route to the actual inlet, checking for curbs or drains that divert it. ')
            outside = _number(facts, 'parcel-outside-footprints')
            if outside is not None:
                citations.append(facts['parcel-outside-footprints']['id'])
                next_step += f'Within the {outside:,.0f} m² mapped outside buildings, mark a footprint that leaves entrances and overflow paths open.'
            else:
                next_step += 'Mark a possible planting or storage area beside the inlet, with a clear overflow route.'
            if topics['planting']:
                next_step += ' Check soil space and utilities before selecting trees or planting depth.'
            elif topics['walking']:
                next_step += ' Keep the footprint outside walking routes and crossing approaches.'
            elif topics['access']:
                next_step += ' Mark driveways and loading entrances that must remain clear.'
        tradeoff = _tradeoff(facts, workflow, citations)
        candidate['feedback'] = {'headline': headline, 'observation': observation, 'relevance': relevance,
                                 'nextStep': next_step, 'tradeoff': tradeoff, 'factIds': list(dict.fromkeys(citations))}
    if candidates:
        count = len(candidates)
        compared = 'traffic observations' if workflow == 'street' else 'terrain paths where runoff may collect'
        result['summary'] = (f'Found {count} {"location" if count == 1 else "locations"} in your selected map area by comparing {compared}. '
                             'Compare the mapped extent, site context and first action below, then choose a location to develop.')
    else:
        result['summary'] = ('No traffic locations could be confirmed in this map area. Zoom into a nearby busy street and search again, or select a location on the map to investigate it directly.'
                             if workflow == 'street' else
                             'No additional runoff collection locations could be confirmed in this map area. Move to an area with terrain data and search again, or select a location on the map to investigate it directly.')
    return result
