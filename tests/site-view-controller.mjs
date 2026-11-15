import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source=await readFile(new URL('../public/site-view.js',import.meta.url),'utf8');
const good=()=>{
  const scan={modelId:'35LT5s1GSfA',title:'Building Exterior & Loading Docks',url:'https://my.matterport.com/show/?m=35LT5s1GSfA',attachmentDate:'2023-03-01',exteriorHint:true};
  return {status:'linked',property:{id:'6067080',lat:34.0369,lon:-118.2531,name:'Demo property',address:'510 E Olympic Blvd',type:'Industrial'},
    scan,scans:[scan],source:{provider:'CoStar property attachment',association:'Property/model association'},
    limitations:['Scan capture date is not established.','Intervention coverage and map registration are unverified.']};
};
function harness({selected=true}={}) {
  const elements=new Map(),requests=[],frames=[],selections=[],timers=new Map();
  let timerId=0;
  const document={activeElement:null};
  const element=tag=>({tag,events:{},children:[],attributes:{},disabled:false,hidden:false,open:false,isConnected:true,textContent:'',
    addEventListener(name,handler){this.events[name]=handler;},
    setAttribute(name,value){this.attributes[name]=value;},removeAttribute(name){delete this.attributes[name];delete this[name];},
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},
    focus(){if(!this.disabled)document.activeElement=this;},showModal(){this.open=true;},close(){this.open=false;this.events.close?.();},
    getClientRects(){return this.hidden?[]:[{}];},
    getBoundingClientRect(){return{left:20,right:1000,top:20,bottom:700};}});
  const $=id=>{if(!elements.has(id))elements.set(id,element('div'));return elements.get(id);};
  document.createElement=tag=>{const el=element(tag);if(tag==='iframe')frames.push(el);return el;};
  const map={handlers:{},on(name,handler){(this.handlers[name]??=[]).push(handler);},fire(name,event){for(const handler of this.handlers[name]??[])handler(event);}};
  const json=(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));
  const selectProperty=property=>{selections.push(property);map.fire('plannersite',{siteId:'property:'+property.id,property,workflow:'street'});};
  $('open-site-view').focus();
  vm.runInNewContext(source,{$,map,json,selectProperty,planningMode:'street',document,URL,AbortController,
    setTimeout(fn,delay){const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);}});
  if(selected)map.fire('plannersite',{siteId:'property:6067080',property:good().property,workflow:'street'});
  return{$,map,document,requests,frames,selections,timers};
}
const flush=()=>new Promise(setImmediate);
async function open(h,descriptor=good()) {
  h.$('open-site-view').focus();const pending=h.$('open-site-view').events.click();
  h.requests.at(-1).resolve(descriptor);await pending;return h.frames.at(-1);
}

