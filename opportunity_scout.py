"""Bounded source-backed location research; geometry stays local.

Ordering is an environmental screen, never predicted design benefit.
Readiness is intentionally absent from the comparison key.
"""
from copy import deepcopy
from math import isfinite
from hashlib import sha256
import json
import time
from shapely.geometry import Point, shape, box
from shapely import transform
from discovery import map_discovery, query_area, load_discovery, traffic_context_at_site
from agent_activity import TransientSourceError
from site_identity import resolve_site
from site_measurements import PROJECT, fact, measure_outlines, property_facts

MAX_SCREEN = 50
MAX_CHOICES = 3
POLICY = 'environmental-screen-v1'


def validate_area(workflow, bounds):
    """Validate before fetching a provider snapshot."""
    if (workflow not in ('water', 'street') or not isinstance(bounds, (list, tuple)) or len(bounds) != 4
            or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not isfinite(n) for n in bounds)
            or not -118.67 <= bounds[0] < bounds[2] <= -118.10
            or not 33.70 <= bounds[1] < bounds[3] <= 34.35
            or bounds[2] - bounds[0] > .1 or bounds[3] - bounds[1] > .1):
        raise ValueError('Choose a map area in Los Angeles no wider or taller than 0.1 degrees.')
    return list(bounds)


def _key(workflow, feature):
    value = feature['properties']['value']
    return (-value if workflow == 'water' else value, feature['id'])


def _origin(layer):
    source = layer['source']
    return {key: value for key, value in {
        'provider': source.get('label'), 'url': source.get('url'),
        'observed_at': source.get('observed_at'), 'retrieved_at': source.get('retrieved_at'),
        'collection': source.get('product')}.items() if value is not None}


def _anchor_traffic_signals(signals, bounds):
    """New choices may target a uniquely supported counted intersection.

    Keep the environmental ordering and provider extent. This is an explicit
    location choice before selection, never a relocation of a saved project or
    a claim that historical demand describes today's flow.
    """
    try:
        inventory = load_discovery('street')
        layer = next((item for item in inventory['layers'] if item['id'] == 'turning'), {})
        nodes = [(item, Point(*PROJECT.transform(*item['properties']['center'])))
                 for item in layer.get('features', [])
                 if box(*bounds).covers(Point(item['properties']['center']))]
    except (OSError, ValueError, TypeError, KeyError):
        return signals
    result = []; anchored = {}; checked = {}
    for signal in signals:
        matches = [(item, point.distance(signal['_shape'])) for item, point in nodes
                   if point.distance(signal['_shape']) <= 25]
        if len(matches) == 1:
            node, distance = matches[0]; node_id = node['id']; center = node['properties']['center']
            if node_id not in checked:
                try:
                    checked[node_id] = traffic_context_at_site(*center)
                except (OSError, ValueError, TypeError, KeyError):
                    checked[node_id] = None
            context = checked[node_id]
            if context:
                signal = {**signal, 'center': list(center),
                          'evaluationLink': {'kind': 'verified_counted_intersection',
                              'turningFeatureId': node_id, 'turningVersion': inventory['version'],
                              'countDate': context['sheet']['date'], 'distanceToFlowM': round(distance, 1),
                              'sourceCenter': signal['center']},
                          '_intersectionLabel': node['properties'].get('label', 'Verified counted intersection')}
                signal['id'] = 'street-' + sha256((signal['id'] + '|' + node_id).encode()).hexdigest()[:16]
                signal['memberIds'] = list(dict.fromkeys([signal['id'], *signal['memberIds']]))
                if node_id in anchored:
                    prior = anchored[node_id]
                    prior['memberIds'] = list(dict.fromkeys([*prior['memberIds'], *signal['memberIds']]))
                    continue
                anchored[node_id] = signal
        result.append(signal)
    return result


