"""Bounded local stormwater concepts; geometry and property records stay local."""
from copy import deepcopy
from hashlib import sha256
import json
import math
from pyproj import Transformer
from shapely import maximum_inscribed_circle, transform, unary_union
from shapely.affinity import rotate
from shapely.geometry import Point, box, mapping
from shapely.ops import nearest_points
from proposal import Design, EvidenceReference, Finding, GeometryFeature, Metric, Proposal
from site_measurements import PROJECT, fact, number, projected, source
from stormwater import event_storage

DISPLAY = Transformer.from_crs(32611, 4326, always_xy=True)
POLICY = 'stormwater-screen-v1'
MAX_HOST_DISTANCE, MIN_AREA = 75, 2


def _parts(g):
    if g.is_empty: return []
    if g.geom_type == 'Polygon': return [g]
    return [p for child in getattr(g, 'geoms', ()) for p in _parts(child)]


def _settings(value):
    result = {'storageDepthM': .15, 'targetAreaM2': 40., 'layout': 'compact',
              'placement': 'near_selection', 'runoffCoefficient': None,
              'drainageAssumption': 'unknown', 'protectAccess': False, **deepcopy(value or {})}
    for key, low, high in (('storageDepthM', .05, .30), ('targetAreaM2', 2, 500)):
        if number(result[key], maximum=high) < low: raise ValueError('Stormwater design input outside screening limits.')
    if result['runoffCoefficient'] is not None: number(result['runoffCoefficient'], maximum=1)
    if (result['layout'] not in ('compact', 'linear') or result['placement'] not in ('near_selection', 'landscape_first', 'away_from_previous')
        or result['drainageAssumption'] not in ('unknown', 'marked_connected') or not isinstance(result['protectAccess'], bool)):
        raise ValueError('Invalid stormwater concept settings.')
    return result


def _catalog_context(host, contains, context):
    context = context or {}
    records = context.get('hostProperties', context.get('nearby', []))
    matches = []
    for item in records:
        try:
            if host.covers(Point(*PROJECT.transform(item['lon'], item['lat']))): matches.append(item)
        except (KeyError, TypeError, ValueError): continue
    if len(matches) == 1:
        return matches[0].get('details') or {}, [matches[0].get('type', 'Unknown')], 1
    if len(matches) > 1:
        return {}, sorted({p.get('type', 'Unknown') for p in matches}), len(matches)
    if contains and context.get('selected'):
        details = context['selected']
        return details, [details.get('propertyType', 'Unknown')], 1
    return {}, [], 0


def _empty(question, settings, decisions=()):
    return {'proposal':None,'alternatives':{},'comparison':{'status':'needs_input','policy':POLICY,'selected':None,'results':[],
        'selectionBasis':'No valid footprint under the mapped constraints.'},'facts':[],'question':question,'decisions':list(decisions),'settings':settings}


def _anchors(area, point):
    anchors = []
    for part in sorted(_parts(area), key=lambda p:(-p.area,p.centroid.x,p.centroid.y))[:5]:
        if part.area < MIN_AREA: continue
        axis = maximum_inscribed_circle(part,tolerance=.1)
        center = part.representative_point(); near = nearest_points(part,point)[0]
        anchors.extend([Point(axis.coords[0]),center,part.centroid,Point((near.x+center.x)/2,(near.y+center.y)/2)])
        a,b,c,d = part.bounds
        for x in (1,2,3):
            for y in (1,2,3):
                p=Point(a+(c-a)*x/4,b+(d-b)*y/4)
                if part.covers(p): anchors.append(p)
    return list({(round(p.x,3),round(p.y,3)):p for p in anchors}.values())[:50]


def _template(anchor, target, kind, angle):
    if kind == 'compact': return anchor.buffer(math.sqrt(target/Point(0,0).buffer(1,quad_segs=16).area),quad_segs=16)
    width = min(4.,max(1.5,math.sqrt(target)/3)); length = target/width
    return rotate(box(anchor.x-length/2,anchor.y-width/2,anchor.x+length/2,anchor.y+width/2),angle,origin=anchor)


