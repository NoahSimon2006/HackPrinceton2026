import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../public/guide.js',import.meta.url),'utf8');
const html=readFileSync(new URL('../public/index.html',import.meta.url),'utf8');
const startsHidden=['site-card','cancel-site-analysis','agent-assessment','proposal-review','water-design-review',
  'traffic-comparison','proposal-result-message','scout-cancel','guide-resume'];
function harness({saved=null}={}) {
  const elements=new Map(),documentEvents={},storage=new Map(saved?[['planning-guide',JSON.stringify(saved)]]:[]);
  let observed=()=>{};
  function element(id) {return {id,children:[],events:{},attributes:{},hidden:startsHidden.includes(id),disabled:false,textContent:'',scrollTop:9,
    addEventListener(type,fn){this.events[type]=fn;},setAttribute(key,value){this.attributes[key]=value;},
    getAttribute(key){return this.attributes[key] ?? null;},removeAttribute(key){delete this.attributes[key];},focus(){this.focused=true;}};}
  const $=id=>{if(!elements.has(id))elements.set(id,element(id));return elements.get(id);};
  const map={handlers:{},on(type,fn){(this.handlers[type]??=[]).push(fn);},fire(type,data={}){for(const fn of this.handlers[type]??[])fn(data);}};
  $('workspace-water').setAttribute('aria-pressed','false');$('planner-status').textContent='Search for a property or select a location on the map.';
  vm.runInNewContext(source,{$,map,Date,JSON,Object,String,Boolean,Math,
    document:{addEventListener(type,fn){(documentEvents[type]??=[]).push(fn);}},
    sessionStorage:{getItem:key=>storage.get(key) ?? null,setItem:(key,value)=>storage.set(key,value)},
    MutationObserver:class {constructor(fn){observed=fn;} observe(){}}});
  const root=$('guide');
  return {$,map,storage,view:()=>root.getAttribute('data-view'),step:()=>root.getAttribute('data-step'),
    tab:()=>root.getAttribute('data-tab'),click:id=>$(id).events.click(),changed:()=>observed(),
    gesture:()=>documentEvents.pointerdown.forEach(fn=>fn({})),
    documentClick:target=>documentEvents.click.forEach(fn=>fn({target})),
    // What planner.js does when a site is selected.
    site(id='site-1',name='First site') {$('site-card').hidden=false;$('site-name').textContent=name;map.fire('plannersite',{siteId:id});}};
}

// The sequence starts at the focus choice, and later steps wait for a site.
{
  const h=harness();
  assert.equal(h.view(),'focus');assert.equal(h.$('guide-back').hidden,true);
  assert.equal(h.$('guide-next').textContent,'Continue');assert.match(h.$('guide-hint').textContent,/find a place/);
  for(const name of ['site','brief','results'])assert.equal(h.$(`guide-step-${name}`).disabled,true,`${name} needs a site`);
  assert.equal(h.$('guide-step-focus').getAttribute('aria-current'),'step');
  h.click('guide-step-results');assert.equal(h.view(),'place','a step without its site falls back to finding a place');
  h.click('guide-step-focus');h.click('guide-next');assert.equal(h.view(),'place');
  assert.equal(h.$('guide-next').hidden,true,'scouting uses its own Find locations action');
  assert.equal(h.$('planner').scrollTop,0);assert.equal(h.$('guide-title-place').focused,true);
  h.click('guide-method-direct');
  assert.equal(h.$('guide-next').hidden,false);assert.equal(h.$('guide-next').disabled,true,'Continue waits for a site');
  assert.equal(h.$('guide-hint').textContent,'','the planner status already says how to set a site');
  assert.equal(JSON.parse(h.storage.get('planning-guide')).method,'direct');
}

// Place guidance offers selection only when a saved location can be selected.
{
  const h=harness();h.click('guide-next');
  h.$('scout-results').children.push({});h.$('scout-results').setAttribute('data-selectable-count','0');h.changed();
  assert.match(h.$('guide-hint').textContent,/Find locations again/,'empty or legacy result cards do not invite an impossible selection');
  h.$('scout-results').setAttribute('data-selectable-count','2');h.changed();
  assert.equal(h.$('guide-hint').textContent,'Choose a location to continue.','saved places remain choices regardless of traffic freshness');
}

// A project restored during page load offers Resume; a site the user picks advances.
{
  const h=harness();h.site();
  assert.equal(h.view(),'focus','restoration is not the user’s move');
  assert.equal(h.$('guide-resume').hidden,false);assert.equal(h.$('guide-resume-name').textContent,'First site');
  h.click('guide-resume-open');assert.equal(h.view(),'brief','no results yet, so resume at the brief');
  h.gesture();h.site('site-2','Second site');assert.equal(h.view(),'site');
  assert.equal(h.$('guide-step-place').getAttribute('data-done'),'true');
  h.click('guide-next');assert.equal(h.view(),'brief');assert.equal(h.$('guide-next').hidden,true,'the brief uses Analyze site');
  h.map.fire('plannersite',{siteId:'site-2'});assert.equal(h.view(),'brief','republishing the same site does not move the user');
  h.map.fire('scoutselect',{});h.map.fire('plannersite',{siteId:'site-2'});
  assert.equal(h.view(),'site','reopening the selected location is still a request to continue');
}