def _signals(workflow, bounds, data):
    # Sort before query_area's bound so file order cannot hide stronger signals.
    ordered = deepcopy(data)
    allowed = ('terrain',) if workflow == 'water' else ('approaches', 'flow')
    ordered['layers'] = [layer for layer in ordered['layers'] if layer['id'] in allowed]
    for layer in ordered['layers']:
        layer['features'].sort(key=lambda feature: _key(workflow, feature))
    result = query_area(workflow, bounds, MAX_SCREEN, data=ordered)
    boundary = box(*bounds); signals = []
    members = {member for layer in result['layers'] if layer['layer'] == 'approaches'
               for feature in layer['features'] for member in feature['properties'].get('member_ids', [])}
    for layer in result['layers']:
        for feature in layer['features']:
            p = feature['properties']; detail = p.get('scalar_detail', {})
            if isinstance(p.get('value'), bool) or not isinstance(p.get('value'), (int, float)) or not isfinite(p['value']):
                continue
            center = p['center']
            if workflow == 'water':
                if p['value'] <= 0 or detail.get('window_edge_contribution'):
                    continue
                if feature['geometry']['type'] == 'LineString':
                    center = feature['geometry']['coordinates'][-1]
            elif (feature['id'] in members or p['value'] >= 90 or p['value'] <= 0
                  or detail.get('road_closure') or not detail.get('direction_verified')):
                continue
            if not boundary.covers(Point(center)):
                continue
            geometry = p.get('contributing_geometry') if workflow == 'water' else None
            geometry = geometry or feature['geometry']
            measured = transform(shape(geometry), PROJECT.transform, interleaved=False)
            if measured.is_empty or not measured.is_valid:
                continue
            identifier = workflow + '-' + sha256(feature['id'].encode()).hexdigest()[:16]
            # An approach ID changes when its set of slow portions changes.
            # Keep stable underlying source IDs as well, so show-more cannot
            # return the same queue under a new group ID or as individual flow.
            member_ids = [identifier]
            if workflow == 'street':
                member_ids.extend(workflow + '-' + sha256(member.encode()).hexdigest()[:16]
                                  for member in p.get('member_ids', []) if isinstance(member, str))
            signals.append({'feature': feature, 'layer': layer, 'center': list(center),
                            'geometry': geometry, '_shape': measured,
                            'id': identifier, 'memberIds': list(dict.fromkeys(member_ids))})
    signals.sort(key=lambda signal: _key(workflow, signal['feature']))
    # Group before excluding history: show-more cannot return a different cell
    # from the same cluster the user has already seen.
    grouped = []
    for signal in signals:
        for previous in grouped:
            a = Point(*PROJECT.transform(*signal['center'])); b = Point(*PROJECT.transform(*previous['center']))
            close = a.distance(b) < (120 if workflow == 'water' else 140)
            overlap = False
            if workflow == 'water' and signal['_shape'].area and previous['_shape'].area:
                overlap = signal['_shape'].intersection(previous['_shape']).area / min(signal['_shape'].area, previous['_shape'].area) > .25
            elif workflow == 'street':
                pd = previous['feature']['properties'].get('scalar_detail', {})
                sd = signal['feature']['properties'].get('scalar_detail', {})
                same_corridor = (pd.get('road_name') and pd.get('road_name') == sd.get('road_name')
                                 and pd.get('direction') and pd.get('direction') == sd.get('direction'))
                # Proximity alone does not make different roads or opposing
                # approaches the same opportunity. Keep their source extents
                # distinct so one cannot hide the other's counted-site link.
                close = close and same_corridor
                overlap = same_corridor and signal['_shape'].distance(previous['_shape']) < 35
            if close or overlap:
                previous['memberIds'] = list(dict.fromkeys([*previous['memberIds'], *signal['memberIds']]))
                break
        else:
            grouped.append(signal)
    return (_anchor_traffic_signals(grouped, bounds) if workflow == 'street' else grouped), result


def _research_site(workflow, center, check):
    """Use both sponsors without converting proximity into ownership."""
    from server import site_outlines, property_catalog, nearby_properties, nearby_frontages
    lon, lat = center; radius = 200 if workflow == 'street' else 110
    warnings = []; facts = []; outlines = []; matched = None
    check()
    try:
        for attempt in range(2):
            check()
            try:
                outlines = site_outlines(lon, lat, workflow)
                break
            except TransientSourceError:
                if attempt: raise
        measured, issues = measure_outlines(outlines, lon, lat, nearby=True)
        facts.extend(measured); warnings.extend(issues)
        vexcel = 'available' if outlines else 'no_feature'
    except (OSError, ValueError, TypeError, KeyError) as error:
        text = str(error)
        vexcel = ('configuration_missing' if 'key is missing' in text else 'access_denied' if 'rejected the key' in text
                  else 'no_feature' if 'No Vexcel property outlines' in text else 'unavailable')
        warnings.append('Vexcel parcel/building extraction: ' + vexcel.replace('_', ' ') + '. Site geometry remains unverified.')
    check()
    try:
        items, details, _ = property_catalog()
        resolution = resolve_site(items, lon, lat, outlines, radius=radius)
        matched = resolution['property']; nearby = nearby_properties(items, lon, lat, radius)
        selected_id = matched['id'] if matched else None
        frontages = nearby_frontages(lon, lat, selected_id, radius=radius)
        measured, issues = property_facts(details.get(selected_id), frontages, nearby=nearby)
        facts.extend(measured); warnings.extend(issues)
        costar = 'matched' if matched else 'nearby_context' if nearby else 'no_feature'
        association = resolution['status']
    except (OSError, ValueError, TypeError, KeyError):
        costar = 'unavailable'; association = 'unavailable'; nearby = []
        warnings.append('CoStar context was unavailable for this candidate.')
    check()
    return {'facts': facts, 'warnings': warnings, 'vexcel': vexcel, 'costar': costar,
            'association': association, 'property': matched,
            'nearbyUses': sorted({p['type'] for p in nearby}), 'nearbyCount': len(nearby)}


