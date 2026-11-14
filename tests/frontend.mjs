// Offline DOM contract tests: no browser and no network/model requests.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const root = new URL('../', import.meta.url);
const html = await readFile(new URL('public/index.html', root), 'utf8');
const code = await readFile(new URL('public/investigator.js', root), 'utf8');
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.listeners={};this.dataset={};this.hidden=false;this.disabled=false;this.value='';this.textContent='';}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;this.textContent='';}
  addEventListener(name,fn){this.listeners[name]=fn;}
}
const elements=Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
const pending=[];
const context={window:{},selected:null,URL,console,Map,Set,Date,JSON,Number,String,document:{
  getElementById:id=>{assert.ok(elements[id],`Missing DOM node ${id}`);return elements[id];},
  createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})},
  setTimeout:()=>1,clearTimeout:()=>{},
  fetch:(url,options)=>new Promise(resolve=>pending.push({url,body:JSON.parse(options.body),resolve}))};
vm.runInNewContext(code,context);
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
const siteA={name:'SITE A'},siteB={name:'SITE B'};
const run={id:'a'.repeat(32),site:siteA.name,status:'complete',created_at:new Date().toISOString(),message:'Done',
  sources:{'E-location':{id:'E-location',title:'Location evidence',kind:'context',text:'<script>unsafe</script>',url:'javascript:alert(1)'}},
  events:[],artifacts:{},report:{summary:'A checked report',findings:[],limitations:[]},
  usage:{model_calls:10,max_calls:24,input_tokens:1000,output_tokens:100},followups:[],followup_running:false};
context.window.investigationSelect(siteA);
elements.analyze.listeners.click();
assert.equal(pending.length,1);
assert.equal(pending[0].body.site,siteA.name);
context.window.investigationSelect(siteB);
pending[0].resolve({ok:true,json:async()=>run});await flush();
assert.equal(elements['investigation-site'].textContent,siteB.name);
assert.equal(elements['investigation-summary'].textContent,'','Stale response must not replace another site');
context.window.investigationSelect(siteA);
assert.equal(elements['investigation-summary'].textContent,'A checked report');
assert.ok(elements['evidence-library'].children.length);
const source=elements['evidence-library'].children[0];
assert.ok(!source.children.some(e=>e.tag==='a'),'Unsafe source URLs must not become links');
assert.equal(source.children[1].textContent,'<script>unsafe</script>','Model content remains literal text');
context.window.investigationSelect(siteB);context.window.investigationSelect(siteA);
assert.ok(elements['evidence-library'].children.length,'Cached source library survives re-selection');
assert.equal(elements['followup-section'].hidden,false);
context.window.investigationSelect(null);
assert.equal(elements.investigator.hidden,true);
console.log('Offline frontend checks passed: stale results, cached selection, safe text/links, follow-up visibility.');
