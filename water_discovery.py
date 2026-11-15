"""Versioned western-pilot discovery from native USGS terrain and local sponsors."""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import numpy as np

WESTERN = (-118.307,34.055,-118.294,34.073)
BUFFER_M = 300
GRID_M = 250
PRODUCT_ROOT = 'https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/CA_LosAngeles_B23/TIFF/'
PRODUCTS = [f'USGS_1M_11_x{x}y{y}_CA_LosAngeles_B23.tif' for x in (37,38) for y in (377,378)]
DEM_URLS = [PRODUCT_ROOT+name for name in PRODUCTS]
DEM_PAGE = 'https://www.usgs.gov/3d-elevation-program'
PUBLISHED = '2025-08-11'
LIMITS = ('Bare-earth terrain only: buildings, curb cuts, pipes and drains are not routed. '
          'Flats and pits remain unresolved; no sink filling. Outlined raster contribution is not verified drainage, runoff capture, observed flooding or a treatment footprint. '
          'Small height differences may be within DEM error. Candidates receiving context-edge or NoData contributions are excluded.')


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def provenance(path):
    return {'retrieved_at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(timespec='seconds'),
            'input_sha256':sha256(path.read_bytes()).hexdigest()}


def projected_study():
    from pyproj import Transformer
    from shapely.geometry import box
    from shapely.ops import transform
    project=Transformer.from_crs(4326,26911,always_xy=True).transform
    return transform(project,box(*WESTERN))