def _candidate(workflow, signal, sponsor, expires):
    layer = signal['layer']; feature = signal['feature']; p = feature['properties']
    detail = p.get('scalar_detail', {}); origin = _origin(layer)
    prefix = signal['id']; source_note = layer['limitations']
    evidence = [fact(prefix + '-signal', 'Terrain-inferred raster contribution' if workflow == 'water' else 'Current speed relative to free-flow reference',
        p['value'], 'm²' if workflow == 'water' else '%', origin, basis='estimated', method=layer['method'], note=source_note)]
    if workflow == 'water':
        for name, label, unit in (('drop_m', 'Terrain path elevation drop', 'm'), ('path_length_m', 'Terrain path length', 'm')):
            if detail.get(name) is not None:
                evidence.append(fact(prefix + '-' + name, label, detail[name], unit, origin, basis='estimated', method=layer['method'], note=source_note))
        environmental = {'summary': f"{p['value']:,.0f} m² of terrain-inferred contribution at a potential collection location.",
                         'basis': 'Bare-earth screening; drainage connection, runoff capture and flood benefit are unverified.',
                         'metrics': [{'label': 'Terrain-inferred contribution', 'value': p['value'], 'unit': 'm²'}]}
        direction = 'Investigate an interception or planting area near the mapped collection signal; locate the actual inlet before sizing a concept.'
        missing = ['Verified drainage connection and inlet', 'Treatment footprint and event assumptions']
        readiness = 'Ready for a preliminary site investigation; runoff capture cannot be evaluated yet.'
    else:
        for name, label, unit in (('speed_kmh', 'Current estimated speed', 'km/h'), ('free_flow_kmh', 'Derived free-flow reference', 'km/h'),
                                  ('length_m', 'Displayed source length', 'm'), ('time_penalty_s', 'Screened excess travel time', 'seconds')):
            if detail.get(name) is not None:
                evidence.append(fact(prefix + '-' + name, label, detail[name], unit, origin, basis='estimated', method=detail.get('baseline', layer['method']), note=source_note))
        environmental = {'summary': f"Current estimated speed is {p['value']:g}% of the free-flow reference on the mapped source portions.",
                         'basis': 'A one-time slowdown signal; neither recurring congestion nor CO₂ savings has been established.',
                         'metrics': [{'label': 'Speed relative to free flow', 'value': p['value'], 'unit': '%'}]}
        direction = 'Investigate signal, crossing and access operations along the slow approach; test a physical change only with a valid network and turning-demand scenario.'
        missing = ['Verified turning demand and simulation network association', 'Physical intervention geometry']
        readiness = 'Ready to investigate current slowdown; environmental performance needs a sourced, comparable simulation.'
        if signal.get('evaluationLink'):
            link = signal['evaluationLink']
            evidence.append(fact(prefix + '-historical-demand-date', 'Historical turning-count date for linked intersection',
                link['countDate'], '', {'provider': 'LADOT manual turning count',
                    'url': 'https://navigatela.lacity.org/dot/traffic_data/', 'observed_at': link['countDate']},
                basis='reported', method='Local original-sheet hash, parse and unique counted-intersection association checks.',
                note='Historical demand is separate from the current flow snapshot. Network restrictions and site checks still require evaluation.'))
            readiness = (f"A verified historical turning sheet from {link['countDate']} is linked to this intersection. "
                         'Current flow remains a separate snapshot; network restrictions and site checks must still pass before simulation.')
            missing = ['Simulation network/restriction and sponsor access checks', 'Physical intervention geometry',
                       'Current turning demand; historical counts are a labeled scenario only']
            direction = ('Investigate this explicitly selected counted intersection beside the mapped slow source. '
                         'Use its verified historical demand for a labeled comparison if network and site checks pass.')
    for item in sponsor['facts']:
        item = deepcopy(item); item['id'] = prefix + '-' + item['id']; evidence.append(item)
    by_id = {item['id'].removeprefix(prefix + '-'): item for item in evidence}
    outside = by_id.get('parcel-outside-footprints'); parcel = by_id.get('parcel-area')
    feasibility = (f"Mapped parcel has {outside['display']} outside returned building footprints. This is not verified available or permeable space."
                   if outside else 'Mapped parcel evidence is available; usable space and access still need checking.' if parcel
                   else 'A site-specific parcel and building check is needed before locating a treatment or changing access.')
    uses = sponsor['nearbyUses']
    disruption = ('Nearby CoStar uses include ' + ', '.join(uses) + '; preserve access and check affected properties.' if uses
                  else 'Affected property operations and access remain unverified.')
    operations = [by_id[key]['display'] for key in ('costar-reportedParkingSpaces', 'costar-reportedLoadingDocks') if key in by_id]
    if operations:
        disruption = 'Associated CoStar record reports ' + ' and '.join(operations) + '; inspect entrances and loading before reallocating space. Reported supply is not observed demand.'
    if sponsor['association'] not in ('matched', 'selected'):
        missing.append('Unambiguous property association; nearby records do not establish land control')
    if sponsor['vexcel'] != 'available': missing.append('Mapped parcel/building geometry')
    prop = sponsor['property']
    label = (prop.get('address') or prop.get('name')) if prop else None
    if not label: label = p.get('label') if workflow == 'street' else 'Terrain collection opportunity'
    if signal.get('evaluationLink'):
        label = signal['_intersectionLabel'] + ' · linked traffic opportunity'
    reason = ('One of the larger independent terrain-contribution signals in this search; investigate real drainage before claiming benefit.'
              if workflow == 'water' else 'One of the stronger independent slowdown signals in this search; design benefit remains unmeasured.')
    readiness_data = {'summary': readiness, 'missing': missing, 'sponsors': {'vexcel': sponsor['vexcel'], 'costar': sponsor['costar']}}
    candidate = {'id': prefix, 'label': label, 'center': signal['center'], 'geometry': signal['geometry'],
                 'propertyId': prop['id'] if prop else None, 'environmental': environmental, 'feasibility': feasibility, 'disruption': disruption,
                 'readiness': readiness_data, 'direction': direction, 'reason': reason, 'evidence': evidence, 'warnings': sponsor['warnings'],
                 'provenance': {'layer': layer['layer'], 'featureId': feature['id'], 'version': layer['version'], 'source': origin,
                                'method': layer['method'], 'limitations': source_note, 'association': sponsor['association'],
                                'groupedCandidateIds': signal['memberIds'], 'comparisonPolicy': POLICY, 'kind': 'opportunity'},
                 'expiresAt': expires if workflow == 'street' else None}
    if signal.get('evaluationLink'):
        candidate['provenance']['evaluationLink'] = deepcopy(signal['evaluationLink'])
    candidate['modelContext'] = {key: deepcopy(candidate[key]) for key in ('id', 'environmental', 'feasibility', 'disruption', 'readiness', 'direction', 'evidence')}
    return candidate