// Detail views belong to the brief; the map view opens from anywhere and returns.
{
  const h=harness();h.gesture();h.site();h.click('guide-next');
  h.click('guide-open-markings');assert.equal(h.view(),'markings');assert.equal(h.step(),'brief');
  assert.equal(h.$('guide-next').textContent,'Done');assert.equal(h.$('guide-back').hidden,true);
  h.$('shape-list').children.push({},{});h.changed();assert.equal(h.$('guide-markings-count').textContent,'2 saved markings');
  h.click('guide-next');assert.equal(h.view(),'brief');assert.equal(h.$('guide-open-markings').focused,true);
  h.click('guide-map');assert.equal(h.view(),'map');assert.equal(h.$('guide-map').getAttribute('aria-pressed'),'true');
  h.click('guide-map');assert.equal(h.view(),'brief');
  h.click('guide-open-settings');h.map.fire('plannerworkspace',{mode:'street'});
  assert.equal(h.view(),'brief','stormwater-only details close outside stormwater');
}

// Starting an analysis shows its progress; finished findings lead; sources open the evidence tab.
{
  const h=harness();h.gesture();h.site();h.click('guide-next');
  h.$('cancel-site-analysis').hidden=false;h.changed();
  assert.equal(h.view(),'results');assert.equal(h.tab(),'assessment');assert.equal(h.$('agent-activity').open,true);
  assert.equal(h.$('guide-next').hidden,true);assert.equal(h.$('guide-skip').hidden,true,'only Cancel is offered during a run');
  h.$('cancel-site-analysis').hidden=true;h.$('agent-assessment').hidden=false;h.changed();
  assert.equal(h.$('agent-activity').open,false);assert.equal(h.$('guide').getAttribute('data-assessment'),'true');
  assert.equal(h.$('guide-next').textContent,'Refine brief');assert.equal(h.$('guide-skip').textContent,'New site');
  h.click('guide-step-site');assert.equal(h.$('guide-skip').textContent,'See results');
  assert.equal(h.$('site-tools').open,false);h.$('site-tools').open=true;
  assert.equal(h.view(),'results');assert.equal(h.tab(),'evidence');assert.equal(h.$('site-tools').open,true);
  h.click('guide-next');assert.equal(h.view(),'brief','Refine brief returns to the brief');
  h.click('guide-step-results');h.click('guide-skip');assert.equal(h.view(),'place','New site returns to finding a place');
}

// Results belong to one focus; a numbered map marker opens the researched locations.
{
  const h=harness();h.gesture();h.site();h.click('guide-step-results');
  h.map.fire('plannerworkspace',{mode:'water'});assert.equal(h.view(),'brief');
  h.$('proposal-review').hidden=false;h.changed();h.click('guide-step-results');
  h.map.fire('plannerworkspace',{mode:'street'});assert.equal(h.view(),'results','existing results stay in view');
  h.click('guide-method-saved');h.documentClick({closest:selector=>selector==='.scout-map-number'?{}:null});
  assert.equal(h.view(),'place');assert.equal(h.$('guide').getAttribute('data-method'),'scout');
}

// A reload in the same tab returns to the saved step once its site is restored.
{
  const h=harness({saved:{step:'brief',method:'direct',tab:'design'}});
  assert.equal(h.view(),'focus','the brief waits for its site');
  h.site();assert.equal(h.view(),'brief');assert.equal(h.tab(),'design');
  const other=harness({saved:{step:'results',method:'scout',tab:'assessment'}});
  other.gesture();other.site();assert.equal(other.view(),'site','a user action replaces the saved step');
}

// Every element the assistant drives exists once in the page.
{
  const ids=new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]));
  for(const match of source.matchAll(/\$\('([a-z-]+)'\)/g))assert.ok(ids.has(match[1]),`guide.js needs #${match[1]} in the page`);
  for(const id of ['focus','place','site','brief','results'].map(name=>`guide-step-${name}`)
    .concat(['scout','direct','saved'].map(name=>`guide-method-${name}`),['assessment','design','evidence','project'].map(name=>`guide-tab-${name}`),
      ['settings','rain','markings'].flatMap(name=>[`guide-open-${name}`,`guide-title-${name}`]),['place','site','brief','results','map'].map(name=>`guide-title-${name}`)))
    assert.ok(ids.has(id),`the page needs #${id}`);
  for(const pane of ['focus','place','site','brief','settings','rain','markings','results','map'])assert.match(html,new RegExp(`data-pane="${pane}"`));
  assert.match(html,/id="run-site-analysis"[^>]*form="site-analysis"/,'the footer action still submits the brief');
  assert.match(html,/id="scout-start"[^>]*form="scout-form"/,'the footer action still submits the area search');
  // Cleanup: controls with nothing behind them are gone, and every aria reference still resolves.
  assert.doesNotMatch(html,/site-view-proposed|site-view-existing|discovery-retry|map-badge|map-eyebrow|footer-caption|traffic-design-guide/);
  assert.match(html,/id="proposal-development" hidden/,'synthetic fixtures are not reachable in normal use');
  assert.match(html,/id="project-files"[^>]*hidden/,'project files stay hidden until there are some');
  for(const match of html.matchAll(/aria-(?:labelledby|describedby|controls)="([^"]+)"/g))
    for(const id of match[1].split(' '))assert.ok(ids.has(id),`aria reference #${id} resolves`);
}
{
  const h=harness();
  assert.equal(h.$('proposal-development').hidden,true,'fixtures need an explicit ?dev');
  assert.equal(h.$('guide-method-saved').hidden,true,'no saved-project route without a saved project');
  h.$('saved-projects').children.push({},{});h.changed();assert.equal(h.$('guide-method-saved').hidden,false);
}
console.log('PASS: guided steps, site gating, restore versus user selection, analysis progress, evidence routing and page wiring');
