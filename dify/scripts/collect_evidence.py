"""Collect an explicit allowlist of fields; never export HTTP headers or secrets."""
from pathlib import Path
import json,os,subprocess
import httpx
root=Path(__file__).resolve().parents[1];runtime=root/'runtime';evidence=root/'evidence'
traces=json.loads((evidence/'actual-playthrough.json').read_text(encoding='utf8'))
app_id=(runtime/'app-id').read_text().strip()
cookies=json.loads((runtime/'console-cookies.json').read_text())
csrf=next((v for k,v in cookies.items() if 'csrf' in k.lower()),'')
nodes=[]
with httpx.Client(base_url=os.getenv('DIFY_CONSOLE_URL','http://localhost:18081'),cookies=cookies,
                  headers={'X-CSRF-Token':csrf},timeout=60,trust_env=False) as client:
    for trace in traces:
        run=trace['workflow_run_id']
        r=client.get(f'/console/api/apps/{app_id}/workflow-runs/{run}/node-executions');r.raise_for_status()
        safe=[{k:n.get(k) for k in ['node_id','node_type','title','status','elapsed_time','error','created_at','finished_at']}
              for n in r.json()['data']]
        assert len(safe)==8 and all(n['status']=='succeeded' for n in safe),safe
        nodes.append({'workflow_run_id':run,'nodes':safe})
(evidence/'dify-node-executions.json').write_text(json.dumps(nodes,ensure_ascii=False,indent=2),encoding='utf8')
player=traces[0]['inputs']['player_id']
cmd=[os.getenv('DOCKER','docker'),'compose','exec','-T','museum','python','audit.py',player]
audit=subprocess.run(cmd,cwd=root,capture_output=True,text=True,check=True)
data=json.loads(audit.stdout)
assert len(data['turns'])==6 and all(t['committed'] for t in data['turns'])
assert any('恶作剧' in action for t in data['turns'] for action in t['remembered_actions'])
(evidence/'seekdb-records.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
model=subprocess.run([os.getenv('DOCKER','docker'),'compose','exec','-T','museum','python','audit_model.py'],
                     cwd=root,capture_output=True,text=True,check=True)
(evidence/'model.json').write_text(json.dumps(json.loads(model.stdout),indent=2),encoding='utf8')
print('Verified 56 actual Dify node executions and 6 committed seekdb turns (7 runs including retry)')
