"""Bounded, memory-only TomTom Orbis v2 flow for the downtown pilot.

No historical feed archive, automatic polling, v4 enrichment, or emissions
inference. Map geometry and agent summaries use the same versioned snapshot.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from threading import Lock
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PILOT = (-118.268, 34.034, -118.219, 34.070)
ZOOM = 15
MAX_TILES = 30
SESSION_REQUEST_BUDGET = 256
DOC = 'https://docs.tomtom.com/traffic-api/documentation/tomtom-orbis-maps/v2/traffic-flow/vector-flow-tiles'
LIMITS = ('One current traffic estimate, not recurring congestion or measured emissions. '
          'Coverage includes returned surface streets only; an absent road is unknown. '
          'Per-segment confidence and observation time are not supplied. '
          'Free-flow speed is derived from absolute speed / relative speed; time penalty is a constant-speed screen over the displayed length, not a routing result.')
_lock = Lock()
_snapshot = None
_attempted_at = 0.0
_requests = 0
_roads = None


def utc(epoch=None):
    return datetime.fromtimestamp(time.time() if epoch is None else epoch, timezone.utc).isoformat(timespec='seconds')


def tiles_for(bounds):
    w, s, e, n = bounds
    def tile(lon, lat):
        return ((lon+180)/360*2**ZOOM, (1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**ZOOM)
    a, b = tile(w, n), tile(e, s)
    tiles = [(x, y) for x in range(math.floor(a[0]), math.ceil(b[0]))
             for y in range(math.floor(a[1]), math.ceil(b[1]))]
    if not tiles or len(tiles) > MAX_TILES:
        raise ValueError('Traffic area exceeds the bounded pilot request limit.')
    return tiles


def tile_coordinate(x, y, u, v, extent):
    lon = (x+u/extent)/2**ZOOM*360-180
    lat = math.degrees(math.atan(math.sinh(math.pi*(1-2*(y+v/extent)/2**ZOOM))))
    return lon, lat


def fetch_tile(x, y, key):
    attributes = 'tags(road_category,relative_speed,absolute_speed,part_of_two_way_road,road_closure,openlr),roadCategories(primary,secondary,tertiary,street)'
    url = f'https://api.tomtom.com/maps/orbis/traffic/flow/vector/tile/{ZOOM}/{x}/{y}?'+urlencode({'apiVersion':2,'attributes':attributes})
    request = Request(url, headers={'TomTom-Api-Key':key,'TomTom-Api-Version':'2','Accept':'application/vnd.mapbox-vector-tile'})
    try:
        with urlopen(request, timeout=12) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000 or response.headers.get_content_type() != 'application/vnd.mapbox-vector-tile':
                raise ValueError('TomTom returned an oversized or unexpected tile.')
            control = response.headers.get('Cache-Control', '')
            age = re.search(r'(?:^|[, ])max-age=(\d+)', control)
            ttl = min(60, int(age.group(1))) if age else 60
            if 'no-store' in control or ttl <= 0:
                raise ValueError('TomTom tile does not permit the short-lived cache required for inspection.')
            return {'tile':(x,y),'body':raw,'received':time.time(),'ttl':ttl,
                    'http_date':response.headers.get('Date'),
                    'data_ids':response.headers.get('TomTom-Traffic-Data-IDs')}
    except HTTPError as error:
        message = ('TomTom rejected the key or traffic entitlement.' if error.code in (401,403) else
                   'TomTom rate limit reached; wait before refreshing.' if error.code == 429 else
                   f'TomTom tile request failed ({error.code}).')
        raise ValueError(message) from None
    except (URLError, TimeoutError, OSError):
        raise ValueError('TomTom could not be reached; current flow is unavailable.') from None


def number(value, low, high):
    return not isinstance(value, bool) and isinstance(value, (int,float)) and math.isfinite(value) and low <= value <= high


def heading(a, b):
    return math.degrees(math.atan2(b[0]-a[0],b[1]-a[1])) % 360


def direction_check(line, code, project):
    """Check ordered LRP anchors against this line; never invent a reverse join.

    OpenLR conversion is not a full network dereference. Require two distinct
    anchors on the returned line in increasing order. Otherwise keep direction
    explicitly unresolved. Clipped tile fragments are checked after merging.
    """
    import openlr
    from shapely.geometry import Point
    try:
        location = openlr.binary_decode(code)
        if not isinstance(location, openlr.LineLocationReference):
            return False
        anchors = [Point(project(p.lon,p.lat)) for p in location.points]
        positions = [line.project(p) for p in anchors if line.distance(p) <= 12]
        if len(positions)>=2:
            return positions[-1]-positions[0]>=15 and all(b>=a for a,b in zip(positions,positions[1:]))
        # Partial tile geometry may contain only one reference anchor. Check
        # its local tangent against the encoded bearing (last LRP looks back).
        for index,point in enumerate(anchors):
            if line.distance(point)>12:continue
            position=line.project(point)
            last=index==len(anchors)-1
            start,end=(max(0,position-30),position) if last else (position,min(line.length,position+30))
            if end-start<20:continue
            actual=heading(line.interpolate(start).coords[0],line.interpolate(end).coords[0])
            expected=(location.points[index].bear+(180 if last else 0))%360
            if abs((actual-expected+180)%360-180)<=25:return True
        return False
    except (ValueError, TypeError, AttributeError, IndexError, OverflowError):
        return False


def named_roads():
    """Local OSM labels only; no nearest-road demand or simulation association."""
    global _roads
    if _roads is not None:
        return _roads
    from pyproj import Transformer
    from shapely.geometry import LineString
    from shapely.strtree import STRtree
    project = Transformer.from_crs(4326,26911,always_xy=True).transform
    path = Path(__file__).resolve().parent/'sim'/'dtla.net.xml'
    try:
        import sumolib
        net = sumolib.net.readNet(str(path))
        rows=[]
        for edge in net.getEdges():
            if edge.isSpecial() or not edge.getName() or not edge.allows('passenger'):
                continue
            line=LineString([project(*net.convertXY2LonLat(x,y)) for x,y in edge.getShape()])
            if line.length:
                rows.append((edge.getName(),line))
        _roads = (rows, STRtree([row[1] for row in rows]), sha256(path.read_bytes()).hexdigest())
    except (OSError, ValueError, ImportError):
        _roads = ([],None,None)
    return _roads


def road_label(line):
    rows, tree, _ = named_roads()
    if tree is None:
        return None
    points = [line.interpolate(fraction,normalized=True) for fraction in (.1,.3,.5,.7,.9)]
    votes={}
    for point in points:
        matches={rows[int(i)][0] for i in tree.query(point.buffer(16)) if rows[int(i)][1].distance(point)<=16}
        for name in matches:
            votes[name]=votes.get(name,0)+1
    winners=[name for name,count in votes.items() if count>=4]
    return winners[0] if len(winners)==1 else None


def decode_tiles(responses, bounds=PILOT):
    import mapbox_vector_tile
    from pyproj import Transformer
    from shapely.geometry import LineString, box, mapping
    from shapely.ops import transform, unary_union, linemerge
    project = Transformer.from_crs(4326,26911,always_xy=True).transform
    unproject = Transformer.from_crs(26911,4326,always_xy=True).transform
    boundary = transform(project, box(*bounds))
    groups={}; rejected=0; total=0
    for response in responses:
        x,y = response['tile']
        try:
            decoded = mapbox_vector_tile.decode(response['body'],default_options={'y_coord_down':True})
        except Exception:
            raise ValueError('TomTom returned an invalid vector tile.') from None
        layer = decoded.get('Traffic flow')
        if layer is None:
            if decoded:
                raise ValueError('Unexpected TomTom traffic layer.')
            continue
        extent=layer.get('extent')
        if not number(extent,256,65536) or layer.get('version')!=2:
            raise ValueError('Unsupported TomTom vector tile grid.')
        if len(layer['features'])>10000:
            raise ValueError('TomTom tile feature limit exceeded.')
        for feature in layer['features']:
            total+=1
            p=feature.get('properties',{}); g=feature.get('geometry',{})
            speed,ratio=p.get('absolute_speed'),p.get('relative_speed')
            code=p.get('openlr')
            if (not number(speed,0,250) or not number(ratio,0,1) or not isinstance(code,str) or not 4<len(code)<=4096
                    or g.get('type') not in ('LineString','MultiLineString')
                    or p.get('road_category') not in ('primary','secondary','tertiary','street')
                    or any(k in p and not isinstance(p[k],bool) for k in ('part_of_two_way_road','road_closure'))):
                rejected+=1;continue
            chains=[g['coordinates']] if g['type']=='LineString' else g['coordinates']
            for chain in chains:
                if (not 2<=len(chain)<=10000 or any(len(c)!=2 or not all(number(v,-extent,extent*2) for v in c) for c in chain)):
                    rejected+=1;continue
                line=LineString([project(*tile_coordinate(x,y,*c,extent)) for c in chain])
                if line.is_empty or line.length<1 or not line.is_valid:
                    rejected+=1;continue
                # Keep overlap margins while grouping; union removes duplicate
                # lengths. Direction is recovered only from the original chains
                # and independently checked against the ordered OpenLR anchors.
                key=(code,speed,ratio,p.get('road_closure',False),p.get('part_of_two_way_road',False),p['road_category'])
                groups.setdefault(key,[]).append(line)
    features=[]; conflicts=set()
    values={}
    for key in groups:
        values.setdefault(key[0],set()).add(key[1:])
    conflicts={code for code,variants in values.items() if len(variants)>1}
    for key,lines in groups.items():
        code,speed,ratio,closed,two_way,category=key
        if code in conflicts:
            rejected+=len(lines);continue
        union=unary_union(lines)
        merged=linemerge(union) if union.geom_type=='MultiLineString' else union
        complete=[merged] if merged.geom_type=='LineString' else list(merged.geoms)
        for whole in complete:
            if whole.geom_type!='LineString':continue
            # Union may reverse lines. Validate either orientation via OpenLR;
            # if both fail, expose orientation unknown and omit direction arrows.
            verified=direction_check(whole,code,project)
            if not verified:
                reversed_line=LineString(list(whole.coords)[::-1])
                if direction_check(reversed_line,code,project):whole=reversed_line;verified=True
            cut=whole.intersection(boundary)
            pieces=[cut] if cut.geom_type=='LineString' else list(getattr(cut,'geoms',[]))
            for line in pieces:
                if line.geom_type!='LineString' or line.length<10:continue
                if whole.project(line.interpolate(0))>whole.project(line.interpolate(line.length)):
                    line=LineString(list(line.coords)[::-1])
                compass=['N','NE','E','SE','S','SW','W','NW'][int((heading(line.coords[0],line.coords[-1])+22.5)//45)%8] if verified else None
                free = speed/ratio if speed>0 and ratio>0 and not closed else None
                current = line.length/speed*3.6 if speed>0 and not closed else None
                reference = line.length/free*3.6 if free else None
                name=road_label(line)
                center=unproject(*line.interpolate(.5,normalized=True).coords[0])
                geometry=mapping(transform(unproject,line))
                ident=sha256((code+json.dumps(geometry,sort_keys=True)).encode()).hexdigest()[:16]
                label=(name or category.capitalize()+' road')+(' · '+compass+'bound' if compass else ' · direction unresolved')
                detail={'speed_kmh':round(speed,1),'relative_speed':round(ratio,3),
                        'free_flow_kmh':round(free,1) if free else None,
                        'length_m':round(line.length,1),'travel_time_s':round(current,1) if current is not None else None,
                        'free_flow_time_s':round(reference,1) if reference is not None else None,
                        'time_penalty_s':round(max(0,current-reference),1) if current is not None and reference is not None else None,
                        'road_closure':closed,'two_way':two_way,'direction':compass,'direction_verified':verified,
                        'confidence':None,'observation_time':None,
                        'road_category':category,'road_name':name,'road_name_method':'OSM proximity label; not a traffic/simulation network join' if name else 'No unambiguous OSM label',
                        'speed_basis':'Provider current estimate; real-time versus historical mix not supplied',
                        'baseline':'Free flow derived from speed / relative speed; constant-speed estimate over this displayed portion only.'}
                features.append({'type':'Feature','id':'flow-'+ident,'geometry':geometry,
                                 'properties':{'label':label,'value':round(ratio*100,1),'center':list(center),'scalar_detail':detail}})
    features.sort(key=lambda f:(f['properties']['value'],f['id']))
    return features, {'tiles_decoded':len(responses),'input_features':total,'excluded_features':rejected,
                      'conflicting_flow_references':len(conflicts),'groups':len(features),
                      'direction_verified':sum(f['properties']['scalar_detail']['direction_verified'] for f in features),
                      'grouping':'Same OpenLR and flow values; overlapping geometry unioned. Disconnected portions remain separate.',
                      'osm_name_source_sha256':named_roads()[2]}


def group_approaches(features):
    """Connected slow portions on the same named road and checked direction.

    Keep source parts, omit inferred connectors and never add overlapping
    lengths twice. The result is a screening group, not a routable itinerary.
    """
    from pyproj import Transformer
    from shapely.geometry import shape, Point
    from shapely.ops import transform, unary_union
    project=Transformer.from_crs(4326,26911,always_xy=True).transform
    buckets={}
    for feature in features:
        p=feature['properties'];d=p['scalar_detail']
        if p['value']<90 and d['direction_verified'] and d['road_name'] and not d['road_closure']:
            buckets.setdefault((d['road_name'],d['direction']),[]).append(feature)
    groups=[]
    for (name,direction),members in buckets.items():
        lines=[transform(project,shape(f['geometry'])) for f in members]
        adjacent={i:set() for i in range(len(lines))}
        for i,line in enumerate(lines):
            for j in range(i):
                other=lines[j]
                if min(Point(line.coords[0]).distance(Point(other.coords[-1])),Point(line.coords[-1]).distance(Point(other.coords[0])))<=18:
                    adjacent[i].add(j);adjacent[j].add(i)
        unseen=set(adjacent)
        while unseen:
            component={min(unseen)};queue=list(component)
            for index in queue:
                for neighbor in sorted(adjacent[index]):
                    if neighbor not in component:component.add(neighbor);queue.append(neighbor)
            unseen-=component
            if len(component)<2 or any(len(adjacent[i])>2 for i in component):continue
            selected=[members[i] for i in sorted(component)]
            geometry=[members[i]['geometry']['coordinates'] for i in sorted(component)]
            total=sum(lines[i].length for i in component)
            if total>1500 or unary_union([lines[i] for i in component]).length<total*.98:continue
            details=[f['properties']['scalar_detail'] for f in selected]
            times=[d['travel_time_s'] for d in details];free=[d['free_flow_time_s'] for d in details]
            duration=sum(times) if all(v is not None for v in times) else None
            baseline=sum(free) if all(v is not None for v in free) else None
            center=selected[len(selected)//2]['properties']['center']
            identifiers=[f['id'] for f in selected]
            d={**details[0],'length_m':round(total,1),'speed_min_kmh':min(d['speed_kmh'] for d in details),
               'speed_max_kmh':max(d['speed_kmh'] for d in details),'member_count':len(selected),
               'travel_time_s':round(duration,1) if duration is not None else None,
               'free_flow_time_s':round(baseline,1) if baseline is not None else None,
               'time_penalty_s':round(max(0,duration-baseline),1) if duration is not None and baseline is not None else None,
               'baseline':'Sum of constant-speed times on the displayed source portions versus their derived free-flow times. Gaps are not routed or included.',
               'speed_kmh':round(total/duration*3.6,1) if duration else 0,
               'free_flow_kmh':round(total/baseline*3.6,1) if baseline else None}
            ratio=baseline/duration*100 if duration and baseline is not None else min(f['properties']['value'] for f in selected)
            groups.append({'type':'Feature','id':'approach-'+sha256('|'.join(identifiers).encode()).hexdigest()[:16],
                           'geometry':{'type':'MultiLineString','coordinates':geometry},
                           'properties':{'label':name+' · '+direction+'bound slow stretch','center':center,'value':round(ratio,1),
                                         'member_ids':identifiers,'scalar_detail':d,'summary':f'{len(selected)} connected slow source portions. Inspect this stretch as one opportunity; it does not establish a recurring queue or a redesign benefit.'}})
    return sorted(groups,key=lambda f:(f['properties']['value'],f['id']))


def empty_snapshot(message, status='unavailable'):
    return {'schema':1,'workflow':'street','version':'flow-unavailable','bbox':list(PILOT),
            'sources':{'tomtom':{'label':'TomTom Traffic · Orbis v2','url':DOC,'retrieved_at':None,'observed_at':None}},
            'layers':[{'id':'flow','label':'Current street flow','status':status,'error':message,'source':'tomtom',
                       'classification':'estimated','unit':'% of free-flow speed','period':'Current estimate unavailable',
                       'method':'Bounded Orbis v2 flow tiles.','limitations':LIMITS,'features':[]}],
            'audit':{'session_tile_requests':_requests,'session_tile_limit':SESSION_REQUEST_BUDGET}}


def get_snapshot():
    global _snapshot,_attempted_at,_requests
    with _lock:
        now=time.time()
        if _snapshot and now<_snapshot.get('expires_epoch',0):
            return deepcopy(_snapshot)
        if now-_attempted_at<60:
            return empty_snapshot('Refresh is available once a minute; no expired traffic is displayed.')
        key=os.getenv('TOMTOM_API_KEY','').strip()
        if not key:return empty_snapshot('Configure TOMTOM_API_KEY locally to show current street flow.')
        tiles=tiles_for(PILOT)
        if _requests+len(tiles)>SESSION_REQUEST_BUDGET:
            return empty_snapshot('The local session traffic request budget is exhausted. Historical counts remain available.')
        _attempted_at=now;_snapshot=None;_requests+=len(tiles)
        def fetch(tile):
            try:return fetch_tile(*tile,key),None
            except ValueError as error:return None,str(error)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results=list(executor.map(fetch,tiles))
        responses=[r for r,e in results if r is not None]; errors=[e for r,e in results if e]
        if not responses:return empty_snapshot(errors[0])
        try:
            features,audit=decode_tiles(responses)
        except (ValueError,TypeError,KeyError,IndexError,ImportError,OverflowError):
            return empty_snapshot('Traffic tiles could not be validated. Check the traffic dependencies and source schema.')
        expires=min(r['received']+r['ttl'] for r in responses)
        if time.time()>=expires:return empty_snapshot('Traffic expired during loading. Refresh to retrieve a current snapshot.')
        received=min(r['received'] for r in responses)
        data_ids=sorted({r['data_ids'] for r in responses if r['data_ids']})
        version='flow-'+sha256(json.dumps([received,data_ids,features],sort_keys=True).encode()).hexdigest()[:16]
        status='partial' if errors or audit['excluded_features'] else 'ready' if features else 'empty'
        layer={'id':'flow','version':version,'label':'Current street flow','status':status,'source':'tomtom',
               'classification':'estimated','unit':'% of free-flow speed','period':'Retrieved '+utc(received),
               'method':'Orbis v2 tiles decoded in Web Mercator; duplicate overlap removed within OpenLR groups. Direction checked against ordered OpenLR anchors.',
               'limitations':LIMITS,'features':features,'error':errors[0] if errors else None}
        approaches=group_approaches(features)
        grouped={**layer,'id':'approaches','label':'Connected slow approaches','features':approaches,
                 'status':status if approaches else 'empty','method':'Adjacent slow portions with one OSM proximity label and checked direction; no invented connector geometry. '+layer['method']}
        _snapshot={'schema':1,'workflow':'street','version':version,'bbox':list(PILOT),'expires_epoch':expires,'expires_at':utc(expires),
                   'sources':{'tomtom':{'label':'TomTom Traffic · Orbis v2','url':DOC,'retrieved_at':utc(received),
                              'observed_at':None,'data_ids':data_ids,'http_dates':sorted({r['http_date'] for r in responses if r['http_date']}),
                              'attribution':'© '+str(datetime.now(timezone.utc).year)+' TomTom'}},'layers':[layer,grouped],
                   'audit':{**audit,'approach_groups':len(approaches),'requested_tiles':len(tiles),'failed_tiles':len(errors),'session_tile_requests':_requests,
                            'session_tile_limit':SESSION_REQUEST_BUDGET,'storage':'Memory only; expires with provider cache lifetime, at most 60 seconds.'}}
        return deepcopy(_snapshot)


def resolve_snapshot(version):
    with _lock:
        if not _snapshot or version!=_snapshot['version'] or time.time()>=_snapshot['expires_epoch']:
            raise ValueError('Traffic snapshot expired or changed. Refresh traffic and select the feature again.')
        return deepcopy(_snapshot)