// User initiation, trusted association, native modal focus and an explicitly
// unverified iframe load state. Closing releases its browsing context.
{
  const h=harness();assert.equal(h.requests.length,0);assert.equal(h.frames.length,0);
  const frame=await open(h);
  assert.equal(h.requests[0].url,'/api/site-view?propertyId=6067080');assert.equal(h.selections.length,0);
  assert.equal(h.$('site-view-dialog').open,true);assert.equal(h.document.activeElement,h.$('site-view-close'));
  assert.equal(frame.src,good().scan.url);assert.match(frame.title,/510 E Olympic/);
  assert.match(h.$('site-view-source').textContent,/CoStar/);
  frame.events.load();assert.match(h.$('site-view-status').textContent,/If the tour is blank or unavailable/);
  assert.equal(frame.attributes.allow,'fullscreen');
  assert.doesNotMatch(h.$('site-view-status').textContent,/verified loaded|coverage confirmed/i);
  let prevented=false;h.$('site-view-dialog').events.cancel({preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(h.$('site-view-dialog').open,false);
  assert.equal(frame.src,undefined);assert.equal(h.$('site-view-stage').children.length,0);
  assert.equal(h.$('site-view-external').href,undefined);assert.equal(h.document.activeElement,h.$('open-site-view'));
  frame.events.load();assert.equal(h.$('site-view-stage').children.length,0,'late iframe events cannot restore closed content');
}

// Reject wrong sites/models and URL confusion before selecting any property or
// embedding external content; a backend error remains retryable.
for(const change of [
  d=>{d.property.id='other';},d=>{d.status='invalid';},d=>{d.property.lat=Infinity;},
  d=>{d.scan.modelId='wrong';},d=>{d.scan.url='http://my.matterport.com/show/?m=35LT5s1GSfA';},
  d=>{d.scan.url='https://my.matterport.com.evil.example/show/?m=35LT5s1GSfA';},
  d=>{d.scan.url='https://my.matterport.com@evil.example/show/?m=35LT5s1GSfA';},
  d=>{d.scan.url='https://user@my.matterport.com/show/?m=35LT5s1GSfA';},
  d=>{d.scan.url='https://my.matterport.com/show/?m=other';},
  d=>{d.scan.url='https://my.matterport.com/show/?m=35LT5s1GSfA&m=other';},
  d=>{d.scan.url='https://my.matterport.com/show/?m=35LT5s1GSfA&redirect=other';},
  d=>{d.scan.url='https://my.matterport.com/show/?m=35LT5s1GSfA#other';},
  d=>{d.scan.url='javascript:alert(1)';}
]) {
  const h=harness(),descriptor=good();change(descriptor);await open(h,descriptor);
  assert.equal(h.frames.length,0);assert.equal(h.selections.length,0);assert.equal(h.$('site-view-dialog').open,false);
  assert.equal(h.$('site-view-entry-retry').hidden,false);assert.equal(h.$('open-site-view').disabled,false);
}
{
  const h=harness();const pending=h.$('open-site-view').events.click();
  h.document.activeElement=h.$('site-view-entry-status'); // A disabled opener can lose browser focus.
  h.requests[0].reject(new Error('Linked attachment unavailable'));await pending;
  assert.match(h.$('site-view-entry-status').textContent,/unavailable/);
  assert.equal(h.document.activeElement,h.$('open-site-view'),'failed metadata restores focus after enabling its opener');
  h.$('site-view-entry-retry').focus();const retry=h.$('site-view-entry-retry').events.click();h.requests[1].resolve(good());await retry;
  assert.equal(h.frames.length,1);assert.equal(h.$('site-view-dialog').open,true);
  h.$('site-view-close').events.click();assert.equal(h.document.activeElement,h.$('open-site-view'),'a hidden retry opener falls back to the visible entry button');
}

// Failed embedding has both retry and the verified external URL; retries use a
// new iframe so delayed events from the old document cannot report success.
{
  const h=harness(),first=await open(h);first.events.error();
  assert.equal(first.src,undefined);assert.equal(h.$('site-view-stage').children.length,0);
  assert.match(h.$('site-view-status').textContent,/could not be opened/);
  assert.equal(h.$('site-view-external').href,good().scan.url);
  h.$('site-view-retry').events.click();const second=h.frames.at(-1);
  assert.notEqual(first,second);assert.equal(second.src,good().scan.url);
  const loading=h.$('site-view-status').textContent;first.events.load();assert.equal(h.$('site-view-status').textContent,loading);
  h.$('site-view-dialog').events.click({target:h.$('site-view-dialog'),clientX:50,clientY:50});
  assert.equal(h.$('site-view-dialog').open,true,'clicks inside dialog are not backdrop dismissals');
  h.$('site-view-dialog').events.click({target:h.$('site-view-dialog'),clientX:5,clientY:5});
  assert.equal(h.$('site-view-dialog').open,false);assert.equal(second.src,undefined);
}

// Changing site or workflow invalidates pending metadata and releases existing
// embeds. Refused map selection must never open a scan for an unrelated site.
for(const event of [
  ['plannersite',{siteId:'property:other',workflow:'street'}],
  ['plannerworkspace',{mode:'water',visible:true}],
  ['plannerworkspace',{mode:'street',visible:false}],
]) {
  const h=harness();const pending=h.$('open-site-view').events.click();h.map.fire(...event);
  assert.equal(h.requests[0].options.signal.aborted,true);h.requests[0].resolve(good());await pending;
  assert.equal(h.frames.length,0);assert.equal(h.selections.length,0);assert.equal(h.$('open-site-view').disabled,event[0]==='plannersite');
  assert.doesNotMatch(h.$('site-view-entry-status').textContent,/Checking/,'canceled metadata must not retain a loading message');
  const active=harness(),frame=await open(active);active.map.fire(...event);
  assert.equal(active.$('site-view-dialog').open,false);assert.equal(frame.src,undefined);
}
{
  const h=harness({selected:false});await h.$('open-site-view').events.click();
  assert.equal(h.requests.length,0);assert.equal(h.frames.length,0);
  assert.equal(h.$('open-site-view').disabled,true);

}
console.log('PASS: site-view descriptor validation, user initiation, focus/close cleanup, load/retry failures, stale requests, selection guards and permanently disabled Proposed');

// Multiple valid tours stay on the same site; an unsupported site has no fallback.
{
  const h=harness();const d=good();
  d.scans.push({...d.scan,modelId:'abcdefghijk',title:'Courtyard exterior',url:'https://my.matterport.com/show/?m=abcdefghijk',exteriorHint:true});
  const first=await open(h,d);
  h.$('site-view-tour-choice').events.change({target:{value:'abcdefghijk'}});
  assert.equal(first.src,undefined);assert.match(h.frames.at(-1).src,/abcdefghijk/);
  assert.equal(h.selections.length,0);
  h.$('site-view-close').events.click();
  const pending=h.$('open-site-view').events.click();
  h.requests.at(-1).resolve({status:'unavailable',property:d.property,scans:[],scan:null,message:'No verified tour'});await pending;
  assert.equal(h.$('site-view-dialog').open,false);
  assert.match(h.$('site-view-entry-status').textContent,/No verified tour/);
}

// Coverage hints describe tours; they do not determine whether a verified
// property tour can open. Missing optional metadata has a neutral fallback.
for (const contextLabel of ['Interior','Amenity','Unspecified']) {
  const h=harness(),d=good();
  d.scan.exteriorHint=false;d.scan.contextLabel=contextLabel;d.scan.title=contextLabel==='Unspecified'?null:'Pool';
  d.scan.attachmentDate='invalid date';
  const frame=await open(h,d);
  assert.equal(frame.src,d.scan.url);
  assert.equal(h.$('site-view-dialog').open,true);
  assert.match(h.$('site-view-tour-label').textContent,/\(1\)/);
  assert.equal(h.$('site-view-tour-choice').disabled,true);
  assert.doesNotMatch(h.$('site-view-source').textContent,/Invalid Date/);
  assert.doesNotMatch(h.$('site-view-tour-title').textContent,/title hint|·/,'a single tour shows its plain title');assert.ok(h.$('site-view-tour-title').textContent);
  assert.equal(h.$('site-view-tour-picker').hidden,true,'no selector for one tour');
  assert.match(h.$('site-view-limitations').children[0].textContent,contextLabel==='Unspecified'?/Coverage unspecified/:new RegExp('tour title: '+contextLabel.toLowerCase()),'inferred coverage is a source limit');
  h.$('site-view-close').events.click();
  assert.equal(h.timers.size,0);
}

// One invalid record (even the proposed default) cannot hide the remaining
// property-associated tours. No invalid model URL reaches an iframe.
{
  const h=harness(),d=good(),valid=d.scan;
  d.scan={...valid,modelId:'invalid',url:'javascript:alert(1)'};
  d.scans=[null,d.scan,valid,{...valid}];
  const frame=await open(h,d);
  assert.equal(frame.src,valid.url);
  assert.equal(h.frames.length,1);
  assert.match(h.$('site-view-entry-status').textContent,/1 linked tour.*Some tour records/);
  assert.equal(h.$('site-view-tour-choice').children.length,1);
}

// A local property list has no arbitrary 100-tour eligibility cutoff.
{
  const h=harness(),d=good();
  d.scans=Array.from({length:101},(_,i)=>{
    const modelId=String(i).padStart(11,'0');
    return {...d.scan,modelId,url:'https://my.matterport.com/show/?m='+modelId};
  });
  d.scan=d.scans[100];await open(h,d);
  assert.equal(h.$('site-view-tour-choice').children.length,101);
  const labels=h.$('site-view-tour-choice').children.map(option=>option.textContent);
  assert.equal(new Set(labels).size,101,'tours sharing a title are numbered, never listed as identical entries');
  assert.match(labels[0],/ 1$/);assert.match(labels[100],/ 101$/);
  assert.equal(h.$('site-view-tour-choice').disabled,false);
  assert.equal(h.$('site-view-tour-choice').value,d.scan.modelId);
}

// A slow iframe gets a helpful fallback without asserting cross-origin
// playback success. Retry, switching, load and close cancel obsolete timers.
{
  const h=harness(),d=good();
  d.scans.push({...d.scan,modelId:'abcdefghijk',title:'Fitness Center',contextLabel:'Amenity',exteriorHint:false,url:'https://my.matterport.com/show/?m=abcdefghijk'});
  const first=await open(h,d),slow=[...h.timers.values()][0];
  assert.equal(slow.delay,12000);slow.fn();
  assert.match(h.$('site-view-status').textContent,/taking longer/);
  assert.equal(h.$('site-view-retry').disabled,false);
  assert.equal(h.$('site-view-external').href,d.scan.url);
  h.$('site-view-retry').events.click();
  assert.equal(h.timers.size,1);
  const retried=h.frames.at(-1),loading=h.$('site-view-status').textContent;
  slow.fn();assert.equal(h.$('site-view-status').textContent,loading);
  assert.equal(first.src,undefined);
  retried.events.load();assert.equal(h.timers.size,0);
  assert.doesNotMatch(h.$('site-view-status').textContent,/playback verified|successfully loaded/i);
  h.$('site-view-tour-choice').events.change({target:{value:'abcdefghijk'}});
  assert.equal(h.timers.size,1);assert.equal(retried.src,undefined);
  assert.equal(h.$('site-view-tour-title').textContent,'','the selector already names the chosen tour');assert.equal(h.$('site-view-tour-picker').hidden,false);
  assert.match(h.$('site-view-limitations').children[0].textContent,/tour title: amenity/);
  const stale=[...h.timers.values()][0];
  h.map.fire('plannersite',{siteId:'property:other',property:{...d.property,id:'other'},workflow:'street'});
  assert.equal(h.timers.size,0);assert.equal(h.$('site-view-dialog').open,false);
  const current=h.$('site-view-status').textContent;stale.fn();assert.equal(h.$('site-view-status').textContent,current);
}
console.log('PASS: all associated tour contexts, individual-record isolation, optional metadata, tour counts and slow-viewer recovery');

// Valid tours remain accessible alongside explicit source-association gaps.
{
  const h=harness(),d=good();
  d.excludedTourCount=2;
  d.exclusions=[{reason:'missing_attachment',count:2,message:'No matching property attachment confirms these links.'},null,{count:'bad',message:'Do not display'}];
  await open(h,d);
  assert.equal(h.$('site-view-dialog').open,true);
  assert.match(h.$('site-view-entry-status').textContent,/1 linked tour.*2 additional tour links could not be verified/);
  const notes=h.$('site-view-limitations').children.map(child=>child.textContent).join(' ');
  assert.match(notes,/2 tour links omitted: No matching property attachment/);
  assert.doesNotMatch(notes,/Do not display/);
}
console.log('PASS: partial association exclusions remain visible alongside playable tour choices');
