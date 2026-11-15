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
    layer=dict(id='counts',label='Historical traffic counts',status='ready',classification='reported',unit='vehicles reported',
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


def download_terrain(refresh=False):
    import rasterio
    from rasterio.windows import from_bounds
    from pyproj import Transformer
    path=DATA/'kipling-dem.tif'
    if path.exists() and not refresh:return path
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',GDAL_HTTP_TIMEOUT='30',GDAL_HTTP_MAX_RETRY='1'):
        with rasterio.open(DEM) as src:
            if src.res!=(1.,1.) or src.crs.to_epsg()!=26911:raise ValueError('Unexpected terrain grid; inspect before routing.')
            x,y=Transformer.from_crs(4326,src.crs,always_xy=True).transform(*PILOT)
            window=from_bounds(x-200,y-200,x+200,y+200,src.transform).round_offsets().round_lengths()
            data=src.read(1,window=window,masked=True)
            if data.shape!=(400,400) or data.count()!=data.size:raise ValueError('Pilot DEM window is incomplete.')
            profile=src.profile.copy();profile.update(width=400,height=400,transform=src.window_transform(window),compress='deflate')
            with rasterio.open(path,'w',**profile) as out:out.write(data.filled(src.nodata),1)
            (DATA/'terrain-source.json').write_text(json.dumps({'url':DEM,'crs':str(src.crs),'resolution_m':list(src.res),'window':list(window.flatten()),'bounds':list(rasterio.windows.bounds(window,src.transform)),'publication_date':'2025-08-11','product':'USGS 1 Meter 11 x37y378 CA_LosAngeles_B23'}))
    return path


def build_water(refresh=False):
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from shapely.geometry import shape,box,mapping,Point
    from shapely import transform
    def shape_transform(fn, geometry):return transform(geometry,fn,interleaved=False)
    source={'dem':{'label':'USGS 3DEP · 1 m bare-earth DEM','url':DEM,'retrieved_at':NOW,'observed_at':None,'published_at':'2025-08-11','vertical_datum':'NAVD88, meters','product':'USGS 1 Meter 11 x37y378 CA_LosAngeles_B23'},
            'rainfall':{'label':'LA County rainfall contours','url':RAINFALL,'retrieved_at':NOW,'observed_at':None},
            'catchments':{'label':'LA County storm-drain study catchments','url':CATCHMENTS,'retrieved_at':NOW,'observed_at':None}}
    limits='Bare-earth screening only: buildings, curb cuts and drains are not routed. Flats/pits remain unresolved; no sink filling. Window-limited contributing area is not runoff volume, flood depth or a verified drainage area. Small elevation differences may be within DEM error.'
    terrain=dict(id='terrain',label='Terrain paths & collection candidates',status='ready',classification='derived',unit='m² of raster area',period='USGS product published 2025-08-11 · acquisition date unverified',source='dem',
                 method='D8 steepest strictly downhill neighbor on the native 1m grid. Accumulate one square meter per valid cell; stop at flats/pits. Display inner 240m area with an 80m context buffer.',limitations=limits,features=[])
    rain=dict(id='rainfall',label='Design rainfall',status='ready',classification='estimated',unit='inches',period='85th-percentile · 24-hour',source='rainfall',method='County contour interpolation at 30m display-cell centers. Cell geometry is a display grid, not source resolution.',limitations='Design rainfall depth, not a forecast, rainfall intensity or flood depth. Contour date unavailable.',features=[])
    catch=dict(id='catchments',label='County drainage context',status='ready',classification='reported',unit='mapped catchment',period='County hydrology study compilation · date unavailable',source='catchments',method='County catchment polygons clipped to the discovery pilot for display.',limitations='Regional storm-drain study context; not a parcel flow boundary. No inlet-level connection is verified.',features=[])
    to_geo=Transformer.from_crs(26911,4326,always_xy=True);to_xy=Transformer.from_crs(4326,26911,always_xy=True)
    x,y=to_xy.transform(*PILOT);study=box(x-120,y-120,x+120,y+120)
    boundary=shape_transform(to_geo.transform,study);bbox=list(boundary.bounds);audit={}
    try:
        raw=cached_json('county-catchments.json',lambda:county_features(CATCHMENTS,','.join(map(str,bbox)),'esriGeometryEnvelope','AREA_NAME,OUTFALL_ID'),refresh)
        source['catchments'].update(input_provenance(DATA/'county-catchments.json'))
        for i,f in enumerate(raw):
            clipped=shape(f['geometry']).intersection(boundary)
            if clipped.is_empty:continue
            center=clipped.representative_point()
            catch['features'].append({'type':'Feature','id':f'catchment-{i+1}','geometry':mapping(clipped),'properties':{'label':f['properties']['AREA_NAME'],'value':f['properties']['AREA_NAME'],'center':[center.x,center.y],'scalar_detail':{'outfall_reference':f['properties'].get('OUTFALL_ID'),'scope':'Mapped regional context, not an inferred parcel connection.'}}})
        if not catch['features']:catch.update(status='empty')
    except (OSError,ValueError,KeyError) as e:catch.update(status='unavailable',error=str(e),features=[])
    try:
        contours=cached_json('county-rainfall.json',lambda:rainfall_contours(tuple(bbox)),refresh)
        source['rainfall'].update(input_provenance(DATA/'county-rainfall.json'))
        for row in range(8):
            for col in range(8):
                cell=box(x-120+col*30,y-120+row*30,x-90+col*30,y-90+row*30)
                center=to_geo.transform(cell.centroid.x,cell.centroid.y)
                estimate=rainfall_at(*center,contours)
                if estimate is None:continue
                rain['features'].append({'type':'Feature','id':f'rain-{row}-{col}','geometry':mapping(shape_transform(to_geo.transform,cell)),
                    'properties':{'label':'County design rainfall','value':estimate['inches'],'center':list(center),'scalar_detail':{'interpolation':estimate['method'],'bracketing_contours_in':estimate['depth_range']}}})
        if not rain['features']:rain.update(status='empty')
    except (OSError,ValueError,KeyError) as e:rain.update(status='unavailable',error=str(e),features=[])
    try:
        path=download_terrain(refresh)
        source['dem'].update(input_provenance(path))
        with rasterio.open(path) as src:
            if src.res!=(1.,1.) or src.crs.to_epsg()!=26911:raise ValueError('Unexpected raster grid.')
            z=src.read(1,masked=True).filled(np.nan).astype(float);affine=src.transform
        if not np.isfinite(z).all():raise ValueError('Terrain has NoData; inspect coverage before routing.')
        target,area,edge,slope=d8(z)
        h,w=z.shape
        def xy(i):return affine*(i%w+.5,i//w+.5)
        def coord(i):return list(to_geo.transform(*xy(i)))
        def interior(i):return study.contains(Point(*xy(i)))
        def county(i):
            point=Point(*coord(i))
            matches=[f['properties']['AREA_NAME'] for f in (raw if catch['status']=='ready' else []) if shape(f['geometry']).covers(point)]
            return ', '.join(sorted(set(matches))) or 'No covering county catchment returned'
        # Select high-contributing-area paths, then avoid repeating shared cells.
        candidates=np.argsort(area,axis=None)[::-1];used=set();paths=[];sinks=[]
        for index in candidates:
            index=int(index)
            if area.flat[index]<100:break
            if not interior(index):continue
            if target.flat[index]<0:
                if len(sinks)<16 and all(math.dist(xy(index),xy(j))>=12 for j in sinks):sinks.append(index)
                continue
            if index in used or len(paths)>=32:continue
            # Follow upstream through its strongest contributing neighbor to
            # show an actual contiguous path instead of a one-cell arrow.
            head=index
            for _ in range(80):
                r,c=divmod(head,w)
                upstream=[rr*w+cc for rr in range(max(0,r-1),min(h,r+2)) for cc in range(max(0,c-1),min(w,c+2)) if target[rr,cc]==head and area[rr,cc]>=25]
                if not upstream:break
                head=max(upstream,key=lambda j:area.flat[j])
            route=path_from(head,target)
            route=longest_inside_path(route,interior)
            if len(route)<6 or z.flat[route[0]]-z.flat[route[-1]]<.2:continue
            if sum(i in used for i in route)>len(route)*.4:continue
            used.update(route);paths.append(route)
        for n,route in enumerate(paths):
            first,last=route[0],route[-1];length=sum(math.dist(xy(a),xy(b)) for a,b in zip(route,route[1:]))
            terrain['features'].append({'type':'Feature','id':f'flow-{n+1}','geometry':{'type':'LineString','coordinates':[coord(i) for i in route]},'properties':{
                'label':'Inferred downhill terrain path','kind':'flow','value':round(float(area.flat[last]),1),'center':coord(route[len(route)//2]),
                'scalar_detail':{'upstream_elevation_m':round(float(z.flat[first]),3),'downstream_elevation_m':round(float(z.flat[last]),3),'drop_m':round(float(z.flat[first]-z.flat[last]),3),'path_length_m':round(length,2),'window_edge_contribution':bool(edge.flat[last]),'county_context':county(last)},
                'grid_reference':{'start_row_col':list(divmod(first,w)),'end_row_col':list(divmod(last,w))}}})
        for n,i in enumerate(sinks):
            terrain['features'].append({'type':'Feature','id':f'collection-{n+1}','geometry':{'type':'Point','coordinates':coord(i)},'properties':{'label':'Unresolved collection candidate','kind':'collection','value':round(float(area.flat[i]),1),'center':coord(i),'scalar_detail':{'elevation_m':round(float(z.flat[i]),3),'window_edge_contribution':bool(edge.flat[i]),'county_context':county(i),'classification':'DEM sink or flat; drainage and ponding are unverified.'},'grid_reference':{'row_col':list(divmod(i,w))}}})
        audit={'raster_cells':int(z.size),'valid_cells':int(np.isfinite(z).sum()),'raster_range_m':[float(z.min()),float(z.max())],'grid_crs':'EPSG:26911','grid_resolution_m':1,'context_m':400,'display_m':240,'threshold_area_m2':100,'path_min_drop_m':.2,'unresolved_terminals':int((target<0).sum()),'catchment_check':'Spatial overlay against county polygons only; inlet connectivity unverified.'}
        if not terrain['features']:terrain.update(status='empty')
    except (OSError,ValueError,KeyError) as e:terrain.update(status='unavailable',error=str(e),features=[])
    return save('water',bbox,source,[terrain,rain,catch],audit)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--refresh',action='store_true');args=parser.parse_args()
    DATA.mkdir(parents=True,exist_ok=True)
    build_traffic(args.refresh);build_water(args.refresh)
