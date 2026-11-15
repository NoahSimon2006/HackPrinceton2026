import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {ReadableStream} from 'node:stream/web';
const source=await readFile(new URL('../public/analysis-stream.js',import.meta.url),'utf8');
async function run(events,chunkSize=7) {
  const wire=events.map(e=>JSON.stringify(e)).join('\n')+'\n';const bytes=new TextEncoder().encode(wire);let index=0;const received=[];
  const context=vm.createContext({TextDecoder,fetch:async()=>({ok:true,headers:{get:()=> 'application/x-ndjson'},body:new ReadableStream({pull(controller){if(index>=bytes.length){controller.close();return;}controller.enqueue(bytes.slice(index,index+chunkSize));index+=chunkSize;}})})});
  vm.runInContext(source,context);
  const result=await context.streamSiteAnalysis({}, {onEvent:e=>received.push(e)});return {result,received};
}
const event={type:'activity',run_id:'a',sequence:1,specialist:'site-evidence',summary:'Measured m²'};
const result={type:'result',run_id:'a',result:{runId:'a',report:null}};
assert.equal((await run([event,result])).received[0].summary,'Measured m²');
await assert.rejects(run([event,{...result,run_id:'b'}]),/identity mismatch/);
await assert.rejects(run([event,event,result]),/sequence mismatch/);
await assert.rejects(run([event]),/ended early/);
await assert.rejects(run([event,{type:'error',run_id:'a',error:'Source failed'}]),/Source failed/);
await assert.rejects(run([event,result,result]),/after its terminal result/);
await assert.rejects(run([event,result,{...event,sequence:2}]),/after its terminal result/);
await assert.rejects(run([event,{...result,result:null}]),/Result identity mismatch/);
console.log('PASS: chunked UTF-8 stream, run identity, event sequence, partial failure and missing terminal result');

// Missing source dates are valid unavailable-source evidence, not a transport
// error. Keep the partial fact intact through fragmented NDJSON decoding.
const unavailableFact={id:'area-flow-coverage',basis:'availability',display:'unavailable',
  source:{provider:'TomTom Traffic',retrieved_at:null,observed_at:null},feature_ids:[]};
const partial=await run([{...event,facts:[unavailableFact]},
  {...result,result:{runId:'a',facts:[unavailableFact],report:{findings:[],recommendations:[],questions:[]},analysisError:null}}],1);
assert.equal(partial.received[0].facts[0].source.retrieved_at,null);
assert.equal(partial.result.facts[0].display,'unavailable');
assert.equal(partial.result.analysisError,null);
console.log('PASS: unavailable-source facts survive fragmented streaming without invented metadata');
