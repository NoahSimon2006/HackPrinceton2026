"""Local, conditional storage screening of planner-drawn water treatments.

No infiltration, drain routing, field suitability or actual existing retention is
inferred. Numeric outputs require explicitly confirmed planner inputs and both
sponsors' evidence. Raw geometry and confirmation text never enter model facts.
"""
from hashlib import sha256
import json
import math

from pyproj import Transformer
from shapely import transform, unary_union
from shapely.geometry import Point, mapping

from hydrology import RAINFALL
from proposal import comparison_fingerprint, from_water_comparison
from site_measurements import PROJECT, fact, projected, source
from stormwater_terrain import terrain_screen

METHOD_URL = 'https://www.epa.gov/system/files/documents/2023-11/bioretentiondesignhandbook_plainnov2023.pdf'
METHOD = ('Event water balance, storage-only screening: external runoff = rainfall × unioned contributing area × planner runoff coefficient; '
          'direct rainfall = rainfall × treatment area; gross storage = treatment area × planner storage depth; '
          'external capture = min(external runoff, max(gross storage − direct rainfall, 0)); external excess = external runoff − external capture. '
          'Direct excess = max(direct rainfall − gross storage, 0). No infiltration or routing credit.')
CONFIRMATIONS = ('surface_confirmed', 'connections_confirmed', 'access_confirmed', 'overflow_confirmed')
KEYS = {'storage_depth_m', 'runoff_coefficient', 'confirmation_note', *CONFIRMATIONS}
RESULT_KEYS = ('runoff_m3', 'captured_m3', 'excess_m3', 'capacity_m3', 'direct_rain_m3', 'direct_excess_m3', 'footprint_m2')
INVERSE = Transformer.from_crs(32611, 4326, always_xy=True)


def validate_water_design(value, workflow):
    if value is None:
        return None
    if workflow != 'water' or not isinstance(value, dict) or set(value) != KEYS:
        raise ValueError('Stormwater comparison needs explicit depth, runoff coefficient, four confirmations and a source/confirmation note.')
    for key in ('storage_depth_m', 'runoff_coefficient'):
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 < number <= 1:
            raise ValueError(f'{key} must be a finite number greater than zero and at most one.')
    if any(type(value[key]) is not bool for key in CONFIRMATIONS):
        raise ValueError('Stormwater confirmations must be true or false.')
    note = value['confirmation_note']
    if not isinstance(note, str) or not 1 <= len(note.strip()) <= 600:
        raise ValueError('Provide a source/confirmation note of 1–600 characters.')
    return {**value, 'confirmation_note': note.strip()}


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _display_feature(geometry, role, layout=None):
    return {'type': 'Feature', 'geometry': mapping(transform(geometry, INVERSE.transform, interleaved=False)),
            'properties': {'role': role, **({'layout': layout} if layout else {})}}


def event_storage(rain_depth_m, treatment_area_m2, storage_depth_m, external_runoff_m3):
    """Reserve capacity for direct rain before screening external runoff storage."""
    capacity = treatment_area_m2 * storage_depth_m
    direct = rain_depth_m * treatment_area_m2 if rain_depth_m is not None else None
    capture = min(external_runoff_m3, max(capacity - direct, 0.)) if None not in (direct, external_runoff_m3) else None
    return dict(runoff_m3=external_runoff_m3, captured_m3=capture,
                excess_m3=external_runoff_m3 - capture if capture is not None else None,
                capacity_m3=capacity, direct_rain_m3=direct,
                direct_excess_m3=max(direct - capacity, 0.) if direct is not None else None,
                footprint_m2=treatment_area_m2)


