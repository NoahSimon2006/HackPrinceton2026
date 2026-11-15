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
console.log('PASS: chunked UTF-8 stream, run identity, event sequence, partial failure and missing terminal result');