def research_candidates(workflow, bounds, exclude_ids=(), *, check=lambda: None, emit=lambda event: None):
    validate_area(workflow, bounds)
    if not isinstance(exclude_ids, (list, tuple, set)) or len(exclude_ids) > 150 or any(not isinstance(value, str) or len(value) > 100 for value in exclude_ids):
        raise ValueError('Invalid candidate history.')
    check(); data = map_discovery(workflow); check()
    signals, query = _signals(workflow, bounds, data)
    excluded = set(exclude_ids)
    available = [signal for signal in signals if not excluded.intersection(signal['memberIds'])]
    candidates = []; expires = data.get('flow_expires_epoch')
    for signal in available[:MAX_CHOICES]:
        check()
        emit({'type': 'scouting', 'message': 'Checking Vexcel geometry and CoStar context for a distinct opportunity.', 'candidateId': signal['id']})
        sponsor = _research_site(workflow, signal['center'], check)
        candidates.append(_candidate(workflow, signal, sponsor, expires))
    check(); warnings = []
    if query['coverage'] != 'inside_pilot':
        if workflow == 'street':
            warnings.append('Some of this area lacks detailed intersection data; current traffic can still identify places to investigate.')
        else:
            warnings.append('Terrain data covers only part of your selected area. Move or shrink the search to compare locations within the mapped terrain area.'
                            if query['coverage'] == 'partial_pilot' else
                            'Terrain data is not available in this area. Move the search into the mapped terrain area, or choose a site directly.')
    for layer in query['layers']:
        if layer.get('error'): warnings.append(layer['error'])
    truncated = any(layer['truncated'] for layer in query['layers'])
    if truncated:
        warnings.append('This search checked the strongest 50 mapped features in each relevant layer. Zoom into a smaller area to investigate more local options.')
    if not candidates:
        warnings.append('No additional locations could be confirmed in this area. Move the search area or choose a site on the map to investigate it directly.')
    methodology = ('Ordered by larger terrain-inferred contributing raster area within the same terrain method. '
                   if workflow == 'water' else 'Ordered by lower current speed relative to the provider free-flow reference. ')
    methodology += ('This is an environmental screening order, not a ranking of evaluated intervention benefits. '
                    'Feasibility and disruption remain explicit tradeoffs; equally strong signals are not given a numerical winner. '
                    'Data readiness never adds points. Nearby or overlapping signals are grouped before showing up to three choices. '
                    'Each search screens at most 50 source features per relevant layer and investigates at most three distinct locations; no detailed design is created.')
    bundle = {'candidates': candidates, 'coverage': query['coverage'], 'methodology': methodology,
            'exhausted': len(available) <= MAX_CHOICES, 'screenTruncated': truncated,
            'warnings': warnings, 'expiresAt': expires if workflow == 'street' else None, 'comparisonPolicy': POLICY,
            'screened': sum(len(layer['features']) for layer in query['layers']), 'distinct': len(signals), 'recommendedId': None}
    # Sponsor requests may outlast the traffic cache lifetime. Refresh once
    # before giving any scalar to the native agent; publication checks again.
    if workflow == 'street' and candidates and (expires is None or time.time() >= expires):
        bundle = refresh_traffic_candidates(bundle, bounds, check=check)
    return bundle


