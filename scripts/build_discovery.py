"""Build reproducible, real-source discovery snapshots. No agent/model calls.

Usage: .venv/bin/python scripts/build_discovery.py [--refresh]
Raw inputs and map artifacts stay in ignored private/discovery/. No private
sponsor data is downloaded by this script. See docs/CHECKPOINT_3.md for limits.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hydrology import county_features, rainfall_contours, rainfall_at, COUNTY_GIS, RAINFALL
from terrain_discovery import d8, path_from
from street_names import street_key

DATA = ROOT/'private'/'discovery'
LADOT = 'https://data.lacity.org/resource/94wu-3ps3.json'
LADOT_PAGE = 'https://data.lacity.org/Transportation/LADOT-Traffic-Counts-Summary/94wu-3ps3'
DEM = 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/CA_LosAngeles_B23/TIFF/USGS_1M_11_x37y378_CA_LosAngeles_B23.tif'
CATCHMENTS = f'{COUNTY_GIS}/PW_Open_Data/MapServer/47'
PILOT = (-118.3027721,34.0692538)
DTLA = [-118.268,34.034,-118.219,34.070]
NOW = datetime.now(timezone.utc).isoformat(timespec='seconds')


def cached_json(name, fetch, refresh):
    path=DATA/name
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    data=fetch(); path.write_text(json.dumps(data)); return data


def remote_json(url):
    with urlopen(url,timeout=30) as response:
        raw=response.read(10_000_001)
        if len(raw)>10_000_000:raise ValueError('Source response exceeded limit.')
        return json.loads(raw)


def input_provenance(path):
    # A rebuild must not make an older cached source look freshly retrieved.
    return {'retrieved_at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(timespec='seconds'),
            'input_sha256':sha256(path.read_bytes()).hexdigest()}


def longest_inside_path(route, contains):
    """Never bridge across a route that leaves and reenters the display area."""
    longest=[]; current=[]
    for index in route:
        if contains(index):
            current.append(index)
            if len(current)>len(longest):longest=current.copy()
        else:current=[]
    return longest


def save(workflow, bbox, sources, layers, audit):
    data=dict(schema=1,workflow=workflow,bbox=bbox,built_at=NOW,sources=sources,layers=layers,audit=audit)
    data['version']=sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()[:16]
    path=DATA/f'{workflow}.json'; temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,separators=(',',':'),allow_nan=False));temporary.replace(path)
    print(workflow,[(x['id'],x['status'],len(x['features'])) for x in layers],flush=True)
    return data


def count_records(records, intersections):
    """Keep reported automated AT-intersection counts; never split or scale."""
    latest={}; skipped={};
    def skip(reason):skipped[reason]=skipped.get(reason,0)+1
    for row in records:
        if row.get('type','').upper() not in ('AUTO','AUT'):
            skip('manual_or_unverified_type');continue
        if row.get('dir','').strip().upper()!='AT':skip('offset_location');continue
        primary,cross=street_key(row.get('primary_street','')),street_key(row.get('cross_street',''))
        points=intersections.get(tuple(sorted((primary,cross))),[])
        if not points:skip('no_network_match');continue
        if any(math.dist(points[0][:2],p[:2])>60 for p in points):skip('ambiguous_match');continue
        try:
            total=float(row['total']);date=datetime.fromisoformat(row['count_date']).date().isoformat()
            if not math.isfinite(total) or total<0 or not total.is_integer():raise ValueError('Invalid count')
        except (KeyError,TypeError,ValueError):skip('invalid_count');continue
        key=(primary,cross)
        if key not in latest or date>latest[key][0]:latest[key]=(date,row,points,total)
    features=[]
    for (primary,cross),(date,row,points,total) in sorted(latest.items()):
        # Equivalent junction nodes within 60m are consolidated; this is an OSM
        # location match, not a source-provided count-station coordinate.
        point=sorted(points,key=lambda p:p[4])[0]
        lon,lat=point[2:4]
        identifier='count-'+sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()[:12]
        directional={}
        for key in ('w_b','e_b','n_b','s_b'):
            try:
                value=float(row[key])
                if math.isfinite(value) and value>=0 and value.is_integer():directional[key]=int(value)
            except (KeyError,ValueError,TypeError):pass
        features.append({'type':'Feature','id':identifier,'geometry':{'type':'Point','coordinates':[lon,lat]},'properties':{
            'label':f"{row['primary_street']} at {row['cross_street']}",'value':int(total),'period':date,
            'center':[lon,lat], 'source_record':row, 'network_node':point[4],
            'scalar_detail':{'count_type':row['type'],'directional_reported_counts':directional,'interval':'Not specified in source metadata; not converted to an hourly or daily rate.'}}})
    return features,skipped


def turning_records(records, intersections):
    """Latest manual turning-movement sheet per intersection that downloads and passes its checks."""
    from traffic_counts import SheetError, find_sheet, peak_hour
    candidates={}; skipped={}
    def skip(reason):skipped[reason]=skipped.get(reason,0)+1
    for row in records:
        if row.get('type','').strip().upper()!='MAN':continue
        if row.get('dir','').strip().upper()!='AT':skip('offset_location');continue
        primary,cross=street_key(row.get('primary_street','')),street_key(row.get('cross_street',''))
        pair=tuple(sorted((primary,cross)))
        points=intersections.get(pair,[])
        if not points:skip('no_network_match');continue
        if any(math.dist(points[0][:2],p[:2])>60 for p in points):skip('ambiguous_match');continue
        if 'shift' in (row.get('cross_street','')+row.get('primary_street','')).lower():skip('split_shift_record');continue
        try:date=datetime.fromisoformat(row['count_date']).date().isoformat()
        except (KeyError,ValueError):skip('invalid_date');continue
        candidates.setdefault(pair,[]).append((date,row,points))
    from concurrent.futures import ThreadPoolExecutor
    def newest_valid(rows):
        # Two newest records per intersection; older sheets are not searched.
        for date,row,points in sorted(rows,key=lambda r:r[0],reverse=True)[:2]:
            try:return row,points,find_sheet(row['primary_street'],row['cross_street'],row['count_date'],'MAN',DATA/'sheets')
            except SheetError:continue
        return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        found=list(pool.map(newest_valid,[candidates[k] for k in sorted(candidates)]))
    features=[]; sheets={}
    for result in found:
        if result is None:skip('sheet_unpublished_or_failed_checks');continue
        row,points,sheet=result
        if True:
            point=sorted(points,key=lambda p:p[4])[0];lon,lat=point[2:4]
            identifier='turning-'+sha256(sheet['sha256'].encode()).hexdigest()[:12]
            peaks={period:peak_hour(sheet,period) for period in ('am','pm')}
            approach_totals={period:{a:sum(v[hour].values()) for a,v in sheet['approaches'].items()} for period,hour in peaks.items()}
            total=sum(approach_totals['pm'].values())
            sheets[identifier]=sheet
            features.append({'type':'Feature','id':identifier,'geometry':{'type':'Point','coordinates':[lon,lat]},'properties':{
                'label':f"{sheet['north_south'].title()} at {sheet['east_west'].title()}",'value':total,'period':sheet['date'],
                'center':[lon,lat],'network_node':point[4],'sheet_url':sheet['url'],'sheet_sha256':sheet['sha256'],
                'scalar_detail':{'count_type':'MAN','peak_hours':{'am':peaks['am'],'pm':peaks['pm']},
                    'peak_hour_approach_vehicles':approach_totals,
                    'interval':'Peak hour within the counted 7-10 AM and 3-6 PM windows; turning movements are on the linked official sheet.'}}})
    return features,skipped,sheets


def build_traffic(refresh=False):
    import sumolib
    from itertools import combinations
    layer=dict(id='counts',label='Dated automated counts',status='ready',classification='reported',unit='automated detections · count duration unknown',
        period='2011–2016 · source count dates',source='ladot',
        method='Latest automated AT-intersection record per primary/cross street matched to local OSM junction names. No demand extrapolation, direction splitting or time conversion.',
        limitations='Historical reported totals, not current traffic. Count duration is not documented; these are not vehicles/hour. Manual and unverified count types are excluded. Locations are approximate OSM matches, not surveyed count stations.',features=[])
    sources={'ladot':{'label':'LADOT Traffic Counts Summary','url':LADOT_PAGE,'retrieved_at':NOW,'observed_at':None},
             'osm':{'label':'OpenStreetMap topology','url':'https://www.openstreetmap.org/copyright','retrieved_at':None,'observed_at':None}}
    audit={}
    try:
        metadata=cached_json('ladot-metadata.json',lambda:remote_json('https://data.lacity.org/api/views/94wu-3ps3.json'),refresh)
        records=cached_json('ladot-records.json',lambda:remote_json(LADOT+'?'+urlencode({'$limit':6000})),refresh)
        if not isinstance(records,list) or len(records)>=6000:raise ValueError('Incomplete traffic extract; paginate before using it.')
        sources['ladot']['description']=metadata.get('description');sources['ladot']['license']=metadata.get('licenseId')
        sources['ladot']['dataset_updated']=datetime.fromtimestamp(metadata['rowsUpdatedAt'],timezone.utc).isoformat()
        sources['ladot'].update(input_provenance(DATA/'ladot-records.json'))
        netpath=ROOT/'sim'/'dtla.net.xml'; net=sumolib.net.readNet(str(netpath))
        sources['osm']['input_sha256']=sha256(netpath.read_bytes()).hexdigest()
        intersections={}
        for node in net.getNodes():
            x,y=node.getCoord();lon,lat=net.convertXY2LonLat(x,y)
            if not(DTLA[0]<=lon<=DTLA[2] and DTLA[1]<=lat<=DTLA[3]):continue
            names={street_key(e.getName()) for e in node.getIncoming()+node.getOutgoing() if not e.isSpecial() and e.allows('passenger') and e.getName()}
            for pair in combinations(sorted(names),2):intersections.setdefault(pair,[]).append((x,y,lon,lat,node.getID()))
        layer['features'],skipped=count_records(records,intersections)
        audit={'source_records':len(records),'skipped':skipped,'manual_counts_excluded':True,'no_hourly_scaling':True}
        if not layer['features']:raise ValueError('No unambiguous automated count matches in the pilot.')
    except (OSError,ValueError,KeyError) as e:
        layer.update(status='unavailable',error=str(e),features=[])
    turning=dict(id='turning',label='Turning-movement counts',status='ready',classification='reported',unit='vehicles in the PM peak hour',
        period='2011–2016 · counted 7–10 AM and 3–6 PM',source='ladot_sheets',
        method='Official LADOT manual count summaries downloaded from NavigateLA. Each sheet is accepted only when its left/through/right counts reproduce every printed row and column total. The map value is all approaches in the busiest counted PM hour.',
        limitations='Historical counts on the sheet date, not current traffic. Signal timing is not on the sheet. Locations are OSM junction matches, not surveyed stations.',features=[])
    sources['ladot_sheets']={'label':'LADOT manual traffic count summaries (NavigateLA)','url':'https://navigatela.lacity.org/','retrieved_at':NOW,'observed_at':None}
    try:
        turning['features'],turn_skipped,sheets=turning_records(records,intersections)
        (DATA/'turning-sheets.json').write_text(json.dumps(sheets))
        audit['turning_skipped']=turn_skipped
        if not turning['features']:turning.update(status='empty')
    except (OSError,ValueError,KeyError,NameError) as e:
        turning.update(status='unavailable',error=str(e),features=[])
    return save('street',DTLA,sources,[layer,turning],audit)


def build_water(refresh=False, sponsors=False):
    from water_discovery import build_water as expanded_water
    return expanded_water(DATA, refresh=refresh, sponsors=sponsors)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--workflow',choices=('street','water','both'),default='both')
    parser.add_argument('--sponsors',action='store_true',help='Fetch the three bounded Vexcel site samples for water discovery.')
    args=parser.parse_args()
    DATA.mkdir(parents=True,exist_ok=True)
    if args.workflow in ('street','both'):build_traffic(args.refresh)
    if args.workflow in ('water','both'):build_water(args.refresh,args.sponsors)