def _orientation(parcel):
    coords=list(parcel.minimum_rotated_rectangle.exterior.coords)
    _,a,b=max((math.hypot(b[0]-a[0],b[1]-a[1]),a,b) for a,b in zip(coords,coords[1:]))
    return math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))


def _parcels(outlines, point):
    groups=[]
    for props,g in outlines:
        if props.get('label')!='Parcel boundary' or g.distance(point)>MAX_HOST_DISTANCE: continue
        for group in groups:
            common=group[1].intersection(g); union=group[1].union(g)
            if union.area and common.area/union.area >= .98:
                group[1]=common
                group[0]['evidenceIds'].append(props['evidenceId'])
                group[0]['reconciled']=True
                if props.get('buildingCoverage') is False: group[0]['buildingCoverage']=False
                break
        else:
            groups.append([{**props,'evidenceIds':[props['evidenceId']]},g])
    return groups


def plan_stormwater(*,lon,lat,evidence,markings,rainfall,scenario,settings,identity,previous=None,property_context=None):
    settings=_settings(settings); point=Point(*PROJECT.transform(lon,lat)); outlines=[]
    for i,item in enumerate(evidence.get('outlines',[]),1):
        props={**item['properties']};props.setdefault('evidenceId',f'outline-{i}')
        outlines.append((props,projected(item['geometry'])))
    parcels=_parcels(outlines,point); containing=[(p,g) for p,g in parcels if g.covers(point)]
    if len(containing)>1: return _empty('Which of the overlapping mapped parcels should host this concept? Select an unambiguous location.',settings)
    hosts=containing or sorted(parcels,key=lambda item:(item[1].distance(point),item[0]['evidenceId']))[:3]
    if not hosts: return _empty('Can you select a mapped parcel near this opportunity so the concept has a bounded host?',settings)
    hosts=[(p,g) for p,g in hosts if p.get('buildingCoverage') is not False and (p.get('buildingCoverage') is True or
           any(bp.get('label')=='Building footprint' and bg.intersects(g) for bp,bg in outlines))]
    if not hosts: return _empty('Can you choose a host parcel with complete mapped building coverage so the concept can avoid structures?',settings)
    zones={kind:unary_union([projected(m['geometry']) for m in markings if m['kind']==kind]) for kind in ('access','treatment','drainage')}
    detections=[]
    for i,item in enumerate(evidence.get('detections',[]),1):
        props={**item['properties']};props.setdefault('evidenceId',f'candidate-{i}');detections.append((props,projected(item['geometry'])))
    frontages=[]
    for i,item in enumerate(evidence.get('frontages',[]),1):
        if (item.get('curbCuts') or 0)>0:
            frontages.append(({**item,'evidenceId':item.get('evidenceId',f'frontage-{i}')},projected(item['geometry'])))
    previous_shape=None
    try:
        previous_geometries=[projected(f['geometry']) for f in (previous or {}).get('geometry',[]) if f['id'] in (previous or {}).get('proposed_geometry_ids',[])]
        if previous_geometries: previous_shape=unary_union(previous_geometries)
    except (KeyError,TypeError,ValueError): pass
    rain= scenario if scenario is not None else rainfall
    rain_m=number(rain['inches'],maximum=100)*.0254 if rain else None
    rain_id='scenario-rainfall' if scenario is not None else 'county-rainfall'; coefficient=settings['runoffCoefficient']
    drainage_area=zones['drainage'].area
    connected=settings['drainageAssumption']=='marked_connected' and drainage_area>0 and coefficient is not None
    runoff=rain_m*drainage_area*coefficient if connected and rain_m is not None else None
    name=(scenario or {}).get('source') or ('County 85th-percentile 24-hour screening event' if rainfall else 'Rainfall unavailable')
    scenario_info={'name':name,'rainfallInches':rain.get('inches') if rain else None,'drainageAssumption':settings['drainageAssumption'],
        'runoffCoefficient':coefficient,'contributingAreaM2':round(drainage_area,3) if drainage_area else None,
        'captureStatus':'explicit_what_if' if runoff is not None else 'unknown','storageDepthM':settings['storageDepthM']}
    candidates=[];rejected=[];contexts=[];unavailable_hosts=[]
    for host_i,(parcel_props,parcel) in enumerate(hosts,1):
        buildings=[(p,g) for p,g in outlines if p.get('label')=='Building footprint' and g.intersects(parcel)]
        building_shape=unary_union([g for _,g in buildings]); cues=[(p,g) for p,g in detections if g.intersects(parcel)]
        access=[(p,g) for p,g in cues if p.get('label')=='Driveway entrance'];parking=[(p,g) for p,g in cues if p.get('label')=='Parking lot']
        landscape=unary_union([g for p,g in cues if p.get('label')=='Landscaped strip'])
        frontage=[(p,g) for p,g in frontages if g.distance(parcel)<=3]
        marked_access_here = not zones['access'].is_empty and zones['access'].intersection(parcel).area > 1e-6
        if settings['protectAccess'] and not (marked_access_here or access or frontage):
            unavailable_hosts.append({'id':f'host-{host_i}', 'reason':'Requested access protection has no mapped entrance, relevant curb-cut frontage or keep-clear marking on this host. Another host’s access evidence cannot locate this host’s entrance.', 'evidence_ids':parcel_props['evidenceIds']})
            continue
        details,uses,record_count=_catalog_context(parcel,bool(containing),property_context)
        circulation=2. if uses==['Multifamily'] else 1.
        parking_margin=1. if (details.get('reportedParkingSpaces') or 0)>0 else 0.
        loading_margin=2. if (details.get('reportedLoadingDocks') or 0)>0 else 0.
        fixed=unary_union([building_shape.buffer(circulation),zones['access'],zones['drainage'],*[g.buffer(loading_margin) for _,g in access],*[g.buffer(parking_margin) for _,g in parking]])
        frontage_protection=unary_union([g.buffer(3) for _,g in frontage]);protected=unary_union([fixed,frontage_protection])
        base=parcel.buffer(-.5).intersection(point.buffer(MAX_HOST_DISTANCE)).difference(fixed)
        available=base.difference(frontage_protection)
        if not zones['treatment'].is_empty:
            available=available.intersection(zones['treatment']);base=base.intersection(zones['treatment'])
        elif buildings or not landscape.is_empty:
            positive=unary_union([building_shape.buffer(12),landscape]);available=available.intersection(positive);base=base.intersection(positive)
        outline_ids=[*parcel_props['evidenceIds'],*[p['evidenceId'] for p,_ in buildings]]
        refs=[EvidenceReference(id=i,source='Vexcel mapped outlines',classification='observed') for i in outline_ids]
        refs += [EvidenceReference(id=p['evidenceId'],source='Vexcel candidate box',classification='modeled') for p,_ in cues]
        refs += [EvidenceReference(id=p['evidenceId'],source='CoStar reported frontage and curb cuts',classification='reported') for p,_ in frontage]
        refs += [EvidenceReference(id=f'marking-{i}',source='Planner map marking',classification='user_provided') for i,_ in enumerate(markings,1)]
        if rain:refs.append(EvidenceReference(id=rain_id,source='Planner rainfall scenario' if scenario is not None else 'LA County rainfall contours',classification='user_provided' if scenario is not None else 'modeled'))
        decisions=[{'source':'Vexcel mapped outlines','decision':f'Fit the footprint inside the mapped host and outside building footprints with a proposed {circulation:g} m screening margin.','evidence_ids':outline_ids}]
        if parcel_props.get('reconciled'):
            decisions.append({'source':'Vexcel mapped outlines','decision':'Use the conservative intersection of nearly coincident returned parcel boundaries. Boundary and legal parcel identity remain unverified.','evidence_ids':parcel_props['evidenceIds']})
        if record_count:
            use_id=f'water-host-{host_i}-costar-use';refs.append(EvidenceReference(id=use_id,source='CoStar local property kit',classification='reported'))
            decisions.append({'source':'CoStar local property kit','decision':
                f"{record_count} CoStar record(s) inside the host report {', '.join(uses)} use. " +
                ('Use a proposed 2 m circulation band around mapped buildings to preserve room to investigate residential access; no entrance location, resident count or required setback is inferred.' if uses==['Multifamily'] else 'Check operating access before detailed design; no entrance location or ownership is inferred.'),
                'evidence_ids':[use_id,*[p['evidenceId'] for p,_ in buildings]]})
        if frontage:
            decisions.append({'source':'CoStar reported frontage and curb cuts','decision':'Exclude a proposed 3 m screening corridor around reported frontage with curb cuts; this preserves a possible access route but does not locate individual entrances.','evidence_ids':[p['evidenceId'] for p,_ in frontage]})
        for field,label,cue,margin in [('reportedParkingSpaces','parking',parking,parking_margin),('reportedLoadingDocks','loading',access,loading_margin)]:
            if details.get(field) is not None:
                ref=f'water-host-{host_i}-costar-{field}';refs.append(EvidenceReference(id=ref,source='CoStar reported '+label,classification='reported'))
                decisions.append({'source':'CoStar local property kit','decision':f'Reported {label} keeps mapped operational cues protected'+(f' with a proposed {margin:g} m screening margin.' if cue and margin else '; unlocated entrances still require verification.'),'evidence_ids':[ref,*[p['evidenceId'] for p,_ in cue]]})
        if not record_count and not frontage:
            decisions.append({'source':'CoStar local property kit','decision':'No host operational match or relevant curb-cut frontage is available. Verify affected property access before detailed design.','evidence_ids':[]})
        if not zones['access'].is_empty:
            decisions.append({'source':'Planner map marking','decision':'Exclude the exact keep-clear marking from every eligible footprint.','evidence_ids':[f'marking-{i}' for i,m in enumerate(markings,1) if m['kind']=='access']})
        ctx={'parcel':parcel,'props':parcel_props,'outlineIds':outline_ids,'buildings':buildings,'landscape':landscape,'access':access,'parking':parking,'frontage':frontage,
             'details':details,'uses':uses,'recordCount':record_count,'refs':list({r.id:r for r in refs}.values()),'decisions':decisions,'provisional':not bool(containing),
             'distance':parcel.distance(point),'host':host_i,'available':available}
        contexts.append(ctx)
        if available.area<MIN_AREA:continue
        angle=_orientation(parcel)
        for anchor in _anchors(available,point):
            for bearing in ([angle,angle+90] if settings['layout']=='linear' else [angle]):
                ideal=_template(anchor,settings['targetAreaM2'],settings['layout'],bearing)
                for part in _parts(ideal.intersection(available)):
                    if part.area<MIN_AREA-1e-6 or not part.is_valid or not available.buffer(.0001).covers(part):continue
                    if maximum_inscribed_circle(part,tolerance=.05).length < .5:continue
                    volumes=event_storage(rain_m,part.area,settings['storageDepthM'],runoff)
                    share=part.intersection(landscape).area/part.area if not landscape.is_empty else 0.
                    distance=point.distance(part);relocation=part.distance(previous_shape) if previous_shape is not None else 0.
                    placement=(-share,distance) if settings['placement']=='landscape_first' else (-relocation,distance) if settings['placement']=='away_from_previous' else (distance,-share)
                    # Millilitre precision prevents floating-point geometry noise
                    # from silently outranking the practical placement criteria.
                    primary=-round(volumes['captured_m3'],3) if volumes['captured_m3'] is not None else 0.
                    rank=(primary,round(abs(settings['targetAreaM2']-part.area),3),*placement,ctx['provisional'],host_i,round(anchor.x,3),round(anchor.y,3))
                    candidates.append({'geometry':part,'ctx':ctx,'volumes':volumes,'rank':rank})
        if frontage:
            for anchor in _anchors(base,point):
                portions=_parts(_template(anchor,settings['targetAreaM2'],settings['layout'],angle).intersection(base))
                if portions:
                    part=max(portions,key=lambda p:p.area)
                    if part.area>=MIN_AREA and part.intersection(frontage_protection).area>.1:
                        rejected.append({'geometry':part,'ctx':ctx,'volumes':event_storage(rain_m,part.area,settings['storageDepthM'],runoff),
                            'reason':'Rejected: overlaps the screening corridor around CoStar frontage with reported curb cuts.'});break
    selected=[]
    for item in sorted(candidates,key=lambda c:c['rank']):
        if all(item['geometry'].intersection(old['geometry']).area/min(item['geometry'].area,old['geometry'].area)<.85 for old in selected):selected.append(item)
        if len(selected)==3:break
    if not selected and not rejected:
        question = ('Can you outline the driveway or loading entrance on a candidate host parcel? No host has access evidence for the requested protection.' if unavailable_hosts and not contexts else 'Is there another treatment area outside the mapped buildings, access and runoff-source markings?')
        result = _empty(question,settings,[d for c in contexts for d in c['decisions']])
        result['comparison']['unavailableHosts'] = unavailable_hosts
        return result
    alternatives={};rows=[];facts=[];chosen=None
    for i,item in enumerate([*selected,*rejected[:2]],1):
        key=f'water-option-{i}';g=item['geometry'];ctx=item['ctx'];v=item['volumes'];rejection=item.get('reason')
        label=('Linear planting strip' if settings['layout']=='linear' else 'Compact rain garden')+(' · alternate '+str(i) if i>1 else '')
        values=[('footprint_area','m²',g.area,'Exact footprint area in UTM 11N.'),
            ('storage_volume','m³',v['capacity_m3'],'Exact area × proposed effective ponding depth; no infiltration or routing modeled.'),
            ('direct_rain_volume','m³',v['direct_rain_m3'],'Named event depth × exact footprint area.'),
            ('runoff_volume','m³',runoff,'Named event depth × union of marked surfaces × explicit scenario coefficient.'),
            ('captured_volume','m³',v['captured_m3'],'Temporary external runoff storage after reserving capacity for direct rain.'),
            ('overflow_volume','m³',v['excess_m3'],'External runoff beyond available ponding storage; overflow route unverified.'),
            ('direct_overflow_volume','m³',v['direct_excess_m3'],'Direct rainfall exceeding gross ponding storage.'),
            ('contributing_area','m²',drainage_area if drainage_area else None,'Union of marked potential source areas; hydraulic connection remains assumed.')]
        geo=mapping(transform(g,DISPLAY.transform,interleaved=False))
        fingerprint=sha256(json.dumps({'identity':identity,'geometry':geo,'settings':settings,'scenario':scenario_info,'markings':markings,'sourceEvidence':evidence,'hostOperations':{'details':ctx['details'],'uses':ctx['uses'],'recordCount':ctx['recordCount']},'decisions':ctx['decisions'],'rejection':rejection},sort_keys=True,allow_nan=False).encode()).hexdigest()
        assumptions=['Concept only: verify land cover, utilities, infiltration, grade, setbacks, overflow routing and land permission.',
            f"Scenario: {name}. Effective ponding depth {settings['storageDepthM']:g} m. Proposed margins are screening choices, not surveyed or required setbacks.",
            'Direct rain occupies storage before external runoff. No permanent retention, infiltration, flood protection or water-quality improvement is calculated.',
            'Vexcel detection boxes are unconfirmed cues. Avoiding them does not prove all access and structures are mapped.',
            f"Requested area {settings['targetAreaM2']:g} m²; fitted footprint {g.area:.3f} m² after mapped exclusions. Eligible concepts must fit at least a 1 m wide internal circle; this is a screening choice, not an engineering standard."]
        if ctx['provisional']:assumptions.append(f"Provisional nearby host parcel, {ctx['distance']:.1f} m from the selected opportunity. The selected site is unchanged; host association, ownership, access and drainage connection remain unverified.")
        if ctx['props'].get('reconciled'):assumptions.append('Nearly coincident source parcel outlines were reconciled by conservative intersection; legal parcel identity and boundary accuracy remain unverified.')
        assumptions.append(f'Explicit what-if: the union of {drainage_area:.3f} m² of marked surfaces is assumed connected to this bed, with runoff coefficient {coefficient:g}. This is not verified drainage or measured capture.' if runoff is not None else
            'External runoff capture is unknown. It requires marked source areas, explicit connection and coefficient assumptions, and an event depth. A roof or terrain accumulation does not establish connectivity.')
        if rejection:assumptions.append(rejection)
        access_ids=[p['evidenceId'] for p,_ in [*ctx['access'],*ctx['parking'],*ctx['frontage']]]+[f'marking-{j}' for j,m in enumerate(markings,1) if m['kind']=='access']
        statement='Rejected internal alternative. '+rejection if rejection else label+' fitted to mapped constraints'+(' in a provisional nearby host parcel.' if ctx['provisional'] else ' inside the mapped parcel.')+(' Temporary runoff storage is an explicit what-if under the named event.' if runoff is not None else ' Drainage connection and external runoff capture remain unassessed.')
        proposal=Proposal(**identity,workflow='water',input_hash=fingerprint,development_fixture=False,status='conditional',design=Design(kind='bioretention',storage_depth_m=settings['storageDepthM']),evidence=ctx['refs'],
            geometry=[GeometryFeature(id=key,geometry=geo,properties={'revision':identity['revision'],'role':'proposed','alternative':key,'eligible':not bool(rejection),'layout':settings['layout']})],existing_geometry_ids=[],proposed_geometry_ids=[key],assumptions=assumptions,recommendation=statement,
            metrics=[Metric(id=k,unit=u,baseline=None,proposed=round(n,3) if n is not None else None,status='calculated' if n is not None else 'unassessed',revision=identity['revision'],input_hash=fingerprint,method=m) for k,u,n,m in values],
            access=Finding(status='unassessed' if rejection or not access_ids else 'checked',evidence_ids=access_ids,text=rejection or ('Avoids mapped access and parking constraints used here; verify unlocated entrances on site.' if access_ids else 'Access is unverified; no entrance position has been inferred.')),
            overlap=Finding(status='checked',evidence_ids=ctx['outlineIds'],text='Inside the mapped host and outside returned building footprints. Host permission and unmapped structures remain unverified.'))
        alternatives[key]=proposal.model_dump();rows.append({'id':key,'label':label,'status':'rejected' if rejection else 'eligible','reason':rejection or ('Preferred provisional fit under the stated policy.' if i==1 else 'Alternative footprint under the same mapped constraints.'),
            'metrics':{m.id:m.proposed for m in proposal.metrics},'inputHash':fingerprint,'revision':identity['revision'],'decisions':deepcopy(ctx['decisions']),'provisionalHost':ctx['provisional']})
        if i==1 and not rejection:
            chosen=proposal
            for k,u,n,m in values:
                if n is not None:facts.append(fact('water-'+k,k.replace('_',' ').capitalize(),round(n,3),u,source('Local stormwater screening'),basis='modeled',method=m,note='Explicit what-if; hydraulic connection unverified.' if runoff is not None else 'Concept; external runoff capture unassessed.',precision=3))
            facts.append(fact('water-draft','Mapped stormwater concept',statement,'',source('Local stormwater screening'),basis='modeled',feature_ids=[key]))
            facts.append(fact('water-target-area','Requested concept footprint area',settings['targetAreaM2'],'m²',source('Planner and agent concept settings'),basis='assumption',method='Requested size, not an observed available area. Actual footprint is measured separately.',precision=3))
            facts.append(fact('water-storage-depth','Proposed effective ponding depth',settings['storageDepthM'],'m',source('Planner and agent concept settings'),basis='assumption',method='Explicit concept setting used in footprint area × effective depth; not a measured site depth.',precision=None))
            facts.append(fact('water-host-distance','Distance from selected opportunity to mapped host parcel',round(ctx['distance'],1),'m',source('Local stormwater screening'),basis='measured',method='Planar shortest distance from the selected point to the mapped host polygon in UTM 11N.',note='Provisional nearby host; association, ownership and drainage connection are unverified.' if ctx['provisional'] else 'The selected point lies inside this mapped host; ownership and drainage connection remain unverified.',precision=1))
            if settings['drainageAssumption']=='marked_connected' and coefficient is not None:
                facts.append(fact('water-runoff-coefficient','Explicit what-if runoff coefficient',coefficient,'',source('Planner scenario'),basis='assumption',method='Planner-authorized coefficient for marked surfaces assumed connected to the concept; not a measured runoff response.',precision=None))
            facts.append(fact('water-layout-placement','Concept layout and placement preference',settings['layout']+'; '+settings['placement'],'',source('Planner and agent concept settings'),basis='assumption',method='Requested shape and placement preference used within mapped constraints; not an observed site characteristic.'))
            for j,decision in enumerate(ctx['decisions'],1):
                # Do not mutate source decisions after computing the input hash.
                facts.append(fact(f'water-siting-{j}','Source-informed siting decision',decision['decision'],'',source(decision['source']),basis='modeled',method='Local constraint check; margins are proposed screening assumptions.',feature_ids=decision['evidence_ids']))
            if ctx['recordCount']:
                facts.append(fact('water-host-costar-use','CoStar records inside host by use',f"{ctx['recordCount']} record(s): {', '.join(ctx['uses'])}",'',source('CoStar local property kit'),basis='reported',method='Local point-in-polygon association. Multiple records do not establish one property, ownership or occupancy.'))
            for field,unit in [('reportedParkingSpaces','spaces'),('reportedLoadingDocks','docks')]:
                if ctx['details'].get(field) is not None:facts.append(fact('water-host-costar-'+field,'Host reported '+field,ctx['details'][field],unit,source('CoStar local property kit'),basis='reported',method='Unique spatial match; not proof of ownership or current demand.'))
    selection='Compare temporary external runoff storage under the same explicit event and marked-area assumptions first; then fit the requested size and placement within mapped constraints.' if runoff is not None else 'External runoff benefit is unknown. Choose a provisional footprint that fits the requested size and placement; this is not a ranking of environmental benefits.'
    decisions=[{**d,'fact_id':f'water-siting-{i}'} for i,d in enumerate((selected or rejected)[0]['ctx']['decisions'],1)]
    return {'proposal':chosen,'alternatives':alternatives,'comparison':{'status':'screened' if chosen else 'needs_input','policy':POLICY,'selected':'water-option-1' if chosen else None,'selectionBasis':selection,'scenario':scenario_info,'results':rows,'unavailableHosts':unavailable_hosts,
        'readiness':'Geometry is mapped; hydraulic connectivity, field access and detailed engineering still need verification.'},'facts':facts,'question':None if chosen else 'The inspected footprints conflict with mapped access. Can you mark another possible treatment area?', 'decisions':decisions,'settings':settings}
