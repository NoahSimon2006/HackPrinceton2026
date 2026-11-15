/* Serialized saves and optimistic versions keep two tabs from overwriting work. */
class SavedProject {
  constructor(value = null) { this.value = value; this.queue = Promise.resolve(); }
  save(snapshot) {
    const frozen = JSON.parse(JSON.stringify(snapshot));
    const operation = this.queue.then(async () => {
      const response = await fetch('/api/projects', {method:'POST',keepalive:true,
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({
          projectId:this.value?.id, expectedVersion:this.value?.version, snapshot:frozen,
        })});
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || 'Project could not be saved.');
      this.value = value;
      return value;
    });
    this.queue = operation.catch(() => {});
    return operation;
  }
}
