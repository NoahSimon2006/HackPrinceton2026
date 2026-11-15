"""Source-connected junctions and walking landings for whole-intersection plans.

Topology, never line proximity alone, establishes a junction. Geographic data
stays in the local context; model summaries expose anonymous IDs and dimensions.
Separately mapped footways can bound a conceptual street envelope but do not
establish a surveyed curb, sidewalk width, ownership, or construction permission.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import math

from pyproj import Transformer
from shapely import make_valid, set_precision, unary_union
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, substring

from site_measurements import PROJECT, projected

MAX_JUNCTION_DISTANCE = 120.
MAX_APPROACH_LENGTH = 65.
MIN_APPROACH_LENGTH = 8.
WALK_KINDS = {'footway', 'path', 'pedestrian'}
MAJOR_KINDS = {'primary', 'secondary', 'tertiary', 'residential', 'unclassified', 'living_street',
               'primary_link', 'secondary_link', 'tertiary_link'}
COMPASS = ('north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest')


def _geo(geometry):
    from street_context import _geographic
    if geometry.geom_type in ('Polygon', 'MultiPolygon'):
        geometry = _clean_area(geometry)
    return _geographic(geometry)


def _clean_area(geometry):
    """Normalize derived source envelopes at millimeter screening precision."""
    value = set_precision(geometry, .001)
    polygons = _parts(value, 'Polygon')
    if not polygons:
        return value
    # Microscopic holes/slivers created at reprojected shared boundaries are not
    # mapped islands. Keep all meaningful holes and preserve topology otherwise.
    return unary_union([Polygon(part.exterior.coords,
        [ring.coords for ring in part.interiors if Polygon(ring).area >= .01])
        for part in polygons]).simplify(.001, preserve_topology=True)


def _opaque(prefix, value):
    return prefix + sha256(value.encode()).hexdigest()[:12]


def _heading(line, distance=3.):
    start, end = line.interpolate(0), line.interpolate(min(distance, line.length))
    return math.degrees(math.atan2(end.x - start.x, end.y - start.y)) % 360


def _direction(angle):
    return COMPASS[int((angle + 22.5) // 45) % 8]


def _unit(line, distance):
    a = line.interpolate(max(0., distance - .5))
    b = line.interpolate(min(line.length, distance + .5))
    length = a.distance(b)
    if length < .01:
        raise ValueError('Road alignment has no usable tangent.')
    return (b.x - a.x) / length, (b.y - a.y) / length


def _parts(geometry, kind):
    if geometry.is_empty:
        return []
    if geometry.geom_type == kind:
        return [geometry]
    return [part for child in getattr(geometry, 'geoms', ()) for part in _parts(child, kind)]


def _source_data(raw, family, origin):
    from street_context import _xml, MAX_LOCAL_BYTES
    root = _xml(raw, limit=MAX_LOCAL_BYTES)
    nodes, walking = {}, []
    if family == 'sumo':
        location = root.find('location')
        ox, oy = map(float, location.get('netOffset', '0,0').split(','))
        convert = Transformer.from_crs(location.get('projParameter'), 32611, always_xy=True)
        def xy(value):
            x, y = map(float, value.split(',')[:2])
            return convert.transform(x - ox, y - oy)
        roundabout_nodes = {value for circle in root.findall('roundabout') for value in (circle.get('nodes') or '').split()}
        for node in root.findall('junction'):
            if node.get('type') == 'internal':
                continue
            point = Point(*convert.transform(float(node.get('x')) - ox, float(node.get('y')) - oy))
            if point.distance(origin) > 200:
                continue
            coords = [xy(value) for value in (node.get('shape') or '').split()]
            area = Polygon(coords) if len(coords) >= 3 else None
            normalized = False
            if area is not None and not area.is_valid:
                # SUMO junction outlines can self-overlap where pedestrian
                # connectors join corners. Retain only a single valid polygon
                # from explicit boundary normalization and disclose the step.
                area = make_valid(area)
                normalized = True
            if area is not None and (area.geom_type != 'Polygon' or area.is_empty or area.area < 1 or area.area > 20_000):
                area = None
            nodes[node.get('id')] = {'point': point, 'area': area, 'kind': 'roundabout' if node.get('id') in roundabout_nodes else node.get('type'), 'area_normalized': normalized}
        for edge in root.findall('edge'):
            if edge.get('function') or edge.get('type', '').removeprefix('highway.').split('|')[0] not in WALK_KINDS:
                continue
            for lane in edge.findall('lane')[:1]:
                coords = [xy(value) for value in (lane.get('shape') or '').split()]
                if len(coords) < 2:
                    continue
                line = LineString(coords)
                if line.is_simple and line.length > 1 and line.distance(origin) < 160:
                    walking.append({'id': _opaque('walk-', 'sumo:' + edge.get('id', '')), 'line': line,
                                    'width_m': float(lane.get('width', '1')), 'node_refs': [edge.get('from'), edge.get('to')],
                                    'basis': 'Separately mapped OSM-derived pedestrian path.'})
    else:
        for node in root.findall('node'):
            try:
                point = Point(*PROJECT.transform(float(node.get('lon')), float(node.get('lat'))))
            except (ValueError, TypeError):
                continue
            nodes[node.get('id')] = {'point': point, 'area': None, 'kind': 'osm_shared_node'}
        for way in root.findall('way'):
            tags = {item.get('k'): item.get('v') for item in way.findall('tag')}
            if tags.get('highway') not in WALK_KINDS or tags.get('access') in ('no', 'private'):
                continue
            refs = [item.get('ref') for item in way.findall('nd')]
            if len(refs) < 2 or any(ref not in nodes for ref in refs):
                continue
            line = LineString([nodes[ref]['point'].coords[0] for ref in refs])
            if line.is_simple and line.length > 1 and line.distance(origin) < 160:
                walking.append({'id': _opaque('walk-', 'osm:' + way.get('id', '')), 'line': line,
                                'width_m': None, 'node_refs': refs,
                                'basis': 'Separately mapped OpenStreetMap pedestrian path; width unreported.'})
    return nodes, walking


def _connections(anchors, nodes, family):
    """Outward half-roads incident to actual shared source nodes."""
    connections = {}
    for anchor in anchors:
        topology = anchor.get('topology', {})
        if topology.get('road_class') not in MAJOR_KINDS or topology.get('junction_type') == 'roundabout':
            continue
        line = projected(anchor['geometry'], ('LineString',))
        if family == 'sumo':
            for endpoint, reverse in ((topology.get('from'), False), (topology.get('to'), True)):
                if endpoint not in nodes:
                    continue
                directed = LineString(list(line.coords)[::-1]) if reverse else line
                other = topology.get('from') if reverse else topology.get('to')
                connections.setdefault(endpoint, []).append({'anchor': anchor, 'line': directed, 'next_node': other,
                                                              'source_node': endpoint, 'reverse': reverse})
        else:
            refs = topology.get('node_refs', [])
            # Node incidence is exact. A bridge merely crossing another line
            # without a shared OSM node never becomes a junction.
            for index, endpoint in enumerate(refs):
                if endpoint not in nodes:
                    continue
                point = nodes[endpoint]['point']
                if line.distance(point) > .2:
                    continue  # The source way was clipped before this node.
                distance = line.project(point)
                for reverse, start, end in ((False, distance, line.length), (True, distance, 0.)):
                    if abs(end - start) < MIN_APPROACH_LENGTH:
                        continue
                    directed = substring(line, start, end)
                    next_node = refs[index - 1] if reverse and index > 0 else refs[index + 1] if not reverse and index + 1 < len(refs) else None
                    connections.setdefault(endpoint, []).append({'anchor': anchor, 'line': directed, 'next_node': next_node,
                                                                  'source_node': endpoint, 'reverse': reverse})
    return connections


def _unique_legs(rows):
    ordered = []
    for row in sorted(rows, key=lambda item: item['anchor']['id']):
        angle = _heading(row['line'])
        if all(abs((angle - _heading(old['line']) + 180) % 360 - 180) > 25 for old in ordered):
            ordered.append(row)
    return ordered


def _extend(row, connections, nodes, family):
    line = row['line']
    source_ids = [row['anchor']['id']]
    width = row['anchor']['width_m']
    if family == 'sumo':
        next_node = row['next_node']
        for _ in range(5):
            if line.length >= MAX_APPROACH_LENGTH or next_node not in connections:
                break
            candidates = _unique_legs(connections[next_node])
            if len(candidates) > 2:
                break  # A second real intersection bounds this approach.
            current_heading = _heading(LineString(list(line.coords)[-2:]))
            forward = [item for item in candidates if item['anchor']['id'] not in source_ids
                       and item['anchor']['label'].casefold() == row['anchor']['label'].casefold()
                       and item['anchor'].get('traffic_direction') == row['anchor'].get('traffic_direction')
                       and (row['anchor'].get('traffic_direction') != 'one_way' or
                            (item['reverse'] == row['reverse'] and item['anchor'].get('lane_count') == row['anchor'].get('lane_count')))
                       and abs((_heading(item['line']) - current_heading + 180) % 360 - 180) < 40]
            if len(forward) != 1:
                break
            follow = forward[0]
            if follow['anchor']['width_m'] < width * .8:
                break  # Do not extrapolate a wide junction through a lane-width transition.
            # The short bridge through a source-connected minor node belongs to
            # that node's mapped roadway, not an invented connection.
            coords = list(line.coords)
            # Join the actual source road-mouth centerlines directly. A SUMO
            # node center can be displaced by pedestrian/service geometry;
            # routing through it creates an artificial zigzag in a straight road.
            coords.extend(follow['line'].coords)
            candidate = LineString(coords)
            if not candidate.is_simple:
                break
            line = candidate
            source_ids.append(follow['anchor']['id'])
            width = min(width, follow['anchor']['width_m'])
            next_node = follow['next_node']
    return substring(line, 0., min(line.length, MAX_APPROACH_LENGTH)), source_ids, width


def _landing(line, position, side, width, walking):
    center = line.interpolate(position)
    tx, ty = _unit(line, position)
    sign = 1 if side == 'left' else -1
    nx, ny = -ty * sign, tx * sign
    ray = LineString([(center.x + nx * max(1., width / 2 - 1.), center.y + ny * max(1., width / 2 - 1.)),
                      (center.x + nx * 22, center.y + ny * 22)])
    matches = []
    for path in walking:
        near = path['line'].project(center)
        ux, uy = _unit(path['line'], near)
        if abs(tx * ux + ty * uy) < .65:
            continue  # A crossing path itself is not an along-street landing.
        points = _parts(ray.intersection(path['line']), 'Point')
        if not points and ray.distance(path['line']) < 1.5:
            points = [nearest_points(ray, path['line'])[1]]
        for point in points:
            along = (point.x - center.x) * tx + (point.y - center.y) * ty
            lateral = (point.x - center.x) * nx + (point.y - center.y) * ny
            if abs(along) <= 2 and width / 2 - 1. <= lateral <= 22:
                matches.append((point.distance(center), path, point))
    if not matches:
        return {'side': side, 'point': Point(center.x + nx * width / 2, center.y + ny * width / 2),
                'basis': 'Proposed landing at the modeled road edge; existing sidewalk connection unverified.',
                'status': 'proposed', 'source_ref': None, 'width_m': None}
    _, path, point = min(matches, key=lambda item: item[0])
    return {'side': side, 'point': point, 'basis': path['basis'], 'status': 'mapped',
            'source_ref': path['id'], 'width_m': path['width_m']}


def _approach(row, node_id, node, connections, nodes, walking, family, origin, junction_id, source_anchors):
    line, chain, width = _extend(row, connections, nodes, family)
    if line.length < MIN_APPROACH_LENGTH:
        return None
    source_area = node['area']
    # SUMO lane geometry starts at its junction mouth. OSM centerlines start at
    # the shared center node; move to the inferred intersection edge first.
    if family == 'osm' and source_area is not None:
        inside = line.intersection(source_area)
        distances = [line.project(Point(coord)) for part in _parts(inside, 'LineString') for coord in part.coords]
        start = max(distances, default=0.)
        if line.length - start < MIN_APPROACH_LENGTH:
            return None
        line = substring(line, start, line.length)
    crossing_center = min(4., line.length / 3)
    landings = [_landing(line, crossing_center, side, width, walking) for side in ('left', 'right')]
    crossing = LineString([item['point'].coords[0] for item in landings])
    matched = all(item['status'] == 'mapped' for item in landings)
    # Bounded paired sidewalk samples establish a planning envelope wider than
    # modeled traffic lanes (which commonly omit parking). It is not a curb survey.
    left, right = [], []
    for position in [0., *range(2, int(min(line.length, 40)) + 1, 2), min(line.length, 40.)]:
        pair = [_landing(line, position, side, width, walking) for side in ('left', 'right')]
        left.append(pair[0]['point'].coords[0]); right.append(pair[1]['point'].coords[0])
    envelope = Polygon(left + right[::-1])
    modeled = line.buffer(width / 2, cap_style='flat')
    if not envelope.is_valid or envelope.area < modeled.area * .2:
        envelope = modeled
    else:
        # The distant tail retains its explicit modeled width. No inferred
        # sidewalk corridor is extrapolated beyond the sampled paths.
        envelope = unary_union([envelope, modeled])
    heading = _heading(line)
    identifier = _opaque('road-', 'junction-approach:' + family + ':' + node_id + ':' + '|'.join(chain) + (':' + str(row['reverse']) if family == 'osm' else ''))
    midpoint = line.project(origin)
    basis = ('Street envelope follows separately mapped pedestrian paths where available; exact curb and parking geometry are unverified.'
             if matched else row['anchor']['width_basis'])
    anchor = {**deepcopy(row['anchor']), 'id': identifier, 'geometry': _geo(line), 'surface': _geo(envelope),
              'length_m': round(line.length, 3), 'width_m': round(width, 3), 'width_basis': basis,
              'heading_deg': round(heading, 1), 'selection_offset_m': round(midpoint, 2),
              'distance_m': round(line.distance(origin), 2), 'junction_id': junction_id,
              'supported_kinds': list(dict.fromkeys([*row['anchor']['supported_kinds'], 'intersection_redesign'])),
              'topology': {'family': family, 'junction_id': node_id, 'source_anchor_ids': chain}}
    access_openings = []
    chain_nodes = {endpoint for candidate in source_anchors if candidate['id'] in chain
                   for endpoint in (candidate.get('topology', {}).get('from'), candidate.get('topology', {}).get('to'))
                   if endpoint is not None and endpoint != node_id}
    for candidate in source_anchors:
        topology = candidate.get('topology', {})
        if topology.get('road_class') != 'service':
            continue
        shared = chain_nodes.intersection((topology.get('from'), topology.get('to')))
        if not shared:
            continue
        shapes = [projected(candidate['surface'])]
        shapes += [nodes[identifier]['area'] for identifier in shared if identifier in nodes and nodes[identifier]['area'] is not None]
        service_line = projected(candidate['geometry'], ('LineString',))
        for shared_node_id in shared:
            if shared_node_id not in nodes:
                continue
            point = nodes[shared_node_id]['point']
            mouth = nearest_points(service_line, point)[0]
            if point.distance(mouth) > .001:
                shapes.append(LineString([point, mouth]).buffer(candidate['width_m'] / 2 + .5, cap_style='square'))
        opening = unary_union(shapes).intersection(envelope.buffer(3))
        if opening.is_empty or opening.area < .1:
            continue
        access_openings.append({'type': 'Feature', 'id': 'access-' + candidate['id'], 'geometry': _geo(opening),
                                'properties': {'kind': 'access', 'basis': 'Source-connected service-road mouth; preserve the opening in proposed curbs and sidewalks.'}})
    point = line.interpolate(crossing_center)
    tx, ty = _unit(line, crossing_center)
    curb = [Point(point.x - ty * sign * width / 2, point.y + tx * sign * width / 2) for sign in (1, -1)]
    value = {'id': _opaque('approach-', junction_id + ':' + identifier), 'anchor_id': identifier,
             'geometry': _geo(line), 'road_geometry': _geo(envelope), 'modeled_road_geometry': _geo(modeled),
             'mouth': _geo(line.interpolate(0)), 'bearing_deg': round(heading, 1), 'direction': _direction(heading),
             'width_m': round(width, 3), 'modeled_width_m': round(width, 3),
             'traffic_direction': anchor.get('traffic_direction', 'unverified'), 'access_openings': access_openings,
             'plan_width_m': round(max(width, crossing.length), 3), 'width_basis': basis,
             'junction_offset_m': 0., 'outward_sign': 1, 'crossing_offset_m': round(max(0., crossing_center - 1.5), 3),
             'available_length_m': round(line.length, 3), 'curb_endpoints': [_geo(point) for point in curb],
             'walking_landings': [{**item, 'point': _geo(item['point'])} for item in landings],
             'walking_connection_status': 'mapped' if matched else 'partial' if any(item['status'] == 'mapped' for item in landings) else 'proposed',
             'crossing_geometry': _geo(crossing), 'crossing_span_m': round(crossing.length, 3),
             'source_anchor_ids': chain,
             'road_geometry_basis': 'Bounded planning envelope from mapped road alignment and nearby pedestrian paths; unverified between-source surface.'}
    value['traffic_flow'] = ('inbound' if row['reverse'] else 'outbound') if anchor.get('traffic_direction') == 'one_way' else anchor.get('traffic_direction', 'unverified')
    if 'lane_count' in anchor:
        value['lane_count'] = anchor['lane_count']
    value['direction_basis'] = anchor.get('direction_basis', 'Paired opposing local network carriageways.' if value['traffic_flow'] == 'two_way' else 'Unpaired carriageway; whole-road direction unverified.')
    return anchor, value


def _pedestrian_connections(junction_id, node, approaches, walking):
    """Fill individual corners bounded by mapped walking paths, never a site hull.

    The inner edge lies in the source junction; the outer boundary follows each
    matched path toward its source junction mouth and a bounded proposed joining
    segment. This supplies the missing corner between adjacent approach strips.
    """
    paths = {item['id']: item for item in walking}
    center = node['point']
    existing_envelope = unary_union([node['area'], *[projected(item['road_geometry']) for item in approaches]])
    ordered = sorted(approaches, key=lambda item: item['bearing_deg'])
    result = []
    for index, first in enumerate(ordered):
        second = ordered[(index + 1) % len(ordered)]
        gap = (second['bearing_deg'] - first['bearing_deg']) % 360
        if gap < 35 or gap > 200:
            continue
        a = next(item for item in first['walking_landings'] if item['side'] == 'right')
        b = next(item for item in second['walking_landings'] if item['side'] == 'left')
        first_path, second_path = paths.get(a['source_ref']), paths.get(b['source_ref'])
        if not first_path or not second_path:
            # Without mapped footways, reserve only an explicitly proposed
            # connection inside the already known road/junction envelope. A
            # straight corner chord must not authorize paving an unknown parcel.
            pa, pb = [Point(*PROJECT.transform(*item['point']['coordinates'])) for item in (a, b)]
            fan = Polygon([center.coords[0], pa.coords[0], pb.coords[0], center.coords[0]])
            polygon = _clean_area(fan.intersection(existing_envelope))
            if polygon.geom_type == 'Polygon' and polygon.area >= 1:
                result.append({'type': 'Feature', 'id': f'{junction_id}-pedestrian-corner-{index + 1}', 'geometry': _geo(polygon),
                    'properties': {'kind': 'pedestrian_connection',
                                   'basis': 'Proposed walking connection within the modeled road and junction envelope; existing sidewalks and accessibility remain unverified.',
                                   'source_refs': [], 'from_approach_id': first['id'], 'to_approach_id': second['id']}})
            continue
        def inward_segment(landing, path):
            point = Point(*PROJECT.transform(*landing['point']['coordinates']))
            start, finish = path['line'].project(point), path['line'].project(center)
            segment = substring(path['line'], start, finish)
            coords = list(segment.coords)
            return [point.coords[0], *coords] if coords[0] != point.coords[0] else coords
        left = inward_segment(a, first_path)
        right = inward_segment(b, second_path)
        # Adjacent source footways often cross before their nearest-to-center
        # points. Stop at that crossing rather than making a bow-tie boundary.
        shared = _parts(LineString(left).intersection(LineString(right)), 'Point')
        if shared:
            meeting = min(shared, key=lambda point: point.distance(Point(left[0])) + point.distance(Point(right[0])))
            left = list(substring(LineString(left), 0., LineString(left).project(meeting)).coords)
            right = list(substring(LineString(right), 0., LineString(right).project(meeting)).coords)
        # Keep the bounded corner near the actual junction and its known walking
        # landings. Long, folded pedestrian paths do not authorize a broad fill.
        radius = max(Point(left[0]).distance(center), Point(right[0]).distance(center)) + 2
        if radius > 35 or any(Point(point).distance(center) > radius for point in left + right):
            continue
        if Point(left[-1]).distance(Point(right[-1])) > 20:
            continue
        polygon = Polygon([center.coords[0], *left, *right[::-1], center.coords[0]])
        if not polygon.is_valid:
            polygon = make_valid(polygon)
        pieces = _parts(polygon, 'Polygon')
        if not pieces:
            continue
        polygon = _clean_area(unary_union(pieces))
        if polygon.is_empty or polygon.area < 1 or polygon.geom_type != 'Polygon' or not center.buffer(radius).covers(polygon):
            continue
        common = set(first_path.get('node_refs', [])).intersection(second_path.get('node_refs', [])) - {None}
        basis = ('Corner envelope bounded by mapped pedestrian paths that share source topology; the short joining segment and pavement are proposed.'
                 if common else 'Proposed corner connection bounded by adjacent mapped pedestrian paths; existing walking connectivity remains unverified.')
        result.append({'type': 'Feature', 'id': f'{junction_id}-pedestrian-corner-{index + 1}', 'geometry': _geo(polygon),
                       'properties': {'kind': 'pedestrian_connection', 'basis': basis,
                                      'source_refs': [a['source_ref'], b['source_ref']],
                                      'from_approach_id': first['id'], 'to_approach_id': second['id']}})
    return result


def build_junction_context(raw, family, anchors, origin):
    """Build one nearest eligible source intersection; never move the selected site."""
    if family not in ('sumo', 'osm'):
        return {'junctions': [], 'anchors': []}
    nodes, walking = _source_data(raw, family, origin)
    connections = _connections(anchors, nodes, family)
    candidates = []
    for identifier, rows in connections.items():
        node = nodes[identifier]
        distance = node['point'].distance(origin)
        legs = _unique_legs(rows)
        if node['kind'] != 'roundabout' and distance <= MAX_JUNCTION_DISTANCE and 3 <= len(legs) <= 6:
            candidates.append((distance, identifier, legs))
    for distance, node_id, legs in sorted(candidates):
        node = deepcopy(nodes[node_id])
        if node['area'] is None:
            # OSM supplies topology and centerlines, not a junction boundary.
            # Bound the authored junction by intersecting the incident corridors
            # with a local radius, with this inference explicit in its basis.
            radius = max(row['anchor']['width_m'] for row in legs) / 2 + 2
            corridors = [row['line'].buffer(row['anchor']['width_m'] / 2, cap_style='square') for row in legs]
            node['area'] = unary_union(corridors).intersection(node['point'].buffer(radius))
            if node['area'].is_empty or node['area'].area < 1 or node['area'].geom_type != 'Polygon' or not node['area'].is_valid:
                continue
        identifier = _opaque('junction-', family + ':' + node_id)
        prepared = [_approach(row, node_id, node, connections, nodes, walking, family, origin, identifier, anchors) for row in legs]
        if any(item is None for item in prepared):
            continue
        new_anchors, approaches = map(list, zip(*prepared))
        if family == 'osm':
            # OSM source centerlines continue all the way to the shared node.
            # Preserve their full known width between that node and each chosen
            # mouth; the initial radial cut must not trim off sidewalk corners.
            source_bridges = [LineString([node['point'], Point(*PROJECT.transform(*item['mouth']['coordinates']))]).buffer(
                item['width_m'] / 2, cap_style='flat') for item in approaches]
            node['area'] = _clean_area(unary_union([node['area'], *source_bridges]))
        pedestrian_connections = _pedestrian_connections(identifier, node, approaches, walking)
        roads = [projected(item['road_geometry']) for item in approaches]
        # Actual source road mouths can leave small modeled gaps to the junction
        # polygon. Source-connected mouth cross-sections provide bounded bridges.
        bridges = []
        for row in approaches:
            line = projected(row['geometry'], ('LineString',))
            mouth = line.interpolate(0)
            nearest = nearest_points(node['area'], mouth)[0]
            if mouth.distance(nearest) > .000001:
                bridges.append(LineString([mouth, nearest]).buffer(row['width_m'] / 2, cap_style='square'))
        # Adjacent source mouths may differ by floating-point reprojection dust.
        # The 2 mm junction overlap ensures a single connected planning surface.
        plan_area = _clean_area(unary_union([node['area'].buffer(.002), *roads, *bridges,
                                             *[projected(item['geometry']) for item in pedestrian_connections]]))
        if plan_area.geom_type != 'Polygon' or not plan_area.is_valid:
            continue
        # Normalized SUMO corner boundaries can leave enclosed triangles between
        # mapped walking connections. These are bounded proposed pedestrian
        # infills, not exterior parcel expansion; retain larger/remote holes.
        infills = []
        for ring in plan_area.interiors:
            hole = Polygon(ring)
            if hole.area <= 30 and node['point'].buffer(30).covers(hole) and any(
                    hole.distance(projected(item['geometry'])) < .02 for item in pedestrian_connections):
                feature = {'type': 'Feature', 'id': f'{identifier}-pedestrian-infill-{len(infills) + 1}',
                           'geometry': _geo(hole), 'properties': {'kind': 'pedestrian_connection',
                           'basis': 'Proposed pedestrian infill of an enclosed gap between source junction boundaries and bounded walking connections; not a surveyed existing sidewalk.',
                           'source_refs': []}}
                infills.append(feature)
        if infills:
            pedestrian_connections.extend(infills)
            plan_area = _clean_area(unary_union([plan_area, *[projected(item['geometry']) for item in infills]]))
        basis = ('OSM-derived SUMO junction polygon and connected roadway topology; widths and curbs are not surveyed.'
                 if family == 'sumo' else 'Shared OpenStreetMap road node with an inferred bounded junction envelope; no surveyed junction boundary.')
        if node.get('area_normalized'):
            basis += ' Self-overlapping pedestrian-corner segments of the source junction outline were normalized to one valid polygon.'
        junction = {'id': identifier, 'center': _geo(node['point']), 'area': _geo(node['area']), 'plan_area': _geo(plan_area),
                    'distance_m': round(distance, 3), 'approach_count': len(approaches), 'basis': basis,
                    'source_hash': sha256(raw).hexdigest(), 'approaches': approaches,
                    'pedestrian_connections': pedestrian_connections,
                    'walking_connection_status': 'mapped' if all(item['walking_connection_status'] == 'mapped' for item in approaches) else 'mixed',
                    'selection_note': 'The selected site stays fixed. The plan uses the nearest connected source intersection, rather than placing a crossing at the selected midblock point.',
                    'assumptions': ['Walking paths are source centerlines, not surveyed curb lines. New sidewalks and landing widths are authored design choices.',
                                    'Derived source envelopes use millimeter coordinate normalization; sub-centimeter gaps are numerical, not mapped features.',
                                    'Source topology establishes connected road legs. Turning movements, signal timing, accessibility and construction feasibility remain unassessed.']}
        return {'junctions': [junction], 'anchors': new_anchors}
    return {'junctions': [], 'anchors': []}


def model_junction_context(junctions, anchors):
    """No raw coordinates, node IDs, street names, or walking geometry leave here."""
    marked = any(anchor['kind'] == 'marked_crossing' for anchor in anchors)
    values = []
    for junction in junctions:
        values.append({key: junction[key] for key in ('id', 'distance_m', 'approach_count', 'basis', 'walking_connection_status', 'selection_note')})
        values[-1]['approaches'] = [{key: approach[key] for key in ('id', 'anchor_id', 'direction', 'width_m', 'plan_width_m',
            'width_basis', 'traffic_direction', 'junction_offset_m', 'outward_sign', 'crossing_offset_m', 'available_length_m', 'crossing_span_m', 'walking_connection_status')}
            for approach in junction['approaches']]
        for summary, approach in zip(values[-1]['approaches'], junction['approaches']):
            summary.update({key: approach[key] for key in ('traffic_flow', 'lane_count', 'direction_basis') if key in approach})
    selected = values[0] if values else None
    direction_supported = selected is not None and all(row['traffic_direction'] == 'two_way' or
        (row['traffic_direction'] == 'one_way' and row.get('traffic_flow') in ('inbound', 'outbound')
         and type(row.get('lane_count')) is int and 1 <= row['lane_count'] <= 8) for row in selected['approaches'])
    walking_width_supported = selected is not None and all(row['plan_width_m'] >=
        (max(row['width_m'], row.get('lane_count', 0)*3) + 2.4 if row['traffic_direction'] == 'one_way' else 8.4)
        for row in selected['approaches'])
    supported = direction_supported and walking_width_supported
    limitation = ('An approach lacks verified travel direction or lane count. Refresh its source data or mark a specific crossing; do not invent opposing traffic.'
                  if not direction_supported else
                  'The available source envelope is too narrow to preserve two traffic lanes and connected pedestrian space. Mark a wider street or sidewalk boundary, or choose another intersection.')
    result = {'design_mode': 'junction' if supported else 'marked_crossing' if marked else 'needs_placement',
            'selected_junction_id': selected['id'] if selected else None,
            'junction_distance_m': selected['distance_m'] if selected else None,
            'approach_count': selected['approach_count'] if selected else 0,
            'junctions': values,
            'design_instruction': 'Create one coordinated intersection_redesign using the selected junction ID and one of its approach anchor IDs. Derive crossings at the junction mouths with connected walking landings, not at arbitrary along-road offsets.' if supported else
                'Use the explicit user-marked crossing alignment.' if marked else
                limitation if selected else
                'No supported connected intersection was found within 120 m. Select an actual intersection or mark the intended crossing.'}
    if selected and not supported and not marked:
        result['question'] = ('An approach has unverified travel direction or lane count. Refresh its source data or mark the specific crossing to design.' if not direction_supported else
                              'The mapped street width cannot fit connected pedestrian space while preserving the required traffic lanes. Mark the actual street and sidewalk boundary, or choose another intersection.')
    return result
