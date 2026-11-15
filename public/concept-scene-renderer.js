/* Local metric geometry only. This scene does not measure performance or align a scan. */
import * as THREE from './vendor/three.module.js';
import {OrbitControls} from './vendor/OrbitControls.js';

const PALETTE = {
  background:0x14221e, ground:0x2a4037, grid:0x42594b, gridMajor:0x607464,
  building:0x9cab9c, buildingEdge:0x647c69, parcel:0x91aa90,
  soil:0x71533e, bedWall:0x514338, bedRim:0xb5efaa,
  bike:0x328fae, pedestrian:0xc9ab57, curb:0x799e4c,
  rejected:0xe8a187, contribution:0x6cbace, road:0x52605d,
};
const finite = value => typeof value === 'number' && Number.isFinite(value);

function polygons(geometry) {
  if (geometry?.type === 'Polygon') return [geometry.coordinates];
  if (geometry?.type === 'MultiPolygon') return geometry.coordinates;
  throw new Error('The conceptual footprint must contain polygons.');
}

function pathFor(ring, Type) {
  if (!Array.isArray(ring) || ring.length < 4 || ring.some(point =>
    !Array.isArray(point) || !finite(point[0]) || !finite(point[1]))) {
    throw new Error('A conceptual surface contains an invalid boundary.');
  }
  const path = new Type();
  ring.forEach(([x,y],index) => index ? path.lineTo(x,y) : path.moveTo(x,y));
  path.closePath();
  return path;
}

/** Preserve every polygon ring; extrusion maps metric XY to east / up / south. */
export function buildPolygonGeometries(geometry, depth = 0) {
  if (!finite(depth) || depth < 0 || depth > 100) throw new Error('Invalid conceptual display height.');
  return polygons(geometry).map(rings => {
    if (!Array.isArray(rings) || !rings.length) throw new Error('An empty conceptual surface cannot be drawn.');
    const shape = pathFor(rings[0], THREE.Shape);
    shape.holes = rings.slice(1).map(ring => pathFor(ring,THREE.Path));
    const mesh = depth > 0
      ? new THREE.ExtrudeGeometry(shape,{depth,steps:1,bevelEnabled:false,curveSegments:1})
      : new THREE.ShapeGeometry(shape,1);
    mesh.rotateX(-Math.PI/2);
    return mesh;
  });
}

function bounds(value) {
  if (!Array.isArray(value) || value.length !== 4 || !value.every(finite) ||
      value[2] < value[0] || value[3] < value[1]) throw new Error('The scene extent is unavailable.');
  return value;
}

function niceSpacing(value) {
  const scale = 10 ** Math.floor(Math.log10(Math.max(.1,value)));
  return [1,2,5,10].find(number => number*scale >= value)*scale;
}

function interventionColor(data) {
  if (data.status === 'rejected') return PALETTE.rejected;
  const use = data.design?.new_use || '';
  return use.includes('bike') ? PALETTE.bike : use.includes('pedestrian') ? PALETTE.pedestrian : PALETTE.curb;
}

export function groundAroundTreatment(board, treatment) {
  const parts = polygons(treatment);
  return {type:'MultiPolygon',coordinates:[
    [board,...parts.map(([outer]) => outer)],
    ...parts.flatMap(([, ...holes]) => holes.map(hole => [hole])),
  ]};
}

// Return null close to a boundary so the whole tuft, including its leaves,
// can fit inside the footprint and away from each excluded ring.
function ringLocation(ring, x, y) {
  let inside = false;
  for (let i=1; i<ring.length; i++) {
    const [ax,ay] = ring[i-1], [bx,by] = ring[i];
    const dx = bx-ax, dy = by-ay, squaredLength = dx*dx+dy*dy;
    if (squaredLength) {
      const t = THREE.MathUtils.clamp(((x-ax)*dx+(y-ay)*dy)/squaredLength,0,1);
      if ((x-ax-t*dx)**2+(y-ay-t*dy)**2 < .2**2) return null;
    }
    if ((ay>y)!==(by>y) && x < ax+(y-ay)*dx/dy) inside = !inside;
  }
  return inside;
}