def refresh_traffic_candidates(bundle, bounds, *, check=lambda: None):
    """Rejoin to one current snapshot; callers discard narrative if reviewStale.

    Disappearing signals are removed, never replaced with a different location.
    """
    validate_area('street', bounds); check()
    data = map_discovery('street'); signals, _ = _signals('street', bounds, data)
    by_id = {signal['id']: signal for signal in signals}
    result = deepcopy(bundle); refreshed = []; changed = False
    for candidate in bundle['candidates']:
        signal = by_id.get(candidate['id'])
        if signal is None:
            changed = True; continue
        prefix = candidate['id'] + '-'
        refreshed_keys = {'signal', 'speed_kmh', 'free_flow_kmh', 'length_m', 'time_penalty_s', 'historical-demand-date'}
        facts = [deepcopy(item) for item in candidate['evidence']
                 if 'TomTom' not in json.dumps(item.get('source', {})) and item['id'].removeprefix(prefix) not in refreshed_keys]
        for item in facts: item['id'] = item['id'].removeprefix(prefix)
        sponsor = {'facts': facts, 'warnings': candidate['warnings'], 'vexcel': candidate['readiness']['sponsors']['vexcel'],
                   'costar': candidate['readiness']['sponsors']['costar'], 'association': candidate['provenance']['association'],
                   'property': {'id': candidate['propertyId'], 'address': candidate['label']} if candidate['propertyId'] else None,
                   'nearbyUses': [], 'nearbyCount': 0}
        updated = _candidate('street', signal, sponsor, data.get('flow_expires_epoch'))
        updated['disruption'] = candidate['disruption']; updated['modelContext']['disruption'] = candidate['disruption']
        # A provider can correct values without changing its snapshot version.
        # Never retain a review that cites the previous scalar values or extent.
        changed |= (updated['provenance']['version'] != candidate['provenance']['version']
                    or updated['geometry'] != candidate['geometry']
                    or [(f['id'], f['value']) for f in updated['evidence']] != [(f['id'], f['value']) for f in candidate['evidence']])
        refreshed.append(updated)
    refreshed.sort(key=lambda candidate: (candidate['environmental']['metrics'][0]['value'], candidate['id']))
    result['candidates'] = refreshed; result['expiresAt'] = data.get('flow_expires_epoch'); result['reviewStale'] = changed
    if changed: result['warnings'].append('Traffic changed during the search. The locations below use the latest available speeds.')
    check(); return result
