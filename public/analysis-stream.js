/* One transport for site analysis. Explicit event IDs prevent mixed-run rendering. */
async function streamSiteAnalysis(payload, {signal, onEvent}) {
  const response = await fetch('/api/site-analysis', {method:'POST',signal,
    headers:{'Content-Type':'application/json','Accept':'application/x-ndjson'},body:JSON.stringify(payload)});
  if (!response.ok) { const error=await response.json(); throw new Error(error.error || 'Analysis unavailable.'); }
  if (!response.body || !response.headers.get('Content-Type')?.includes('application/x-ndjson')) throw new Error('Restart the local server to enable agent activity.');
  const reader=response.body.getReader(), decoder=new TextDecoder();
  let buffer='', runId=null, result=null, sequence=0;
  function consume(line) {
    if (!line.trim()) return;
    const event=JSON.parse(line);
    if (result !== null) throw new Error('Analysis event arrived after its terminal result.');
    if (typeof event.run_id !== 'string' || !event.run_id) throw new Error('Missing analysis identity.');
    runId ??= event.run_id;
    if (event.run_id !== runId) throw new Error('Analysis identity mismatch.');
    if (event.type === 'activity') {
      if (!Number.isInteger(event.sequence) || event.sequence <= sequence) throw new Error('Activity sequence mismatch.');
      sequence=event.sequence; onEvent(event);
    } else if (event.type === 'result') {
      if (!event.result || event.result.runId !== runId) throw new Error('Result identity mismatch.');
      result=event.result;
    } else if (event.type === 'error') throw new Error(event.error);
    else throw new Error('Unknown analysis event.');
  }
  try {
    while (true) {
      const {value,done}=await reader.read();
      if (done) break;
      buffer+=decoder.decode(value,{stream:true});
      if (buffer.length > 4000000) throw new Error('Analysis response exceeded its limit.');
      const lines=buffer.split('\n'); buffer=lines.pop(); for (const line of lines) consume(line);
    }
    buffer+=decoder.decode(); if(buffer.trim()) consume(buffer);
    if (!result) throw new Error('Analysis stream ended early. Retrieved facts are preserved; retry.');
    return result;
  } finally { await reader.cancel().catch(()=>{}); reader.releaseLock(); }
}

function cancelSiteAnalysis(runId) {
  if (!runId) return;
  // Signal the server as well as aborting the reader; active provider calls have
  // bounded timeouts and are not forcibly interrupted inside their HTTP client.
  fetch('/api/site-analysis/cancel', {method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({runId}),keepalive:true}).catch(()=>{});
}