export function gardenPlantPositions(treatment, areaM2) {
  const spacing = Math.max(.38,Math.sqrt(areaM2/1000));
  const result = [];
  for (const [outer,...holes] of polygons(treatment)) {
    const box = new THREE.Box2();
    for (const point of outer) box.expandByPoint(new THREE.Vector2(...point));
    const size = box.getSize(new THREE.Vector2());
    const step = Math.max(spacing,Math.sqrt(size.x*size.y/1600));
    const rows = Math.max(1,Math.floor(size.y/step));
    const columns = Math.max(1,Math.floor(size.x/step));
    for (let row=0; row<rows; row++) {
      for (let column=0; column<columns; column++) {
        const cell = row*columns+column;
        const x = box.min.x+size.x*(column+(row%2 ? .68 : .32)+.21*Math.sin(cell*2.4))/columns;
        const y = box.min.y+size.y*(row+.5+.24*Math.cos(cell*3.93))/rows;
        if (ringLocation(outer,x,y) === true && holes.every(hole => ringLocation(hole,x,y) === false)) {
          result.push([x,y]);
        }
      }
    }
  }
  return result;
}

function tuftGeometry() {
  const vertices = [], indices = [];
  for (let i=0; i<6; i++) {
    const angle = i*2.399963, x = Math.cos(angle), z = Math.sin(angle);
    const tip = .12+(i%3)*.025, height = .29+(i%4)*.069;
    const start = vertices.length/3;
    vertices.push(
      -z*.025,0,x*.025, z*.025,0,-x*.025,
      x*.07-z*.031,height*.56,z*.07+x*.031, x*.07+z*.031,height*.56,z*.07-x*.031,
      x*tip,height,z*tip,
    );
    indices.push(start,start+1,start+2,start+1,start+3,start+2,start+2,start+3,start+4);
  }
  const result = new THREE.BufferGeometry();
  result.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));
  result.setIndex(indices);
  result.computeVertexNormals();
  return result;
}

