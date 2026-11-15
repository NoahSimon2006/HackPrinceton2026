/* Curated Hancock Terrace demonstration. Source footprints are metric geometry;
 * materials, planting, drainage details and all vertical dimensions are authored
 * conceptual design. This is not a scan or a hydraulic simulation. */
import * as THREE from './vendor/three.module.js';
import {OrbitControls} from './vendor/OrbitControls.js';
import {buildPolygonGeometries} from './concept-scene-renderer.js';
import {eventVolumes} from './demo-math.js';

const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
const polygons=g=>g.type==='MultiPolygon'?g.coordinates:[g.coordinates];
const allPoints=g=>polygons(g).flat(2);
const boxOf=g=>{const p=allPoints(g);return [Math.min(...p.map(v=>v[0])),Math.min(...p.map(v=>v[1])),Math.max(...p.map(v=>v[0])),Math.max(...p.map(v=>v[1]))];};
const rectangle=(a,b,c,d)=>({type:'Polygon',coordinates:[[[a,b],[c,b],[c,d],[a,d],[a,b]]]});
function inRing(x,y,ring){let c=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++)if(((ring[i][1]>y)!==(ring[j][1]>y))&&(x<(ring[j][0]-ring[i][0])*(y-ring[i][1])/(ring[j][1]-ring[i][1])+ring[i][0]))c=!c;return c;}
const inside=(x,y,g)=>polygons(g).some(r=>inRing(x,y,r[0])&&!r.slice(1).some(h=>inRing(x,y,h)));
function random(seed=813){return()=>{seed|=0;seed=seed+0x6D2B79F5|0;let t=Math.imul(seed^seed>>>15,1|seed);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}

export function createDemoScene(container,data,{onError=()=>{},onSelect=()=>{},onFrame=()=>{}}={}){
  if(!container||!Array.isArray(data?.cells)||!data.cells.length||!Array.isArray(data.buildings))throw new Error('The saved demonstration geometry is unavailable.');
  const rng=random(), scene=new THREE.Scene(), camera=new THREE.PerspectiveCamera(38,1,.1,700);
  const resources={geometries:new Set(),materials:new Set(),textures:new Set()};
  const geo=g=>(resources.geometries.add(g),g), mat=m=>(resources.materials.add(m),m);
  const texture=t=>(resources.textures.add(t),t);
  const color=(c,extra={})=>mat(new THREE.MeshStandardMaterial({color:c,roughness:.86,...extra}));
  const buildingGroup=new THREE.Group(), groundGroup=new THREE.Group(), existingGroup=new THREE.Group(), proposedGroup=new THREE.Group(), sectionGroup=new THREE.Group();
  scene.add(groundGroup,buildingGroup,existingGroup,proposedGroup,sectionGroup);sectionGroup.visible=false;
  const bounds=data.bounds||[-58,-67,37,29], street={westX:-39,eastX:-25.4,minY:-62,maxY:24,...data.street};
  const cells=data.cells.map((c,i)=>({...c,id:c.id||`cell-${i+1}`,bounds:boxOf(c.geometry),depthM:c.depthM??.15}));
  const c0=cells[0], centerY=cells.reduce((s,c)=>s+(c.bounds[1]+c.bounds[3])/2,0)/cells.length;
  const focus=new THREE.Vector3(-22,1.2,-centerY), cellMeshes=[], flowParticles=[], waterSurfaces=[], hotspots=[];
  let renderer,controls,observer,disposed=false,failed=false,paused=false,frame=0,mode='proposed',view='overview',rain=0,autoRotate=false,dirty=true,lastTime=0,elapsed=0;
  let rainCloud,dropPositions,dropGeometry,moveFrom,moveTo,moveStarted=0,sectionWater;
  const solidGeo=geo(new THREE.BoxGeometry(1,1,1)), sphereGeo=geo(new THREE.SphereGeometry(1,9,7)), cylinderGeo=geo(new THREE.CylinderGeometry(1,1,1,10));
  const pavement=color(0xc6c5b7), concrete=color(0xdfdcd0), darkConcrete=color(0x999d91), white=color(0xe9e6d8), iron=color(0x303e35,{metalness:.5,roughness:.45});
  const glass=color(0x536d68,{metalness:.3,roughness:.28}), trim=color(0x607d63), plinth=color(0x597360);
  const trunkMat=color(0x725948), leafMat=color(0x527a3d,{side:THREE.DoubleSide}), barkMat=color(0x76674d), wood=color(0xa97745);
  const asphalt=color(0x696e6a), soilMat=color(0x57493a), mulchMat=color(0x6a5641), pebbleMat=color(0xb3b3a1), gravelMat=color(0xaaa99a);
  const waterMat=mat(new THREE.MeshPhysicalMaterial({color:0x51b5b1,transparent:true,opacity:.54,roughness:.16,metalness:.18,clearcoat:1,side:THREE.DoubleSide,depthWrite:false}));

  function mesh(geometry,material,parent,x=0,y=0,z=0){const m=new THREE.Mesh(geometry,material);m.position.set(x,y,z);m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;}
  function block(parent,x,y,z,w,h,d,material){const m=mesh(solidGeo,material,parent,x,y,z);m.scale.set(w,h,d);return m;}
  function sphere(parent,x,y,z,r,material,scale=[1,1,1]){const m=mesh(sphereGeo,material,parent,x,y,z);m.scale.set(r*scale[0],r*scale[1],r*scale[2]);return m;}
  function cylinder(parent,a,b,r,material,rTop=r){const delta=b.clone().sub(a),g=rTop===r?cylinderGeo:geo(new THREE.CylinderGeometry(rTop/r,1,1,10));const m=mesh(g,material,parent);m.position.copy(a).add(b).multiplyScalar(.5);m.scale.set(r,delta.length(),r);m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),delta.normalize());return m;}
  function line(parent,points,c=0x889688,opacity=1){const l=new THREE.Line(geo(new THREE.BufferGeometry().setFromPoints(points)),mat(new THREE.LineBasicMaterial({color:c,transparent:opacity<1,opacity})));parent.add(l);return l;}
  function surface(g,parent,material,height=0,base=0){return buildPolygonGeometries(g,height).map(raw=>{const m=mesh(geo(raw),material,parent,0,base,0);return m;});}
  function label(text,position,parent,size=2,colorText='#26463d'){
    const canvas=document.createElement('canvas');canvas.width=512;canvas.height=96;
    const ctx=canvas.getContext('2d');ctx.fillStyle='rgba(247,247,238,.94)';ctx.beginPath();ctx.roundRect(1,1,510,94,18);ctx.fill();ctx.fillStyle=colorText;ctx.textAlign='center';ctx.textBaseline='middle';ctx.font='600 32px system-ui';ctx.fillText(text,256,48);
    const tx=texture(new THREE.CanvasTexture(canvas));tx.colorSpace=THREE.SRGBColorSpace;
    const sprite=new THREE.Sprite(mat(new THREE.SpriteMaterial({map:tx,depthTest:false,transparent:true,toneMapped:false,fog:false})));sprite.position.copy(position);sprite.scale.set(size*5.33,size,1);parent.add(sprite);return sprite;
  }
  function proceduralTexture(kind){
    const cvs=document.createElement('canvas');cvs.width=cvs.height=256;const ctx=cvs.getContext('2d');
    ctx.fillStyle=kind==='asphalt'?'#858b83':'#a5b087';ctx.fillRect(0,0,256,256);
    for(let i=0;i<8000;i++){const v=Math.floor(95+rng()*90);ctx.fillStyle=kind==='asphalt'?`rgba(${v},${v},${v},.18)`:`rgba(${v*.8},${v},${v*.65},.2)`;ctx.fillRect(rng()*256,rng()*256,1+rng()*2,1+rng()*2);}
    const tx=texture(new THREE.CanvasTexture(cvs));tx.colorSpace=THREE.SRGBColorSpace;tx.wrapS=tx.wrapT=THREE.RepeatWrapping;tx.repeat.set(8,8);return tx;
  }
  asphalt.map=proceduralTexture('asphalt');
  const turfMat=color(0xb1bc8a,{map:proceduralTexture('turf')});

  function makeGround(){
    const [x0,y0,x1,y1]=bounds;
    block(groundGroup,(x0+x1)/2,-1.2,-(y0+y1)/2,x1-x0,1.9,y1-y0,color(0xd2c7ad));
    // The exposed board gives the illustration a deliberate architectural model edge.
    block(groundGroup,(x0+x1)/2,-2.18,-(y0+y1)/2,x1-x0+.2,.1,y1-y0+.2,color(0x5e6b5e));
    surface(rectangle(x0,y0,x1,y1),groundGroup,color(0xc3c1ab),0,-.24);
    surface(rectangle(street.westX,y0,street.eastX,y1),groundGroup,asphalt,.08,-.12);
    const walk=rectangle(street.eastX-.025,y0,-19.45,y1);
    // Proposed cells are genuine holes in this presentation's paving, allowing
    // the soil and water surface to remain visible below the reference grade.
    walk.coordinates.push(...cells.flatMap(c=>polygons(c.geometry).map(r=>[...r[0]].reverse())));
    surface(walk,groundGroup,pavement,.18,-.08);
    for(let y=y0+2;y<y1;y+=2.5){
      line(groundGroup,[new THREE.Vector3(-23,.106,-y),new THREE.Vector3(-19.45,.106,-y)],0x9a9f93,.7);
      if(!cells.some(c=>y>c.bounds[1]&&y<c.bounds[3]))line(groundGroup,[new THREE.Vector3(street.eastX,.106,-y),new THREE.Vector3(-23,.106,-y)],0x9a9f93,.6);
    }
    line(groundGroup,[new THREE.Vector3(-21.2,.108,-y0),new THREE.Vector3(-21.2,.108,-y1)],0xb0b0a3,.65);
    // Curb segments preserve both planting openings and the central access gap.
    for(let y=y0;y<y1;y+=.5)if(!cells.some(c=>y>c.bounds[1]-.15&&y<c.bounds[3]+.15))block(groundGroup,street.eastX+.08,.095,-y,.18,.28,.5,concrete);
    block(groundGroup,street.westX-.12,.08,-(y0+y1)/2,.24,.32,y1-y0,concrete);
    surface(rectangle(street.westX-5,y0,street.westX-.2,y1),groundGroup,pavement,.17,-.07);
    for(let y=y0;y<y1;y+=3)line(groundGroup,[new THREE.Vector3(street.westX-5,.103,-y),new THREE.Vector3(street.westX-.2,.103,-y)],0xa3a99b,.7);
    // A quiet parking edge: no invented traffic capacity or circulation result.
    for(let y=y0+3;y<y1;y+=8)block(groundGroup,street.westX+2.5,-.031,-y,.09,.006,3.2,white);
    for(const y of [-49,14]){
      const car=new THREE.Group();car.position.set(-27.3,.12,-y);groundGroup.add(car);
      const body=color(y<0?0x657d7b:0xd2ccba,{metalness:.3,roughness:.38});
      block(car,0,.61,0,1.65,.67,4.05,body);block(car,0,1.1,.1,1.43,.54,2.1,body);
      block(car,0,1.15,-1,1.35,.42,.045,color(0x506669,{metalness:.4,roughness:.2}));
      block(car,0,1.15,1.2,1.35,.42,.045,color(0x506669,{metalness:.4,roughness:.2}));
      for(const x of [-.85,.85]){block(car,x,1.18,.1,.025,.38,1.85,color(0x506669));for(const z of [-1.3,1.3]){const tire=mesh(geo(new THREE.CylinderGeometry(.32,.32,.18,14)),color(0x343a37),car,x,.32,z);tire.rotation.z=Math.PI/2;}}
      block(car,0,.55,-2.04,1.4,.12,.04,white);
    }
  }

  function makeBuilding(b){
    const height=b.height||9.6,main=Boolean(b.primary),body=color(main?0x849a79:0xc4c5b5),roof=color(main?0xa7ae98:0xb8bcaa);
    surface(b.geometry,buildingGroup,body,height,.1);surface(b.geometry,buildingGroup,roof,.11,height+.1);
    const g=new THREE.Group();buildingGroup.add(g);
    for(const rings of polygons(b.geometry)){
      const ring=rings[0];let signed=0;for(let i=0;i<ring.length-1;i++)signed+=ring[i][0]*ring[i+1][1]-ring[i+1][0]*ring[i][1];
      for(let i=0;i<ring.length-1;i++){
        const a=ring[i],b2=ring[i+1],dx=b2[0]-a[0],dy=b2[1]-a[1],length=Math.hypot(dx,dy);if(length<1)continue;
        const nx=(signed>0?dy:-dy)/length,ny=(signed>0?-dx:dx)/length;
        const edge=new THREE.Group();edge.position.set(a[0],.1,-a[1]);edge.rotation.y=Math.atan2(dy,dx);g.add(edge);
        // Horizontal trim follows the true extracted perimeter.
        block(edge,length/2,height-.25,0,length,.26,.25,main?trim:darkConcrete);
        block(edge,length/2,.3,0,length,.6,.12,main?plinth:darkConcrete);
        if(!main)continue;
        const floors=Math.max(1,Math.round(height/3.2)), bays=Math.floor(length/3.35);
        for(let n=0;n<bays;n++)for(let level=0;level<floors;level++){
          const t=(n+.5)/bays,x=a[0]+dx*t+nx*.08,y=a[1]+dy*t+ny*.08;
          const win=new THREE.Group();win.position.set(x,1.4+level*3.1,-y);win.rotation.y=Math.atan2(dy,dx);g.add(win);
          block(win,0,0,0,1.5,1.6,.12,white);
          block(win,0,0,.076,1.31,1.39,.035,glass);
          // Both faces are authored since source footprints do not supply facade normals.
          block(win,0,0,-.076,1.31,1.39,.035,glass);
          block(win,0,0,.1,.045,1.43,.05,white);block(win,0,0,-.1,.045,1.43,.05,white);
          block(win,0,-.82,0,1.7,.12,.35,white);
        }
        for(let level=1;level<floors;level++)block(edge,length/2,level*3.1-.3,0,length,.13,.18,white);
      }
      const bnd=boxOf({type:'Polygon',coordinates:rings});
      if(main){
        // Roof furniture is visibly an architectural illustration, not extracted evidence.
        for(let k=0;k<5;k++){const x=bnd[0]+7+(k%2)*12,y=bnd[1]+7+k*6;if(inside(x,y,b.geometry)){block(g,x,height+.5,-y,2.2,.65,1.6,darkConcrete);block(g,x,height+.85,-y,2.35,.08,1.75,iron);}}
      }
    }
  }

  function palm(x,y,height=10){
    const p=new THREE.Group();p.position.set(x,.1,-y);buildingGroup.add(p);
    cylinder(p,new THREE.Vector3(0,0,0),new THREE.Vector3(.3,height,0),.17,trunkMat,.11);
    for(let j=0;j<10;j++){
      const angle=j*Math.PI*2/10+rng()*.3, length=2.6+rng(),points=[];
      for(let k=0;k<6;k++){const t=k/5;points.push(new THREE.Vector3(.3+Math.cos(angle)*length*t,height+.55*Math.sin(t*Math.PI)-1.15*t*t,Math.sin(angle)*length*t));}
      const curve=new THREE.CatmullRomCurve3(points);mesh(geo(new THREE.TubeGeometry(curve,8,.035,4,false)),barkMat,p);
      for(let k=1;k<11;k++){
        const t=k/12,pt=curve.getPoint(t),w=.65*Math.sin(t*Math.PI),frond=mesh(geo(new THREE.PlaneGeometry(w*1.8,.2)),leafMat,p,pt.x,pt.y,pt.z);
        frond.rotation.set(-.5,angle,Math.sin(angle)*.3);frond.rotateZ(angle);frond.scale.y=.7;
      }
    }
  }

  function shadeTree(parent,x,y,height=4.4){
    const g=new THREE.Group();g.position.set(x,.1,-y);parent.add(g);
    cylinder(g,new THREE.Vector3(),new THREE.Vector3(.1,height*.7,0),.11,trunkMat,.045);
    for(let j=0;j<5;j++){
      const a=j*1.26;const end=new THREE.Vector3(Math.cos(a)*.9,height*.8,Math.sin(a)*.9);
      cylinder(g,new THREE.Vector3(.05,height*.48,0),end,.045,trunkMat,.014);
    }
    const count=210,leaves=new THREE.InstancedMesh(sphereGeo,leafMat,count),dummy=new THREE.Object3D();
    for(let i=0;i<count;i++){
      const a=rng()*Math.PI*2,r=Math.sqrt(rng())*1.7,h=(rng()-.5)*1.8;
      dummy.position.set(Math.cos(a)*r,height+h,Math.sin(a)*r);dummy.scale.set(.22+rng()*.25,.09+rng()*.13,.22+rng()*.25);dummy.rotation.set(rng(),rng()*6,rng());dummy.updateMatrix();leaves.setMatrixAt(i,dummy.matrix);leaves.setColorAt(i,new THREE.Color().setHSL(.22+rng()*.07,.27+rng()*.17,.24+rng()*.16));
    }
    leaves.castShadow=true;leaves.receiveShadow=true;g.add(leaves);
    // Stakes and mulch ring make the proposed tree read as a tangible intervention.
    for(const dx of [-.45,.45])cylinder(g,new THREE.Vector3(dx,0,0),new THREE.Vector3(dx,2.2,0),.035,wood);
    cylinder(g,new THREE.Vector3(-.45,1.8,0),new THREE.Vector3(.45,1.8,0),.02,iron);
  }

  function grassPatch(parent,c){
    const b=c.bounds,positions=[],flowerPositions=[];
    for(let i=0;i<160;i++){
      const x=b[0]+.27+rng()*(b[2]-b[0]-.54),y=b[1]+1.15+rng()*(b[3]-b[1]-2.3);
      if(inside(x,y,c.geometry))positions.push([x,y]);
    }
    const bladeGeo=geo(new THREE.ConeGeometry(.036,.7,3)),blades=new THREE.InstancedMesh(bladeGeo,leafMat,positions.length*7),dummy=new THREE.Object3D();
    let n=0;
    for(const [x,y]of positions){
      for(let j=0;j<7;j++){const h=.45+rng()*.5,a=rng()*Math.PI*2;
        dummy.position.set(x+Math.cos(a)*.13,-c.depthM+h*.44,-y+Math.sin(a)*.13);dummy.scale.set(1,h/.7,1);dummy.rotation.set((rng()-.5)*.55,a,(rng()-.5)*.5);dummy.updateMatrix();blades.setMatrixAt(n,dummy.matrix);blades.setColorAt(n,new THREE.Color().setHSL(.19+rng()*.08,.3,.25+rng()*.18));n++;
      }
      if(rng()>.68)flowerPositions.push([x,y]);
    }
    blades.castShadow=true;blades.receiveShadow=true;parent.add(blades);
    const flowers=new THREE.InstancedMesh(sphereGeo,color(0xb49cbd),flowerPositions.length*3);n=0;
    for(const[x,y]of flowerPositions)for(let j=0;j<3;j++){
      dummy.position.set(x+(rng()-.5)*.2,.5+rng()*.24,-y+(rng()-.5)*.2);dummy.scale.set(.06,.11,.06);dummy.rotation.set(0,0,0);dummy.updateMatrix();flowers.setMatrixAt(n,dummy.matrix);flowers.setColorAt(n,new THREE.Color(rng()>.4?0xa69aba:0xd0b982));n++;
    }flowers.castShadow=true;parent.add(flowers);
  }

  function makeCell(c,index){
    const g=new THREE.Group();g.userData.cellId=c.id;proposedGroup.add(g);
    const b=c.bounds,cx=(b[0]+b[2])/2,cy=(b[1]+b[3])/2,w=b[2]-b[0],length=b[3]-b[1];
    surface(c.geometry,existingGroup,turfMat,.12,0);
    const soil=surface(c.geometry,g,soilMat,.62,-.62-c.depthM);soil.forEach(m=>{m.userData.hotspot='planting';cellMeshes.push(m);});
    surface(c.geometry,g,mulchMat,.035,-c.depthM);
    // Narrow cast edges, a distinct stone inlet apron and a small overflow grate.
    for(const x of [b[0]+.07,b[2]-.07])block(g,x,-.06,-cy,.14,.36,length,concrete);
    for(const y of [b[1]+.07,b[3]-.07])block(g,cx,-.06,-y,w,.36,.14,concrete);
    const inletY=b[3]-.6,overflowY=b[1]+.75;
    block(g,b[0]+.08,-.02,-inletY,.22,.18,.7,darkConcrete);
    block(g,cx,-c.depthM+.01,-inletY,w-.32,.11,.95,pebbleMat);
    for(let j=0;j<38;j++){const x=b[0]+.24+rng()*(w-.48),y=inletY+(rng()-.5)*.7;sphere(g,x,-c.depthM+.09,-y,.06+rng()*.06,pebbleMat,[1.2,.7,1]);}
    block(g,cx,.035,-overflowY,.48,.12,.55,iron);
    for(let j=0;j<6;j++)block(g,cx,.101,-overflowY-.22+j*.085,.43,.012,.024,darkConcrete);
    grassPatch(g,c);
    shadeTree(g,cx,b[1]+2.5,4.1);
    const water=surface(c.geometry,g,waterMat,0,-c.depthM+.02);water.forEach(m=>{m.visible=false;m.renderOrder=3;waterSurfaces.push({mesh:m,depth:c.depthM});});
    // Slow moving luminous beads explain the proposed path; they are not water particles from a solver.
    for(let j=0;j<18;j++){
      const bead=sphere(g,0,.1,0,.047,color(0x79d5d5,{emissive:0x2c8a97,emissiveIntensity:.4}));bead.visible=false;
      flowParticles.push({mesh:bead,phase:j/18,x:cx,startY:b[3]-.65,endY:b[1]+.8,depth:c.depthM});
    }
    if(index===0)hotspots.push({id:'inlet',position:new THREE.Vector3(b[0],.5,-inletY)});
    if(index===cells.length-1)hotspots.push({id:'overflow',position:new THREE.Vector3(cx,.45,-overflowY)});
    if(index===0)hotspots.push({id:'planting',position:new THREE.Vector3(cx,.6,-cy)});
  }

  function fence(){
    // An illustrative frontage fence reflects the exterior reference photo;
    // the wide center opening is deliberately preserved for access.
    for(const[y0,y1]of [[-45,-26],[-8,7]]){
      const x=-18.65;
      for(let y=y0;y<y1;y+=.34)block(buildingGroup,x,.9,-y,.025,1.6,.025,iron);
      for(const h of [.45,1.6])block(buildingGroup,x,h,-(y0+y1)/2,.045,.04,y1-y0,iron);
      for(let y=y0;y<=y1;y+=2.5)block(buildingGroup,x,.9,-y,.06,1.75,.06,iron);
    }
  }

  function makeSection(){
    const x=-24.2,z=-((c0.bounds[1]+c0.bounds[3])/2),depth=c0.depthM;
    const section=new THREE.Group();section.position.set(x,0,z);sectionGroup.add(section);
    const layers=[{y:-.05-depth,h:.18,m:mulchMat,name:'Mulch + planting',height:.35},
      {y:-.41-depth,h:.55,m:color(0x967955),name:'Bioretention soil',height:-.41-depth},
      {y:-.8-depth,h:.22,m:color(0xc0b69b),name:'Transition layer',height:-.8-depth},
      {y:-1.12-depth,h:.42,m:gravelMat,name:'Drainage aggregate',height:-1.12-depth}];
    layers.forEach((l,i)=>{const labelY=.9-i*.66;block(section,0,l.y,0,2.4,l.h,4.5,l.m);label(l.name,new THREE.Vector3(4.15,labelY,0),section,.48);line(section,[new THREE.Vector3(1.24,l.height,0),new THREE.Vector3(2.25,labelY,0),new THREE.Vector3(2.75,labelY,0)],0x5b7265);});
    block(section,0,-1.45-depth,0,2.5,.08,4.6,darkConcrete);
    for(let i=0;i<130;i++)sphere(section,(rng()-.5)*2.25,-1.16-depth+(rng()-.5)*.22,(rng()-.5)*4.35,.045+rng()*.065,pebbleMat,[1.3,.8,1]);
    cylinder(section,new THREE.Vector3(-.55,-1.08-depth,-2.4),new THREE.Vector3(-.55,-1.08-depth,2.4),.11,color(0x4f777a));
    for(let i=0;i<18;i++){
      const z0=-2.15+i*.25;const ring=mesh(geo(new THREE.TorusGeometry(.112,.012,5,12)),darkConcrete,section,-.55,-1.08-depth,z0);ring.rotation.x=0;
    }
    const planting=rectangle(x-1.2,-z-2.25,x+1.2,-z+2.25);grassPatch(sectionGroup,{geometry:planting,bounds:boxOf(planting),depthM:depth});
    sectionWater=block(section,0,-depth*.5,0,2.22,depth,4.32,waterMat);sectionWater.visible=false;
    label('Assumed ponding · '+Math.round(depth*100)+' cm',new THREE.Vector3(0,1.1,-3),section,.45);
    label('Illustrative section · not a surveyed detail',new THREE.Vector3(0,-2.1-depth,0),section,.36);
  }

  function createRain(){
    const count=600;dropPositions=new Float32Array(count*6);
    for(let i=0;i<count;i++){const x=-29+rng()*13,z=-street.minY-rng()*(street.maxY-street.minY),h=rng()*16;dropPositions.set([x,h,z,x-.04,h-.35,z+.07],i*6);}
    dropGeometry=geo(new THREE.BufferGeometry());dropGeometry.setAttribute('position',new THREE.BufferAttribute(dropPositions,3));
    rainCloud=new THREE.LineSegments(dropGeometry,mat(new THREE.LineBasicMaterial({color:0x8bb9c4,transparent:true,opacity:.4,depthWrite:false})));rainCloud.visible=false;scene.add(rainCloud);
  }

  // Repeated facade trim, paving, stones and fence posts share instanced draws.
  // Preserve independently animated water/flow meshes and click targets.
  function batchStatic(parent){
    scene.updateMatrixWorld(true);const inverse=parent.matrixWorld.clone().invert(),groups=new Map();
    const excluded=new Set([...cellMeshes,...waterSurfaces.map(p=>p.mesh),...flowParticles.map(p=>p.mesh),sectionWater]);
    parent.traverse(o=>{if(!o.isMesh||o.isInstancedMesh||excluded.has(o)||Array.isArray(o.material))return;
      const key=o.geometry.uuid+o.material.uuid;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(o);
    });
    for(const items of groups.values()){
      if(items.length<3)continue;
      const batch=new THREE.InstancedMesh(items[0].geometry,items[0].material,items.length);
      items.forEach((o,i)=>batch.setMatrixAt(i,inverse.clone().multiply(o.matrixWorld)));
      batch.castShadow=items.some(o=>o.castShadow);batch.receiveShadow=true;
      items.forEach(o=>o.removeFromParent());parent.add(batch);
    }
  }

  const presets={
    overview:{position:new THREE.Vector3(-72,35,40),target:new THREE.Vector3(-22,1.5,-centerY)},
    street:{position:new THREE.Vector3(-34,5.3,-cells[0].bounds[3]-10),target:new THREE.Vector3(-23,1.2,-centerY)},
    plan:{position:new THREE.Vector3(-18,108,-centerY+.01),target:new THREE.Vector3(-18,0,-centerY)},
    section:{position:new THREE.Vector3(-33,4,-(c0.bounds[1]+c0.bounds[3])/2+9),target:new THREE.Vector3(-22.9,-.25,-(c0.bounds[1]+c0.bounds[3])/2)},
  };
  function schedule(){dirty=true;if(!frame&&!disposed&&!failed)frame=requestAnimationFrame(tick);}
  function setView(name){
    if(!(name in presets)||disposed)return;view=name;
    const section=name==='section';buildingGroup.visible=!section;groundGroup.visible=!section;existingGroup.visible=!section&&mode==='existing';proposedGroup.visible=!section&&mode==='proposed';sectionGroup.visible=section;
    rainCloud.visible=!section&&rain>0;
    controls.autoRotate=false;autoRotate=false;
    moveFrom={position:camera.position.clone(),target:controls.target.clone()};moveTo=presets[name];moveStarted=performance.now();schedule();
  }
  function projectHotspots(){
    const w=container.clientWidth,h=container.clientHeight;
    const list=hotspots.map(item=>{const p=item.position.clone().project(camera);return{id:item.id,x:(p.x*.5+.5)*w,y:(-.5*p.y+.5)*h,visible:view!=='section'&&mode==='proposed'&&Math.abs(p.x)<.95&&Math.abs(p.y)<.95&&p.z<1};});
    onFrame(list);
  }
  function snapshotInfo(){return{mode,view,rainMm:rain,autoRotate,cells:cells.length,units:'m',renderedFrames:renderer?.info?.render?.frame??0,camera:{position:camera.position.toArray(),target:controls.target.toArray()},buildingCount:data.buildings.length};}
  function tick(now){
    frame=0;if(disposed||failed||paused)return;
    if(document.hidden||!container.isConnected||!container.clientWidth||!container.clientHeight){lastTime=now;return;}
    const dt=Math.min(.05,(now-(lastTime||now))/1000);lastTime=now;elapsed+=dt;
    if(moveTo){const t=clamp((now-moveStarted)/850,0,1),e=t*t*(3-2*t);camera.position.lerpVectors(moveFrom.position,moveTo.position,e);controls.target.lerpVectors(moveFrom.target,moveTo.target,e);controls.update();if(t===1)moveTo=null;dirty=true;}
    if(autoRotate){controls.update(dt);dirty=true;}
    if(rain>0&&view!=='section'){
      const speed=5+rain*.12;
      for(let i=0;i<dropPositions.length;i+=6){dropPositions[i+1]-=dt*speed;dropPositions[i+4]-=dt*speed;if(dropPositions[i+1]<.2){dropPositions[i+1]=16;dropPositions[i+4]=15.65;}}
      dropGeometry.attributes.position.needsUpdate=true;
      for(const p of flowParticles){const phase=(elapsed*.09+p.phase)%1;p.mesh.position.set(p.x,.025-p.depth*.2,-(p.startY+(p.endY-p.startY)*phase));}
      dirty=true;
    }
    if(dirty){
      dirty=false;try{renderer.render(scene,camera);renderer.domElement.dataset.scene=JSON.stringify(snapshotInfo());projectHotspots();}catch(e){failed=true;onError('The demonstration renderer could not draw this view. Reload to retry.');return;}
    }
    if(!frame&&(moveTo||autoRotate||(rain>0&&view!=='section')))frame=requestAnimationFrame(tick);
  }
  function resize(){if(disposed)return;const w=Math.max(1,container.clientWidth),h=Math.max(1,container.clientHeight);camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h,false);schedule();}
  function visibility(){if(!document.hidden)schedule();}
  function lost(e){e.preventDefault();if(disposed)return;failed=true;cancelAnimationFrame(frame);frame=0;onError('The 3D graphics context was interrupted. Reload this demo to retry.');}
  let pointerStart=null;
  function pointerDown(e){pointerStart=[e.clientX,e.clientY];moveTo=null;}
  function pointerUp(e){if(!pointerStart||Math.hypot(e.clientX-pointerStart[0],e.clientY-pointerStart[1])>6)return;const r=renderer.domElement.getBoundingClientRect(),p=new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),ray=new THREE.Raycaster();ray.setFromCamera(p,camera);const hit=ray.intersectObjects(cellMeshes,false)[0];if(hit&&mode==='proposed'&&view!=='section')onSelect(hit.object.userData.hotspot||'planting');}
  function dispose(){
    if(disposed)return;disposed=true;cancelAnimationFrame(frame);observer?.disconnect();document.removeEventListener('visibilitychange',visibility);controls?.dispose();
    renderer?.domElement.removeEventListener('webglcontextlost',lost);renderer?.domElement.removeEventListener('pointerdown',pointerDown);renderer?.domElement.removeEventListener('pointerup',pointerUp);
    scene.traverse(o=>o.shadow?.dispose());for(const g of resources.geometries)g.dispose();for(const m of resources.materials)m.dispose();for(const t of resources.textures)t.dispose();scene.clear();renderer?.dispose();renderer?.forceContextLoss();renderer?.domElement.remove();
  }

  try{
    renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'high-performance'});renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.7));
    renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;
    renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;
    renderer.domElement.style.cssText='display:block;width:100%;height:100%;touch-action:none;';renderer.domElement.setAttribute('role','img');renderer.domElement.setAttribute('aria-label','Detailed conceptual Hancock Terrace streetscape. Drag to orbit and scroll to zoom.');container.append(renderer.domElement);
    scene.background=new THREE.Color(0xe4e9df);scene.fog=new THREE.Fog(0xe4e9df,125,270);
    scene.add(new THREE.HemisphereLight(0xf9f5e5,0x859180,2.25));
    const sun=new THREE.DirectionalLight(0xffecd2,3.1);sun.position.set(-55,78,-4);sun.target.position.copy(focus);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);sun.shadow.normalBias=.035;sun.shadow.bias=-.0001;Object.assign(sun.shadow.camera,{left:-65,right:65,top:65,bottom:-65,near:1,far:220});scene.add(sun,sun.target);
    const fill=new THREE.DirectionalLight(0xe0edff,.8);fill.position.set(40,25,40);scene.add(fill);
    makeGround();data.buildings.forEach(makeBuilding);cells.forEach(makeCell);fence();
    const trees=data.trees?.length?data.trees:[{x:-17.7,y:-42},{x:-17.8,y:-30},{x:-17.8,y:-6},{x:-17.6,y:5}];trees.forEach(t=>palm(t.x,t.y,t.height||9+rng()*3));
    makeSection();createRain();[buildingGroup,groundGroup,proposedGroup,sectionGroup].forEach(batchStatic);existingGroup.visible=false;
    controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=false;controls.minDistance=3;controls.maxDistance=150;controls.minPolarAngle=.02;controls.maxPolarAngle=Math.PI*.485;controls.autoRotateSpeed=.48;controls.addEventListener('change',schedule);
    camera.position.copy(presets.overview.position);controls.target.copy(presets.overview.target);controls.update();
    renderer.domElement.addEventListener('webglcontextlost',lost);renderer.domElement.addEventListener('pointerdown',pointerDown);renderer.domElement.addEventListener('pointerup',pointerUp);document.addEventListener('visibilitychange',visibility);
    observer=new ResizeObserver(resize);observer.observe(container);resize();
  }catch(e){dispose();throw new Error('Detailed 3D is unavailable: '+(e.message||'graphics initialization failed'));}

  return{
    setMode(value){if(!['existing','proposed'].includes(value)||disposed)return;mode=value;existingGroup.visible=view!=='section'&&mode==='existing';proposedGroup.visible=view!=='section'&&mode==='proposed';schedule();},
    setRain(mm){if(disposed)return;rain=clamp(Number(mm)||0,0,data.scenario?.maxRainMm||50);const volumes=eventVolumes(rain,data.scenario),fill=clamp(volumes.stored/data.scenario.storageM3,0,1);rainCloud.visible=rain>0&&view!=='section';rainCloud.material.opacity=.15+rain/100;for(const p of waterSurfaces){p.mesh.visible=rain>0;p.mesh.position.y=-p.depth+fill*p.depth+.02;}if(sectionWater){sectionWater.visible=rain>0;sectionWater.scale.y=c0.depthM*fill;sectionWater.position.y=-c0.depthM+c0.depthM*fill/2;}for(const p of flowParticles)p.mesh.visible=rain>0;schedule();},
    setView,
    setPaused(value){paused=Boolean(value);if(paused){cancelAnimationFrame(frame);frame=0;}else{lastTime=0;schedule();}},
    setAutoRotate(value){if(disposed)return;autoRotate=Boolean(value);controls.autoRotate=autoRotate;moveTo=null;schedule();},
    reset(){setView('overview');},snapshotInfo,
    exportPng(){if(disposed||failed)throw new Error('The scene is not available.');const ratio=renderer.getPixelRatio();try{renderer.setPixelRatio(2);renderer.render(scene,camera);return renderer.domElement.toDataURL('image/png');}finally{renderer.setPixelRatio(ratio);schedule();}},
    dispose,
  };
}