def compare_water(*, lon, lat, markings, design, hydrology, scenario, outlines,
                  property_details, frontages, source_status, identity):
    design = validate_water_design(design, 'water')
    site_id, revision, input_revision = identity['site_id'], identity['revision'], identity['input_revision']
    reasons = []
    if not design:
        reasons.append('Enter storage depth, runoff coefficient and the four site confirmations before comparing.')
    elif not all(design[key] for key in CONFIRMATIONS):
        reasons.append('Confirm the contributing surface, drainage connections, access preservation and overflow destination before comparing.')
    if source_status.get('outlines') != 'ready': reasons.append('Usable Vexcel parcel/building evidence is required.')
    if source_status.get('property') != 'ready' or not isinstance(property_details, dict) or not property_details.get('propertyType'):
        reasons.append('Select a CoStar property with reported use and access context before comparing.')
    origin = source('Local storage screening', METHOD_URL)
    sources = [{'provider': 'EPA Bioretention Design Handbook — design reference; local simplified event balance', 'url': METHOD_URL}]
    point = Point(*PROJECT.transform(lon, lat))
    parcels, buildings = [], []
    try:
        for feature in outlines:
            props = feature['properties']; label = props.get('label')
            if label not in ('Parcel boundary', 'Building footprint'): continue
            geom = projected(feature['geometry'], ('Polygon', 'MultiPolygon'))
            if not point.buffer(5000).covers(geom): raise ValueError('Out-of-scope outline')
            if label == 'Parcel boundary' and geom.covers(point): parcels.append(geom)
            if label == 'Building footprint': buildings.append(geom)
            sources.append({'provider': 'Vexcel parcel extraction', 'url': 'https://api.vexcelgroup.com/v2/property/extract',
                            'observed_at': props.get('date'), 'collection': props.get('collection'), 'feature_id': props.get('evidenceId')})
        if len(parcels) != 1 or not buildings:
            raise ValueError('Need a unique containing parcel and mapped buildings')
        parcel, building = parcels[0], unary_union(buildings)
        if parcel.intersection(building).area <= 0: raise ValueError('No parcel building coverage')
    except (ValueError, TypeError, KeyError):
        parcel = building = None
        reasons.append('A unique containing parcel and usable mapped building footprints are required; absence is not zero overlap.')
    sources.append({'provider': 'CoStar local property kit', 'observed_at': None,
                    'fields': {key: property_details.get(key) for key in ('propertyType', 'units', 'reportedParkingSpaces', 'reportedLoadingDocks')}
                    if isinstance(property_details, dict) else {}})
    estimate = (hydrology or {}).get('estimate')
    rain = None
    try:
        raw = scenario if scenario is not None else estimate
        inches = raw['inches']
        if isinstance(inches, bool) or not isinstance(inches, (int, float)) or not math.isfinite(inches) or not 0 <= inches <= 100:
            raise ValueError('Invalid rainfall')
        if scenario is None:
            if source_status.get('hydrology') != 'ready' or estimate.get('method') not in ('on_contour', 'interpolated'):
                raise ValueError('County rainfall unavailable')
            rain = {'inches': inches, 'label': 'County 85th-percentile, 24-hour rainfall', 'basis': 'estimated', 'source': RAINFALL,
                    'depth_range': estimate.get('depth_range'), 'method': estimate['method']}
        else:
            if not isinstance(scenario.get('source'), str) or not scenario['source'].strip(): raise ValueError('Missing rainfall source')
            rain = {'inches': inches, 'label': 'Planner rainfall scenario', 'basis': 'user_provided', 'source': scenario['source']}
    except (ValueError, TypeError, KeyError, AttributeError):
        reasons.append('A valid sourced county rainfall depth or explicitly labeled planner rainfall is required.')
    if rain: sources.append({'provider': rain['label'], 'url': RAINFALL if scenario is None else None, 'basis': rain['basis']})
    drainage, treatments, access = [], [], []
    try:
        for marking in markings:
            geom = projected(marking['geometry'], ('Polygon',))
            if not point.buffer(1000).covers(geom): raise ValueError('Marking beyond site')
            if marking['kind'] == 'drainage': drainage.append(geom)
            elif marking['kind'] == 'treatment': treatments.append(geom)
            elif marking['kind'] == 'access': access.append(geom)
            else: raise ValueError('Wrong marking kind')
        if not drainage or len(treatments) not in (2, 3): raise ValueError('Mark contributing area and two or three treatments')
        if any(a.equals(b) for i, a in enumerate(treatments) for b in treatments[i+1:]): raise ValueError('Duplicate treatments')
    except (ValueError, TypeError, KeyError):
        reasons.append('Draw a contributing surface and two or three distinct treatment polygons within this site.')
    contributing = unary_union(drainage) if drainage else None
    if contributing is not None and parcel is not None and not parcel.covers(contributing):
        reasons.append('Contributing surfaces must be within the selected parcel; off-parcel drainage is not supported.')
    keep_clear = unary_union(access)
    frontage_lines, frontage_status = [], 'unassessed'
    if frontages:
        try:
            for frontage in frontages:
                cuts = frontage.get('curbCuts')
                if isinstance(cuts, bool) or not isinstance(cuts, (int, float)) or not math.isfinite(cuts) or cuts < 0 or cuts != int(cuts):
                    raise ValueError('Unusable reported curb-cut count')
                line = projected(frontage['geometry'], ('LineString',))
                if not point.buffer(1000).covers(line): raise ValueError('Out-of-scope frontage')
                frontage_lines.append((line, cuts))
            frontage_status = 'checked'
        except (ValueError, TypeError, KeyError, AttributeError):
            frontage_status = 'unavailable'
            frontage_lines = []
            reasons.append('Some supplied CoStar frontages or reported curb-cut counts could not be assessed; access is not cleared.')
    assumptions = [
        'Conditional screening of planner-drawn placements; the confirmations and coefficient are planner inputs, not field verification by the app.',
        'Depth is uniform available surface storage above a flat treatment bottom. No media void storage, infiltration, drain-out or permanent removal credit.',
        'Direct rainfall fills storage before external runoff in this conservative event-volume balance; no time routing or flow-rate feasibility is modeled.',
        'The baseline is a no-added-treatment reference with zero added capture, not measured existing retention or current flood volume.',
        'Confirm grades, soils, utilities, setbacks, physical access and overflow conveyance in the field before design or construction.',
        'Bare-earth terrain paths and county subbasins do not verify parcel drainage connections; confirmations remain planner supplied.',
        'Missing CoStar frontage geometry leaves frontage access unassessed; explicit planner access confirmation is still required. Reported parking/loading counts do not locate operations.',
    ]
    results = {'baseline': dict.fromkeys(RESULT_KEYS)}
    checks, geometries, verdicts = {}, {}, {}
    common_ready = not reasons
    runoff = rain['inches'] * .0254 * contributing.area * design['runoff_coefficient'] if common_ready else None
    if common_ready:
        results['baseline'] = dict(runoff_m3=runoff, captured_m3=0., excess_m3=runoff, capacity_m3=0., direct_rain_m3=0., direct_excess_m3=0., footprint_m2=0.)
    for index, geom in enumerate(treatments, 1):
        name = f'treatment-{index}'
        geometries[name] = _display_feature(geom, 'proposed', name)
        invalid = list(reasons)
        check = {'footprint_m2': geom.area, 'outside_parcel_m2': None, 'building_overlap_m2': None,
                 'access_overlap_m2': geom.intersection(keep_clear).area, 'drainage_overlap_m2': geom.intersection(contributing).area if contributing is not None else None}
        check.update(frontage_status=frontage_status, frontage_conflicts=sum(1 for line,cuts in frontage_lines if cuts > 0 and geom.intersects(line)) if frontage_status == 'checked' else None)
        if check['frontage_conflicts']:
            invalid.append('Treatment directly intersects a mapped CoStar frontage with reported curb cuts; resolve access before recommendation.')
        if parcel is not None:
            check.update(outside_parcel_m2=geom.difference(parcel).area, building_overlap_m2=geom.intersection(building).area)
        for key, label in [('outside_parcel_m2', 'Treatment extends outside the selected parcel'), ('building_overlap_m2', 'Treatment overlaps mapped buildings'),
                           ('access_overlap_m2', 'Treatment overlaps a keep-clear area'), ('drainage_overlap_m2', 'Treatment overlaps the external contributing surface')]:
            if check[key] is not None and check[key] > 1e-6: invalid.append(label + '.')
        checks[name] = check
        result = dict.fromkeys(RESULT_KEYS)
        if not invalid:
            result = event_storage(rain['inches'] * .0254, geom.area, design['storage_depth_m'], runoff)
            if result['captured_m3'] <= 0: invalid.append('No external runoff storage is available under this rainfall and depth.')
        terrain = terrain_screen(geometries[name]['geometry'])
        check['terrain'] = terrain
        if terrain.get('status') != 'ready': invalid.append('Terrain slope screening is unavailable for this placement.')
        results[name] = result
        verdicts[name] = {'eligible': not invalid, 'ineligible_reasons': invalid}
    eligible = [name for name in verdicts if verdicts[name]['eligible']]
    recommended = min(eligible, key=lambda name: (-results[name]['captured_m3'], results[name]['footprint_m2'], name)) if eligible else None
    # Raw inputs affect revision identity but are not repeated in model facts or the comparison.
    digest = _digest(dict(lon=lon, lat=lat, markings=markings, design=design, hydrology=hydrology,
                          scenario=scenario, outlines=outlines, property_details=property_details,
                          frontages=frontages, source_status=source_status))
    comparison = dict(status='ready' if common_ready else 'unavailable', results=results, checks=checks, geometry=geometries,
                      contributing_geometry=_display_feature(contributing, 'contributing') if contributing is not None else None,
                      ranking={'recommended': recommended, 'reason': 'Conditional best storage screening option; not construction feasibility.' if recommended else
                               '; '.join(reasons) or 'No treatment passes geometry and storage checks.', 'verdicts': verdicts},
                      rainfall=rain, design={k:design[k] for k in ('storage_depth_m', 'runoff_coefficient')} if design else None,
                      assumptions=assumptions, sources=sources, method=METHOD, input_digest=digest,
                      contributing_area_m2=contributing.area if contributing is not None else None, missing_inputs=reasons,
                      confirmations={key: design[key] for key in (*CONFIRMATIONS, 'confirmation_note')} if design else None)
    fingerprint = comparison_fingerprint(comparison, site_id=site_id, revision=revision, input_revision=input_revision)
    comparison.update(site_id=site_id, workflow='water', revision=revision, input_revision=input_revision, input_hash=fingerprint)
    proposal = from_water_comparison(comparison, recommended, site_id=site_id, revision=revision, input_revision=input_revision).model_dump(mode='json') if recommended else None
    facts = [fact('water-status', 'Stormwater storage comparison', 'Conditional screening available' if common_ready else 'Unassessed: required site inputs are incomplete', '', origin,
                  basis='modeled' if common_ready else 'availability', method=METHOD,
                  note='Planner confirmations are not app-verified site conditions. No infiltration or flood reduction established.')]
    costar_origin = source('CoStar local property kit')
    facts.append(fact('water-frontage-status', 'CoStar frontage access check', frontage_status, '', costar_origin, basis='availability',
                      method='Validate supplied frontage geometry and reported curb-cut counts; check direct intersection only, without an assumed setback.',
                      note='Missing frontage geometry is unassessed, not zero conflicts. Planner access confirmation does not override a known direct conflict.'))
    if isinstance(property_details, dict):
        for key, label, unit in [('reportedParkingSpaces', 'Reported parking operations to preserve', 'spaces'), ('reportedLoadingDocks', 'Reported loading operations to preserve', 'docks')]:
            value = property_details.get(key)
            if isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value) and value >= 0:
                facts.append(fact(f'water-costar-{key}', label, value, unit, costar_origin, basis='reported',
                                  method='Reported selected-property snapshot; observation date unavailable.',
                                  note='Counts do not establish their mapped locations or available treatment land. Preserve operations through planner-confirmed access and keep-clear areas.'))
    for name, verdict in verdicts.items():
        facts.append(fact(f'water-{name}-verdict', f'{name} screening verdict',
                          'Conditional preferred option' if name == recommended else 'Eligible alternative' if verdict['eligible'] else 'Not eligible', '', origin,
                          basis='modeled', method='Rank by external runoff captured, then smaller footprint.',
                          note='Conditional screening only; not independently verified engineering feasibility. ' + '; '.join(verdict['ineligible_reasons'])))
    for name, check in checks.items():
        if check['frontage_conflicts'] is not None:
            facts.append(fact(f'water-{name}-frontage-conflicts', f'{name} reported curb-cut frontage conflicts', check['frontage_conflicts'], 'frontages', costar_origin,
                              basis='measured', method='Direct intersection with sourced frontage lines reporting one or more curb cuts; no arbitrary buffer.',
                              note='The line identifies frontage context, not surveyed driveway edges; a direct conflict blocks screening recommendation.'))
        terrain = check['terrain']
        if terrain.get('status') == 'ready':
            terrain_source = dict(terrain.get('source') or {})
            terrain_source.setdefault('observed_at', None)
            terrain_source['retrieved_at'] = terrain_source.get('retrieved_at') or origin['retrieved_at']
            for key, label, unit in [('median_slope_percent', 'median bare-earth slope', '%'), ('max_slope_percent', 'maximum bare-earth slope', '%'), ('relief_m', 'bare-earth elevation range', 'm')]:
                value = terrain.get(key)
                if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
                    facts.append(fact(f'water-{name}-{key}', f'{name} {label}', value, unit, terrain_source, basis='estimated',
                                      method='Local sampling of the sourced bare-earth raster over the drawn treatment.',
                                      note='Topographic screening only; not treatment bottom grade, verified drainage, curb or inlet elevations.'))
    if common_ready:
        facts.extend([fact('water-contributing-area', 'Unioned planner contributing surface', contributing.area, 'm²', origin, basis='user_marked',
                           method='Union of planner drainage polygons measured locally in UTM 11N; overlapping areas counted once.'),
                      fact('water-rainfall', 'Comparison rainfall', rain['inches'], 'in', source('Planner rainfall scenario' if scenario is not None else 'LA County rainfall contours', None if scenario is not None else RAINFALL), basis='assumption' if scenario is not None else 'estimated',
                           method='Planner rainfall scenario' if scenario is not None else 'County 85th-percentile, 24-hour contour estimate.')])
        for name, result in results.items():
            for key, value in result.items():
                if value is None: continue
                facts.append(fact(f'water-{name}-{key}', f'{name} {key.replace("_", " ")}', value, 'm²' if key == 'footprint_m2' else 'm³', origin,
                                  basis='modeled', method=METHOD, note='Conditional storage-only screening; baseline is zero added treatment, not measured existing retention.'))
        facts.extend([fact('water-depth', 'Planner storage depth', design['storage_depth_m'], 'm', origin, basis='assumption', method='Explicit planner design input.', precision=None),
                      fact('water-coefficient', 'Planner runoff coefficient', design['runoff_coefficient'], '', origin, basis='assumption', method='Explicit planner surface input.', precision=None)])
    return {'comparison': comparison, 'proposal': proposal, 'facts': facts, 'warnings': reasons}