def download_mosaic(directory, refresh=False):
    import rasterio
    from rasterio.windows import from_bounds, Window
    from rasterio.transform import Affine
    from contextlib import ExitStack
    directory=Path(directory);path=directory/'western-dem.tif';meta_path=directory/'western-terrain-source.json'
    if path.exists() and meta_path.exists() and not refresh:
        metadata=json.loads(meta_path.read_text())
        if (metadata.get('input_sha256')==sha256(path.read_bytes()).hexdigest()
                and metadata.get('pilot_bbox')==list(WESTERN) and metadata.get('buffer_m')==BUFFER_M
                and metadata.get('urls')==DEM_URLS):return path,metadata
        raise ValueError('Western terrain cache changed; rebuild with --refresh.')
    bounds=projected_study().buffer(BUFFER_M).bounds
    bounds=(math.floor(bounds[0]),math.floor(bounds[1]),math.ceil(bounds[2]),math.ceil(bounds[3]))
    tiles=directory/'terrain-tiles';tiles.mkdir(parents=True,exist_ok=True)
    inputs=[]
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',GDAL_HTTP_TIMEOUT='30',GDAL_HTTP_MAX_RETRY='1'):
        for url,name in zip(DEM_URLS,PRODUCTS):
            local=tiles/('western-'+name)
            if refresh or not local.exists():
                print('Reading USGS window:',name,flush=True)
                with rasterio.open(url) as src:
                    if src.crs.to_epsg()!=26911 or src.res!=(1.,1.) or src.count!=1 or src.transform.b or src.transform.d:
                        raise ValueError('Unexpected USGS native grid.')
                    left=max(bounds[0],src.bounds.left);bottom=max(bounds[1],src.bounds.bottom)
                    right=min(bounds[2],src.bounds.right);top=min(bounds[3],src.bounds.top)
                    if right<=left or top<=bottom:continue
                    raw=from_bounds(left,bottom,right,top,src.transform)
                    col,row=math.floor(raw.col_off),math.floor(raw.row_off)
                    window=Window(col,row,math.ceil(raw.col_off+raw.width)-col,math.ceil(raw.row_off+raw.height)-row)
                    values=src.read(1,window=window,masked=True)
                    profile=src.profile.copy();profile.update(width=values.shape[1],height=values.shape[0],transform=src.window_transform(window),compress='deflate',nodata=-999999)
                    temporary=local.with_suffix('.tmp.tif')
                    with rasterio.open(temporary,'w',**profile) as dst:dst.write(values.filled(-999999),1)
                    temporary.replace(local)
            inputs.append({'url':url,'file':str(local.relative_to(directory)),**provenance(local)})
        if len(inputs)!=4:raise ValueError('The western pilot requires all four source tiles.')
        with ExitStack() as stack:
            sources=[stack.enter_context(rasterio.open(directory/item['file'])) for item in inputs]
            # The product origins differ by sub-millimeter projection rounding.
            # Place native cells on the first source grid with a <=1 mm offset
            # tolerance. No interpolation and no dependence on merge's numeric
            # nodata casting (which can silently produce a zero-filled mosaic).
            first=sources[0].transform
            left=first.c+math.floor(bounds[0]-first.c)
            top=first.f+math.ceil(bounds[3]-first.f)
            affine=Affine(1,0,left,0,-1,top)
            width,height=math.ceil(bounds[2]-left),math.ceil(top-bounds[1])
            mosaic=np.full((1,height,width),np.nan,dtype=np.float32)
            overlap_difference=0.;alignment_error=0.
            for src in sources:
                if src.res!=(1.,1.) or src.crs.to_epsg()!=26911:raise ValueError('Mosaic sources are not on the native grid.')
                x,y=src.transform.c-left,top-src.transform.f
                col,row=round(x),round(y);error=max(abs(x-col),abs(y-row))
                if error>.001:raise ValueError('Source grids differ by more than 1 mm; explicit resampling would be required.')
                alignment_error=max(alignment_error,error)
                values=src.read(1,masked=True).astype(np.float32).filled(np.nan)
                bottom=min(row+src.height,height);right=min(col+src.width,width)
                if row<0 or col<0 or bottom<=row or right<=col:raise ValueError('Mosaic window does not cover a source.')
                incoming=values[:bottom-row,:right-col];existing=mosaic[0,row:bottom,col:right]
                overlap=np.isfinite(existing)&np.isfinite(incoming)
                if overlap.any():overlap_difference=max(overlap_difference,float(np.max(np.abs(existing[overlap]-incoming[overlap]))))
                np.copyto(existing,incoming,where=~np.isfinite(existing)&np.isfinite(incoming))
            if not np.isfinite(mosaic).any() or np.nanmax(mosaic)==np.nanmin(mosaic):raise ValueError('Mosaic does not retain source elevation variation.')
            profile=sources[0].profile.copy();profile.update(width=width,height=height,transform=affine,compress='deflate',nodata=float('nan'))
            temporary=path.with_suffix('.tmp.tif')
            with rasterio.open(temporary,'w',**profile) as dst:dst.write(mosaic)
            temporary.replace(path)
    with rasterio.open(path) as src:actual_bounds=list(src.bounds)
    metadata={'schema':2,'urls':DEM_URLS,'crs':'EPSG:26911','resolution_m':[1.,1.],
              'bounds':actual_bounds,'pilot_bbox':list(WESTERN),'buffer_m':BUFFER_M,
              'publication_date':PUBLISHED,'acquisition_date':None,'vertical_datum':'NAVD88, meters',
              'inputs':inputs,'maximum_alignment_error_m':alignment_error,'maximum_overlap_difference_m':overlap_difference,
              'method':'Native 1 m cells placed on a common grid within 1 mm origin tolerance; first valid overlapping pixel, no interpolation or gap filling.',
              **provenance(path)}
    meta_path.write_text(json.dumps(metadata,indent=2))
    return path,metadata


def upstream_cells(target, outlet, limit=50000):
    """Reverse the exact D8 links; disconnected cells never join an outline."""
    height,width=target.shape;queue=[int(outlet)];seen={int(outlet)}
    for cell in queue:
        row,col=divmod(cell,width)
        for r in range(max(0,row-1),min(height,row+2)):
            for c in range(max(0,col-1),min(width,col+2)):
                neighbor=r*width+c
                if target[r,c]==cell and neighbor not in seen:
                    seen.add(neighbor);queue.append(neighbor)
                    if len(queue)>limit:raise ValueError('Contribution outline exceeds the bounded cell limit.')
    return queue