export function createConceptScene(container, data, {onError = () => {}} = {}) {
  if (!container || data?.schemaVersion !== 1 || data.units !== 'm' ||
      !Array.isArray(data.features) || data.features.length > 1000) {
    throw new Error('This conceptual scene is not a supported metric model.');
  }
  const focusBounds = bounds(data.focusBounds), extent = bounds(data.bounds);
  const water = data.identity.workflow === 'water';
  const rainGarden = water && data.status !== 'rejected';
  const center = new THREE.Vector3((focusBounds[0]+focusBounds[2])/2,0,-(focusBounds[1]+focusBounds[3])/2);
  const focusSpan = Math.max(focusBounds[2]-focusBounds[0],focusBounds[3]-focusBounds[1]);
  const viewSpan = rainGarden ? Math.max(12,focusSpan*1.65) : Math.max(24,focusSpan*1.9);
  const gridStepM = niceSpacing(viewSpan/9);
  const boardSize = Math.ceil(Math.max(viewSpan*2.4,extent[2]-extent[0],extent[3]-extent[1])/gridStepM)*gridStepM;
  const geometries = new Set(), materials = new Set(), textures = new Set();
  const scene = new THREE.Scene(); scene.background = new THREE.Color(PALETTE.background);
  const camera = new THREE.OrthographicCamera(-viewSpan,viewSpan,viewSpan,-viewSpan,.1,Math.max(1500,boardSize*12));
  const base = new THREE.Group(), existing = new THREE.Group(), proposed = new THREE.Group(), context = new THREE.Group();
  scene.add(base,context,existing,proposed);
  existing.visible = false;
  let renderer, controls, observer, scaleLabel, disposed = false, failed = false, pendingFrame = 0, mode = 'proposed';
  const geometry = value => {geometries.add(value); return value;};
  const material = value => {materials.add(value); return value;};
  const solidMaterial = (color, extra={}) => material(new THREE.MeshStandardMaterial({color,roughness:.88,metalness:0,...extra}));
  const lineMaterial = (color, extra={}) => material(new THREE.LineBasicMaterial({color,toneMapped:false,...extra}));

  function line(ring, parent, height, color, opacity=1) {
    const points = ring.map(([x,y]) => new THREE.Vector3(x,height,-y));
    const line = new THREE.Line(geometry(new THREE.BufferGeometry().setFromPoints(points)),lineMaterial(color,{transparent:opacity<1,opacity}));
    parent.add(line);
  }
  function boundaries(feature, parent, height, color, opacity=1) {
    if (['Polygon','MultiPolygon'].includes(feature.geometry?.type)) {
      for (const rings of polygons(feature.geometry)) for (const ring of rings) line(ring,parent,height,color,opacity);
    } else if (feature.geometry?.type === 'LineString') line(feature.geometry.coordinates,parent,height,color,opacity);
    else if (feature.geometry?.type === 'MultiLineString') {
      for (const ring of feature.geometry.coordinates) line(ring,parent,height,color,opacity);
    }
  }
  function addSurface(feature,parent,color,height,offset=0,{opacity=1,edges=false}={}) {
    const top = solidMaterial(color,{transparent:opacity<1,opacity,depthWrite:opacity===1,side:THREE.DoubleSide,
      ...(feature.kind==='intervention'?{emissive:color,emissiveIntensity:.12}:{})});
    const side = solidMaterial(new THREE.Color(color).multiplyScalar(.69),{transparent:opacity<1,opacity,depthWrite:opacity===1});
    for (const shape of buildPolygonGeometries(feature.geometry,height)) {
      geometry(shape);
      const mesh = new THREE.Mesh(shape,height>0?[top,side]:top);
      mesh.position.y = offset; mesh.receiveShadow = true;
      // Translucent context is a display treatment: the source footprint and
      // illustrative building height remain unchanged, while the design stays visible.
      mesh.castShadow = feature.kind === 'building' && opacity===1; parent.add(mesh);
      if (edges) {
        const edge = new THREE.LineSegments(geometry(new THREE.EdgesGeometry(shape,30)),lineMaterial(PALETTE.buildingEdge,{transparent:true,opacity:.55}));
        edge.position.y = offset; parent.add(edge);
      }
    }
  }
  function addRainGarden() {
    const treatment = data.treatment;
    const depth = data.design.storage_depth_m;
    const half = boardSize/2, east = center.x, north = -center.z;
    const board = [[east-half,north-half],[east+half,north-half],[east+half,north+half],
      [east-half,north+half],[east-half,north-half]];
    const tile = document.createElement('canvas');
    tile.width = tile.height = 128;
    const tileContext = tile.getContext('2d');
    tileContext.fillStyle = new THREE.Color(PALETTE.ground).getStyle();
    tileContext.fillRect(0,0,128,128);
    tileContext.fillStyle = new THREE.Color(PALETTE.grid).getStyle();
    tileContext.fillRect(0,0,2,128);
    tileContext.fillRect(0,0,128,2);
    const gridTexture = new THREE.CanvasTexture(tile);
    textures.add(gridTexture);
    gridTexture.colorSpace = THREE.SRGBColorSpace;
    gridTexture.wrapS = gridTexture.wrapT = THREE.RepeatWrapping;
    const groundMaterial = solidMaterial(0xffffff,{map:gridTexture});
    const ground = [
      [existing,{type:'Polygon',coordinates:[board]}],
      [proposed,groundAroundTreatment(board,treatment)],
    ];
    for (const [parent,area] of ground) {
      for (const shape of buildPolygonGeometries(area)) {
        geometry(shape);
        const uv = shape.getAttribute('uv');
        for (let index=0; index<uv.count; index++) uv.setXY(index,uv.getX(index)/gridStepM,uv.getY(index)/gridStepM);
        const mesh = new THREE.Mesh(shape,groundMaterial);
        mesh.receiveShadow = true; parent.add(mesh);
      }
    }

    const bed = {kind:'treatment',geometry:treatment};
    addSurface(bed,proposed,PALETTE.soil,0,-depth);
    const cap = material(new THREE.MeshBasicMaterial({visible:false}));
    const wall = solidMaterial(PALETTE.bedWall,{side:THREE.DoubleSide});
    for (const shape of buildPolygonGeometries(treatment,depth)) {
      const mesh = new THREE.Mesh(geometry(shape),[cap,wall]);
      mesh.position.y = -depth; mesh.receiveShadow = true; proposed.add(mesh);
    }
    boundaries(bed,existing,.012,PALETTE.bedRim,.42);
    boundaries(bed,proposed,.012,PALETTE.bedRim);

    const positions = gardenPlantPositions(treatment,data.areaM2);
    if (!positions.length) return;
    const clusters = new THREE.InstancedMesh(geometry(tuftGeometry()),solidMaterial(0xffffff,{side:THREE.DoubleSide}),positions.length);
    const tuft = new THREE.Object3D();
    const greens = [0x74af53,0x438b47,0xa1c668,0x6da752].map(color => new THREE.Color(color));
    positions.forEach(([x,y],index) => {
      tuft.position.set(x,-depth,-y);
      tuft.rotation.y = index*2.399963;
      tuft.scale.set(1,.85+(index%7)*.095,1);
      tuft.updateMatrix();
      clusters.setMatrixAt(index,tuft.matrix);
      clusters.setColorAt(index,greens[index%greens.length]);
    });
    clusters.castShadow = true;
    proposed.add(clusters);
  }
  function cameraState() {
    return {position:camera.position.toArray(),target:controls.target.toArray(),up:camera.up.toArray(),zoom:camera.zoom,
      frustum:[camera.left,camera.right,camera.top,camera.bottom]};
  }
  function render() {
    if (disposed || failed || pendingFrame) return;
    pendingFrame = requestAnimationFrame(() => {
      pendingFrame = 0;
      if (disposed || failed) return;
      renderer.domElement.dataset.camera = JSON.stringify(cameraState());
      renderer.domElement.dataset.mode = mode;
      try {renderer.render(scene,camera);}
      catch {
        failed=true;
        onError('The 3D view could not be drawn. Close and reopen it; the 2D design is still available.');
      }
    });
  }
  function resize() {
    if (disposed) return;
    const width = Math.max(1,container.clientWidth), height = Math.max(1,container.clientHeight), aspect = width/height;
    // Preserve pose/zoom on resize. The model and modes always share one camera.
    const vertical = viewSpan/2;
    camera.left=-vertical*aspect; camera.right=vertical*aspect; camera.top=vertical; camera.bottom=-vertical;
    camera.updateProjectionMatrix(); renderer.setSize(width,height,false); render();
  }
  function reset() {
    if (disposed || failed) return;
    camera.up.set(0,1,0); camera.zoom=1;
    controls.target.copy(center);
    const view = rainGarden ? new THREE.Vector3(.9,2.05,1.55) : new THREE.Vector3(.6,2.75,.8);
    camera.position.copy(center).add(view.normalize().multiplyScalar(viewSpan*1.6));
    camera.updateProjectionMatrix(); controls.update(); render();
  }
  function contextLost(event) {
    event.preventDefault();
    if (disposed) return;
    failed=true; cancelAnimationFrame(pendingFrame); pendingFrame=0;
    onError('The 3D graphics context was interrupted. Close and reopen the view; the 2D design is still available.');
  }
  function dispose() {
    if (disposed) return;
    disposed=true; cancelAnimationFrame(pendingFrame); pendingFrame=0;
    observer?.disconnect();
    controls?.removeEventListener('change',render); controls?.dispose();
    renderer?.domElement.removeEventListener('webglcontextlost',contextLost);
    for (const item of geometries) item.dispose();
    for (const item of materials) item.dispose();
    for (const item of textures) item.dispose();
    scene.traverse(object => {
      object.shadow?.dispose();
      if (object.isInstancedMesh) object.dispose();
    });
    scene.clear();
    renderer?.dispose(); renderer?.forceContextLoss(); renderer?.domElement.remove();
    scaleLabel?.remove();
  }

  try {
    renderer = new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'low-power'});
    renderer.setPixelRatio(Math.min(2,window.devicePixelRatio || 1));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure=.95;
    renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFShadowMap;
    const canvas = renderer.domElement;
    canvas.style.cssText='display:block;width:100%;height:100%;touch-action:none;';
    canvas.setAttribute('aria-label','Conceptual site model. Drag to orbit; scroll to zoom. Keyboard camera controls are below the model.');
    canvas.setAttribute('role','img'); canvas.dataset.units='m'; canvas.dataset.gridStep=String(gridStepM);
    canvas.dataset.revision=String(data.identity.revision); canvas.dataset.inputHash=data.identity.inputHash;
    canvas.addEventListener('webglcontextlost',contextLost); container.append(canvas);
    scaleLabel=document.createElement('span');
    scaleLabel.textContent=`Grid ${gridStepM} m`;
    scaleLabel.style.cssText='position:absolute;top:12px;left:12px;padding:6px 9px;border:1px solid #627b63;border-radius:6px;background:#10231de8;color:#d9edcd;font:600 11px/1.3 system-ui;letter-spacing:.02em;pointer-events:none;';
    container.append(scaleLabel);
    controls = new OrbitControls(camera,canvas); controls.enableDamping=false;
    controls.minPolarAngle=0; controls.maxPolarAngle=Math.PI/2-.04;
    controls.minZoom=.3; controls.maxZoom=12;
    controls.addEventListener('change',render);

    scene.add(new THREE.HemisphereLight(0xf0fff2,0x435b4a,1.7));
    const sun = new THREE.DirectionalLight(0xfff4d9,2);
    sun.position.copy(center).add(new THREE.Vector3(-viewSpan,viewSpan*1.8,viewSpan*.8));
    sun.target.position.copy(center); sun.castShadow=true;
    sun.shadow.mapSize.set(1024,1024); sun.shadow.normalBias=.06;
    const shadowSpan=viewSpan*1.1;
    Object.assign(sun.shadow.camera,{left:-shadowSpan,right:shadowSpan,top:shadowSpan,bottom:-shadowSpan,near:.1,far:viewSpan*5});
    scene.add(sun,sun.target);
    if (rainGarden) addRainGarden();
    else {
      const board = new THREE.Mesh(geometry(new THREE.PlaneGeometry(boardSize,boardSize)),solidMaterial(PALETTE.ground));
      board.rotation.x=-Math.PI/2; board.position.set(center.x,-.035,center.z); board.receiveShadow=true; base.add(board);
      const grid = new THREE.GridHelper(boardSize,Math.round(boardSize/gridStepM),PALETTE.gridMajor,PALETTE.grid);
      geometry(grid.geometry);
      for (const item of Array.isArray(grid.material)?grid.material:[grid.material]) {item.transparent=true;item.opacity=.5;material(item);}
      grid.position.set(center.x,-.025,center.z); base.add(grid);
    }

    for (const feature of data.features) {
      if (feature.kind === 'parcel') boundaries(feature,context,.008,PALETTE.parcel,.65);
      else if (feature.kind === 'building') addSurface(feature,context,PALETTE.building,feature.heightM,0,{edges:true,opacity:rainGarden ? .22 : .52});
      else if (feature.kind === 'road') {
        if (['Polygon','MultiPolygon'].includes(feature.geometry?.type)) addSurface(feature,context,PALETTE.road,0,.005);
        else boundaries(feature,context,.008,PALETTE.road);
      } else if (feature.kind === 'contributing') {
        addSurface(feature,proposed,PALETTE.contribution,0,.012,{opacity:.25});
        boundaries(feature,proposed,.018,PALETTE.contribution,.9);
      } else if (feature.kind === 'intervention' && !rainGarden) {
        const color = interventionColor(data), depth=feature.heightM || 0;
        const offset=water ? .035-depth : .025;
        addSurface(feature,proposed,color,depth,offset);
        boundaries(feature,proposed,offset+depth+.008,color);
      }
    }

    const marker = new THREE.Group();
    const markerOffset = viewSpan*(rainGarden ? .42 : .32);
    marker.position.set(center.x-markerOffset,.08,center.z+markerOffset);
    const arrow = new THREE.ArrowHelper(new THREE.Vector3(0,0,-1),new THREE.Vector3(),gridStepM,0xc8dec8,gridStepM*.24,gridStepM*.13);
    for (const item of [arrow.line,arrow.cone]) {
      geometry(item.geometry);material(item.material);
      item.material.depthTest=false;item.material.depthWrite=false;item.renderOrder=100;
    }
    marker.add(arrow);
    const label = document.createElement('canvas'); label.width=128; label.height=128;
    const ctx=label.getContext('2d');
    ctx.fillStyle='#142b21';ctx.strokeStyle='#95b58b';ctx.lineWidth=5;
    ctx.beginPath();ctx.arc(64,64,52,0,Math.PI*2);ctx.fill();ctx.stroke();
    ctx.fillStyle='#dcefd1';ctx.font='600 70px system-ui';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText('N',64,65);
    const texture=new THREE.CanvasTexture(label); textures.add(texture); texture.colorSpace=THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(material(new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:false})));
    sprite.scale.set(gridStepM*.65,gridStepM*.65,1); sprite.position.set(0,.15,-gridStepM*1.35); marker.add(sprite); base.add(marker);
    observer = new ResizeObserver(resize); observer.observe(container);
    resize(); reset();
  } catch (error) {
    dispose();
    throw new Error(`Conceptual 3D is unavailable: ${error.message || 'graphics initialization failed'}`);
  }

  return {
    setMode(value) {
      if (!['existing','proposed'].includes(value)) throw new Error('Unknown conceptual view.');
      if (disposed) return;
      mode=value; proposed.visible=value==='proposed'; existing.visible=value==='existing'; render();
    },
    reset,
    top() {
      if (disposed || failed) return;
      const radius=camera.position.distanceTo(controls.target);
      camera.position.copy(controls.target).add(new THREE.Vector3(0,radius,.001));
      controls.update(); render();
    },
    rotate(direction) {
      if (disposed || failed) return;
      const angle = direction==='left'?-Math.PI/12:direction==='right'?Math.PI/12:Number(direction);
      if (!finite(angle)) return;
      camera.position.sub(controls.target).applyAxisAngle(new THREE.Vector3(0,1,0),angle).add(controls.target);
      controls.update(); render();
    },
    zoom(factor) {
      if (disposed || failed || !finite(factor) || factor<=0) return;
      camera.zoom=THREE.MathUtils.clamp(camera.zoom*factor,controls.minZoom,controls.maxZoom);
      camera.updateProjectionMatrix(); controls.update(); render();
    },
    setContextVisible(value) {if (!disposed) {context.visible=Boolean(value);render();}},
    cameraState,
    geometrySummary() {return {units:'m',gridStepM,areaM2:data.areaM2,features:data.features.map(feature=>({id:feature.id,kind:feature.kind,heightM:feature.heightM})),identity:{...data.identity}};},
    dispose,
  };
}
