"""Read actual Ollama version, installed model digest and model details."""
import json
import httpx
from app import MODEL,OLLAMA
with httpx.Client(base_url=OLLAMA,timeout=30,trust_env=False) as client:
    def get(path):
        r=client.get(path);r.raise_for_status();return r.json()
    version=get('/api/version')['version']
    model=next(m for m in get('/api/tags')['models'] if m['name']==MODEL)
    r=client.post('/api/show',json={'model':MODEL});r.raise_for_status();info=r.json()
    running=next((m for m in get('/api/ps')['models'] if m['name']==MODEL),None)
    print(json.dumps({'ollama_version':version,'model':MODEL,'manifest_digest':model['digest'],
                      'size_bytes':model['size'],'details':info['details'],
                      'loaded_on_cpu':running is not None and running.get('size_vram')==0},indent=2))
