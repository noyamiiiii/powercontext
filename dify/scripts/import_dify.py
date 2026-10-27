"""Use the actual Dify console APIs to import and publish the supplied DSL."""
from pathlib import Path
import json,os,time
import httpx,yaml

root=Path(__file__).resolve().parents[1]
api=os.getenv('DIFY_CONSOLE_URL','http://localhost:18081')
runtime=root/'runtime';runtime.mkdir(exist_ok=True)
admin=json.loads((runtime/'admin.json').read_text(encoding='utf8'))
env=dict(line.split('=',1) for line in (root/'.env').read_text().splitlines() if line and not line.startswith('#'))
evidence=root/'evidence';evidence.mkdir(exist_ok=True)
with httpx.Client(base_url=api,timeout=60,trust_env=False) as client:
    for attempt in range(90):
        try:
            response=client.get('/console/api/setup')
            if response.status_code==200:break
        except httpx.HTTPError:pass
        time.sleep(2)
    else:raise RuntimeError('Dify API did not become ready')
    def request(method,path,**kwargs):
        csrf=next((v for k,v in client.cookies.items() if 'csrf' in k.lower()),None)
        headers={'X-CSRF-Token':csrf} if csrf else {}
        r=client.request(method,path,headers=headers,**kwargs)
        if r.status_code>=400:
            # Errors are logged without request headers, cookies or credentials.
            raise RuntimeError(f'{method} {path}: {r.status_code} {r.text[:1000]}')
        return r.json()
    if response.json().get('step')!='finished':
        request('POST','/console/api/setup',json=dict(admin,language='zh-Hans'))
    request('POST','/console/api/login',json={'email':admin['email'],
        'password':admin['password'],'remember_me':True})
    dsl=yaml.safe_load((root/'dsl/midnight-museum.yml').read_text(encoding='utf8'))
    for variable in dsl['workflow']['environment_variables']:
        if variable['name']=='MUSEUM_TOOL_TOKEN':variable['value']=env['MUSEUM_TOOL_TOKEN']
    # Keep the supplied public DSL secret-free; credentials only enter the local Dify import.
    imported=request('POST','/console/api/apps/imports',json={
        'mode':'yaml-content','yaml_content':yaml.safe_dump(dsl,allow_unicode=True,sort_keys=False)})
    if imported.get('status')=='pending':
        imported=request('POST','/console/api/apps/imports/'+imported['id']+'/confirm')
    app_id=imported.get('app_id')
    if not app_id:raise RuntimeError('Import returned no app id: '+str(imported))
    request('POST',f'/console/api/apps/{app_id}/workflows/publish',json={
        'marked_name':'midnight-v1','marked_comment':'seekdb memories and local Ollama narration'})
    key=request('POST',f'/console/api/apps/{app_id}/api-keys')
    (runtime/'app-key').write_text(key['token']);(runtime/'app-key').chmod(0o600)
    (runtime/'app-id').write_text(app_id)
    (runtime/'console-cookies.json').write_text(json.dumps(dict(client.cookies)))
    (runtime/'console-cookies.json').chmod(0o600)
    # Confirm a fresh import is valid and exportable, but do not export embedded credentials.
    summary={'dify_version':'1.9.2','app_id':app_id,'import_status':imported.get('status'),
             'published':True,'api_key_created':True,'node_count':len(dsl['workflow']['graph']['nodes'])}
    (evidence/'dify-import.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary))