def contribution_geometry(cells, width, affine):
    from rasterio.features import shapes
    from rasterio.transform import Affine
    from shapely.geometry import shape, mapping
    from shapely.ops import unary_union,transform
    from pyproj import Transformer
    rows=np.array(cells)//width;cols=np.array(cells)%width
    top,left=int(rows.min()),int(cols.min())
    mask=np.zeros((int(rows.max())-top+1,int(cols.max())-left+1),dtype=np.uint8)
    mask[rows-top,cols-left]=1
    window_transform=affine*Affine.translation(left,top)
    polygon=unary_union([shape(g) for g,value in shapes(mask,mask=mask.astype(bool),transform=window_transform,connectivity=4) if value==1])
    if not polygon.is_valid or abs(polygon.area-len(cells))>.01:raise ValueError('Contribution outline does not conserve raster area.')
    return mapping(transform(Transformer.from_crs(26911,4326,always_xy=True).transform,polygon))


def terrain_features(path, study=None):
    import rasterio
    from rasterio.features import geometry_mask,shapes
    from pyproj import Transformer
    from shapely.geometry import Point,mapping,shape
    from shapely.ops import transform,unary_union
    from terrain_discovery import d8,path_from
    study=projected_study() if study is None else study
    to_geo=Transformer.from_crs(26911,4326,always_xy=True).transform
    with rasterio.open(path) as src:
        if src.crs.to_epsg()!=26911 or src.res!=(1.,1.):raise ValueError('Unexpected terrain grid.')
        z=src.read(1,masked=True).astype(float).filled(np.nan);affine=src.transform
        in_study=geometry_mask([mapping(study)],z.shape,affine,invert=True)
    target,area,edge,slope=d8(z)
    h,w=z.shape
    def xy(i):return affine*(i%w+.5,i//w+.5)
    def coord(i):return list(to_geo(*xy(i)))
    def tile(i):
        x,y=xy(i);return (int(x//GRID_M),int(y//GRID_M))
    eligible=np.isfinite(z)&in_study&~edge&(area>=150)&(area<=50000)
    # Two unresolved collections and one path per display cell spread the
    # screen across independent blocks without calling them ranked designs.
    ordered=np.flatnonzero(eligible);ordered=ordered[np.argsort(area.ravel()[ordered],kind='stable')[::-1]]
    counts={};sinks=[];paths=[];used=set()
    for index in ordered:
        index=int(index);cell=tile(index);current=counts.setdefault(cell,[0,0])
        if target.flat[index]<0:
            if current[0]>=2 or any(math.dist(xy(index),xy(i))<35 for i in sinks):continue
            sinks.append(index);current[0]+=1
        elif current[1]<1 and index not in used:
            head=index
            for _ in range(100):
                r,c=divmod(head,w)
                incoming=[rr*w+cc for rr in range(max(0,r-1),min(h,r+2)) for cc in range(max(0,c-1),min(w,c+2)) if target[rr,cc]==head and area[rr,cc]>=25]
                if not incoming:break
                head=max(incoming,key=lambda i:area.flat[i])
            route=path_from(head,target,max_cells=2000)
            # Use only a contiguous in-pilot piece; never bridge the boundary.
            pieces=[];piece=[]
            for i in route:
                if in_study.flat[i] and not edge.flat[i]:piece.append(i)
                elif piece:pieces.append(piece);piece=[]
            if piece:pieces.append(piece)
            route=max(pieces,key=len,default=[])
            if len(route)<15 or z.flat[route[0]]-z.flat[route[-1]]<.2 or sum(i in used for i in route)>.4*len(route):continue
            if area.flat[route[-1]]>50000:continue
            paths.append(route);used.update(route);current[1]+=1
    features=[]
    for kind,entries in [('flow',paths),('collection',sinks)]:
        for item in entries:
            route=item if kind=='flow' else [item];start,end=route[0],route[-1]
            cells=upstream_cells(target,end)
            if len(cells)!=int(area.flat[end]):raise ValueError('D8 contribution area mismatch.')
            center=coord(route[len(route)//2]);details={'window_edge_contribution':False,
                     'raster_area_m2':len(cells),'coverage':'All outlined cells lie within valid downloaded terrain; actual drainage unverified.'}
            if kind=='flow':
                details.update(upstream_elevation_m=round(float(z.flat[start]),3),downstream_elevation_m=round(float(z.flat[end]),3),
                               drop_m=round(float(z.flat[start]-z.flat[end]),3),path_length_m=round(sum(math.dist(xy(a),xy(b)) for a,b in zip(route,route[1:])),2))
                geometry={'type':'LineString','coordinates':[coord(i) for i in route]}
                label='Downhill terrain path';summary='Follow the cyan path to investigate a potential collection location. The outlined raster area drains to its last cell in this terrain screen; buildings and actual drains can change that connection.'
            else:
                details.update(elevation_m=round(float(z.flat[end]),3),classification='Unresolved DEM flat or pit; not an observed flood or a confirmed inlet.')
                geometry={'type':'Point','coordinates':center};label='Collection location to investigate'
                summary='Terrain converges on this flat or low point. Inspect its outlined contribution area, nearby space and real inlet or overflow connections before placing a treatment.'
            row,col=divmod(end,w)
            features.append({'type':'Feature','id':f'{kind}-{row}-{col}','geometry':geometry,
                             'properties':{'label':label,'kind':kind,'value':float(len(cells)),'center':center,'summary':summary,
                                           'contributing_geometry':contribution_geometry(cells,w,affine),
                                           'scalar_detail':details,'grid_reference':{'raster':'western-dem.tif','start_row_col':list(divmod(start,w)),'end_row_col':[row,col]}}})
    valid=np.isfinite(z)&in_study
    audit={'raster_cells':int(z.size),'valid_cells':int(np.isfinite(z).sum()),'pilot_cells':int(in_study.sum()),
           'pilot_valid_cells':int(valid.sum()),'context_buffer_m':BUFFER_M,'grid_crs':'EPSG:26911','grid_resolution_m':1,
           'spatial_selection_grid_m':GRID_M,'threshold_area_m2':150,'maximum_contribution_m2':50000,
           'pilot_edge_affected_cells':int((edge&in_study).sum()),'represented_blocks':len({tile(i) for i in sinks+[p[-1] for p in paths]}),
           'raster_range_m':[float(np.nanmin(z)),float(np.nanmax(z))],
           'method':'Strictly descending unfilled D8; propagated context/NoData boundary excluded; exact reverse-linked contribution polygons.'}
    return features,audit


def layer(identifier,label,source,unit,classification,method,limits,period='Source date unavailable'):
    return dict(id=identifier,label=label,source=source,unit=unit,classification=classification,method=method,limitations=limits,period=period,status='ready',features=[])


def cached(directory,name,fetch,refresh):
    path=directory/name
    if path.exists() and not refresh:return json.loads(path.read_text()),provenance(path)
    value=fetch();path.write_text(json.dumps(value,allow_nan=False));return value,provenance(path)


def build_water(directory, refresh=False, sponsors=False):
    from hydrology import rainfall_contours,rainfall_at,county_features,COUNTY_GIS,RAINFALL
    from pyproj import Transformer
    from shapely.geometry import box,shape,mapping
    from shapely.ops import transform
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    catch_url=f'{COUNTY_GIS}/PW_Open_Data/MapServer/47'
    sources={'dem':{'label':'USGS 3DEP · four native 1 m DEM tiles','url':DEM_PAGE,'observed_at':None,'retrieved_at':None,'published_at':PUBLISHED,'vertical_datum':'NAVD88, meters','product':'CA_LosAngeles_B23 · western pilot','raster_file':'western-dem.tif'},
             'rainfall':{'label':'LA County rainfall contours','url':RAINFALL,'observed_at':None,'retrieved_at':None},
             'catchments':{'label':'LA County storm-drain study catchments','url':catch_url,'observed_at':None,'retrieved_at':None},
             'costar':{'label':'CoStar local property kit','url':'https://www.costar.com/','observed_at':None,'retrieved_at':None},
             'vexcel':{'label':'Vexcel parcel/building extraction','url':'https://api.vexcelgroup.com/v2/property/extract','observed_at':None,'retrieved_at':None}}
    terrain=layer('terrain','Terrain paths & collection areas','dem','m² of terrain-inferred contribution','derived',
                  'Native 1 m unfilled D8 across the western pilot with 300 m surrounding context; boundary-affected candidates excluded. Select a feature to see its exact contributing raster outline.',LIMITS,'USGS published '+PUBLISHED+' · acquisition date unverified')
    rain=layer('rainfall','Design rainfall depth','rainfall','inches','estimated','County contour interpolation at 100 m display-cell centers. The display grid is not source resolution.','85th-percentile 24-hour event depth; not a forecast, rainfall intensity, observed flooding or flood depth.','85th-percentile · 24-hour event')
    catch=layer('catchments','County drainage study areas','catchments','mapped catchment','reported','County polygons clipped to the pilot.','Regional study context; no parcel, inlet or pipe connection is established.')
    properties=layer('properties','Reported property uses','costar','reported use','reported','CoStar point records within the pilot; parcel association requires the selected-site check.','Property points and reported use do not establish ownership, precise parcels, infiltration or runoff.')
    surfaces=layer('surfaces','Mapped parcels & buildings','vexcel','m² of mapped outline','measured','Bounded extraction at three independent properties; latest dated returned collections. Areas measured locally in UTM 11N.','Sampled site evidence, not pilot-wide surface coverage. Building-free space is not necessarily permeable, plantable or accessible.')
    boundary=box(*WESTERN);study=projected_study();to_geo=Transformer.from_crs(26911,4326,always_xy=True).transform
    audit={}
    try:
        path,metadata=download_mosaic(directory,refresh)
        sources['dem'].update(provenance(path),metadata_file='western-terrain-source.json',metadata_sha256=sha256((directory/'western-terrain-source.json').read_bytes()).hexdigest(),urls=DEM_URLS)
        terrain['features'],audit=terrain_features(path)
        if audit['pilot_valid_cells']<audit['pilot_cells']:terrain['status']='partial'
        if not terrain['features']:terrain['status']='empty'
    except (OSError,ValueError,KeyError,ImportError) as error:
        terrain.update(status='unavailable',error='Complete source-backed terrain build failed: '+str(error),features=[])
    try:
        raw,meta=cached(directory,'western-catchments.json',lambda:county_features(catch_url,','.join(map(str,WESTERN)),'esriGeometryEnvelope','AREA_NAME,OUTFALL_ID'),refresh)
        sources['catchments'].update(meta)
        for index,feature in enumerate(raw):
            polygon=shape(feature['geometry'])
            if not polygon.is_valid:raise ValueError('Invalid county catchment polygon.')
            cut=polygon.intersection(boundary)
            if cut.is_empty:continue
            point=cut.representative_point();p=feature['properties']
            catch['features'].append({'type':'Feature','id':f'catchment-{index}','geometry':mapping(cut),
                                     'properties':{'label':p['AREA_NAME'],'value':p['AREA_NAME'],'center':[point.x,point.y],
                                                   'scalar_detail':{'outfall_reference':p.get('OUTFALL_ID'),'scope':'County study context; no site drainage connection.'}}})
        if not catch['features']:catch['status']='empty'
    except (OSError,ValueError,KeyError) as error:catch.update(status='unavailable',error=str(error),features=[])
    try:
        contours,meta=cached(directory,'western-rainfall.json',lambda:rainfall_contours(WESTERN),refresh)
        sources['rainfall'].update(meta)
        left,bottom,right,top=study.bounds
        for row,y in enumerate(np.arange(math.floor(bottom/100)*100,top,100)):
            for col,x in enumerate(np.arange(math.floor(left/100)*100,right,100)):
                cell=box(x,y,x+100,y+100).intersection(study)
                if cell.is_empty:continue
                center=to_geo(*cell.representative_point().coords[0]);estimate=rainfall_at(*center,contours)
                if estimate is None:continue
                rain['features'].append({'type':'Feature','id':f'rain-{row}-{col}','geometry':mapping(transform(to_geo,cell)),
                                        'properties':{'label':'Design rainfall depth','value':estimate['inches'],'center':list(center),
                                                      'scalar_detail':{'interpolation':estimate['method'],'bracketing_contours_in':estimate['depth_range']}}})
        if not rain['features']:rain['status']='empty'
    except (OSError,ValueError,KeyError) as error:rain.update(status='unavailable',error=str(error),features=[])
    try:
        import server
        catalog=server.property_catalog()[0]
        records=[p for p in catalog if WESTERN[0]<=p['lon']<=WESTERN[2] and WESTERN[1]<=p['lat']<=WESTERN[3]]
        for p in records:
            properties['features'].append({'type':'Feature','id':'property-'+p['id'],'geometry':{'type':'Point','coordinates':[p['lon'],p['lat']]},
                                           'properties':{'label':p['name']+' · '+p['address'],'value':p['type'],'center':[p['lon'],p['lat']],
                                                         'scalar_detail':{'scope':'Reported property use, not parcel control or runoff generation.'}}})
        kit=Path(server.os.environ['COSTAR_KIT_DIR'])/'data/commercial-property.jsonl'
        sources['costar'].update(provenance(kit))
        if not properties['features']:properties['status']='empty'
        sampled=[];failures=[]
        for ident in ('4355436','4483806','734761'):
            point=next(p for p in catalog if p['id']==ident)
            name='western-vexcel-'+ident+'.json'
            try:
                if not sponsors and not (directory/name).exists():raise ValueError('Sponsor sample not downloaded; build with --sponsors.')
                outlines,meta=cached(directory,name,lambda:server.site_outlines(point['lon'],point['lat'],'water'),refresh and sponsors)
                sampled.append({'property_id':ident,**meta})
                for index,feature in enumerate(outlines):
                    polygon=shape(feature['geometry']);p=feature['properties']
                    if not polygon.is_valid:raise ValueError('Unusable Vexcel outline.')
                    from site_measurements import PROJECT
                    projected=transform(PROJECT.transform,polygon)
                    center=polygon.representative_point()
                    surfaces['features'].append({'type':'Feature','id':f'outline-{ident}-{index}','geometry':mapping(polygon),
                        'properties':{'label':p['label']+' · '+point['name'],'value':round(projected.area,1),'center':[center.x,center.y],
                                      'period':p.get('date') or 'Capture date not supplied','kind':'building' if p['label']=='Building footprint' else 'parcel',
                                      'scalar_detail':{'capture_date':p.get('date'),'collection':p.get('collection'),'scope':'Mapped outline only; building coverage '+str(p.get('buildingCoverage','not supplied'))+'.'}}})
            except (OSError,ValueError,KeyError) as error:failures.append({'property_id':ident,'reason':str(error)})
        sources['vexcel'].update(retrieved_at=min((p['retrieved_at'] for p in sampled),default=None),samples=sampled)
        surfaces['status']='partial' if failures and surfaces['features'] else 'unavailable' if failures else 'ready' if surfaces['features'] else 'empty'
        if failures:surfaces['error']='One or more sampled properties have no usable outlines.'
        audit['sponsor_samples']={'successful':len(sampled),'failures':failures}
    except (OSError,ValueError,KeyError,StopIteration,ImportError):
        properties.update(status='unavailable',error='Local CoStar kit unavailable.',features=[])
        surfaces.update(status='unavailable',error='Sponsor sample configuration unavailable.',features=[])
    # Keep save's destination explicit so isolated builds never touch live data.
    data={'schema':1,'workflow':'water','bbox':list(WESTERN),'built_at':stamp(),'sources':sources,
          'layers':[terrain,rain,catch,properties,surfaces],'audit':audit}
    data['version']=sha256(json.dumps(data,sort_keys=True,allow_nan=False).encode()).hexdigest()[:16]
    temporary=directory/'water.tmp';temporary.write_text(json.dumps(data,separators=(',',':'),allow_nan=False));temporary.replace(directory/'water.json')
    print('water',[(l['id'],l['status'],len(l['features'])) for l in data['layers']],flush=True)
    return data
