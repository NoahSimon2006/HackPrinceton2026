import assert from 'node:assert/strict';
import {buildPolygonGeometries, gardenPlantPositions, groundAroundTreatment} from '../public/concept-scene-renderer.js';

const polygon={type:'Polygon',coordinates:[
  [[0,0],[10,0],[10,10],[0,10],[0,0]],
  [[3,3],[3,7],[7,7],[7,3],[3,3]],
]};
function capArea(geometry,height,checkHole=false) {
  const position=geometry.getAttribute('position'),index=geometry.getIndex();
  let area=0;
  const get=offset=>index?index.getX(offset):offset;
  for(let i=0;i<(index?index.count:position.count);i+=3) {
    const points=[0,1,2].map(j=>{const p=get(i+j);return [position.getX(p),position.getY(p),position.getZ(p)];});
    if(!points.every(p=>Math.abs(p[1]-height)<1e-6))continue;
    const [a,b,c]=points;
    area+=Math.abs((b[0]-a[0])*(c[2]-a[2])-(b[2]-a[2])*(c[0]-a[0]))/2;
    if(checkHole)assert.ok(!points.every(p=>p[0]>3 && p[0]<7 && -p[2]>3 && -p[2]<7),'hole must remain open');
  }
  return area;
}
const [flat]=buildPolygonGeometries(polygon);
assert.equal(capArea(flat,0,true),84);
const [volume]=buildPolygonGeometries(polygon,.15);
assert.equal(capArea(volume,.15),84);
const positions=volume.getAttribute('position');
assert.equal(Math.min(...Array.from({length:positions.count},(_,i)=>positions.getZ(i))),-10,'north maps to negative Z');
assert.ok(Math.abs(Math.max(...Array.from({length:positions.count},(_,i)=>positions.getY(i)))-.15)<1e-6,'meters and vertical depth are unchanged');
const parts=buildPolygonGeometries({type:'MultiPolygon',coordinates:[polygon.coordinates,[[[20,0],[22,0],[22,2],[20,2],[20,0]]]]});
assert.equal(parts.length,2);
assert.equal(parts.reduce((sum,part)=>sum+capArea(part,0),0),88);
assert.throws(()=>buildPolygonGeometries(polygon,Infinity),/height/);
assert.throws(()=>buildPolygonGeometries({type:'LineString',coordinates:[[0,0],[1,1]]}),/polygons/);
for(const geometry of [flat,volume,...parts])geometry.dispose();
console.log('PASS: actual Three.js triangulation preserves holes, multipolygons, meter scale, north orientation and assumed depth');

const treatment={type:'MultiPolygon',coordinates:[polygon.coordinates,[[[13,1],[17,1],[17,3],[13,3],[13,1]]]]};
const plantPositions=gardenPlantPositions(treatment,92);
assert.deepEqual(plantPositions,gardenPlantPositions(treatment,92));
assert.ok(plantPositions.some(([x])=>x<10) && plantPositions.some(([x])=>x>13),'plant both parts');
for(const [x,y] of plantPositions) {
  const holeClearance=Math.hypot(Math.max(3-x,0,x-7),Math.max(3-y,0,y-7));
  const inMain=x>=.2 && x<=9.8 && y>=.2 && y<=9.8 && holeClearance>=.2;
  const inStrip=x>=13.2 && x<=16.8 && y>=1.2 && y<=2.8;
  assert.ok(inMain || inStrip,'each tuft has clearance from the rim and excluded areas');
}
const board=[[-2,-2],[20,-2],[20,14],[-2,14],[-2,-2]];
const ground=buildPolygonGeometries(groundAroundTreatment(board,treatment));
assert.equal(ground.length,2,'the excluded hole remains an island of ground');
assert.equal(ground.reduce((area,part)=>area+capArea(part,0),0),352-92,'only the exact treatment is recessed');
ground.forEach(geometry=>geometry.dispose());
console.log('PASS: the bed preserves exact cutouts and deterministic planting respects rims, holes and disconnected geometry');
