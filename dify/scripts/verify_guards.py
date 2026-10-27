"""Real HTTP/seekdb/Ollama checks of atomic commit and failure handling."""
from pathlib import Path
import json,os,subprocess,time,uuid
import httpx
root=Path(__file__).resolve().parents[1]
env=dict(l.split('=',1) for l in (root/'.env').read_text().splitlines() if l and not l.startswith('#'))
auth={'Authorization':'Bearer '+env['MUSEUM_TOOL_TOKEN']}
api=os.getenv('MUSEUM_URL','http://localhost:18091')
player='guards_'+uuid.uuid4().hex[:12];results={}
with httpx.Client(base_url=api,timeout=180,trust_env=False) as client:
    def post(path,data,expected=200,headers=auth):
        r=client.post(path,json=data,headers=headers);assert r.status_code==expected,(path,r.status_code,r.text)
        return r.json()
    def action(request,text,who=player):return dict(player_id=who,request_id=request,action=text)
    post('/context',action('unauth','调查铜铃'),401,headers={});results['unauthorized_401']=True
    post('/context',action('invalid','调查铜铃',"x';DROP"),422);results['invalid_identifier_422']=True
    post('/context',action('blank','   '),422);results['blank_action_422']=True
    a=post('/context',action('parallel_a','安抚守夜员'))
    b=post('/context',action('parallel_b','对着镜子恶作剧'))
    assert a['context']['version']==b['context']['version']==0
    ta={'turn_id':a['turn_id']};tb={'turn_id':b['turn_id']}
    post('/commit',ta,409);results['no_commit_without_model_409']=True
    post('/context',action('parallel_a','修改原动作'),409);results['request_reuse_with_other_action_409']=True
    post('/narrate',ta);post('/narrate',tb)
    saved=post('/commit',ta);post('/commit',tb,409)
    assert saved['version']==1 and saved['trust']==4
    assert post('/commit',ta)==saved
    results.update(stale_concurrent_commit_409=True,commit_retry_exact=True,player=player)
    outage=player+'_outage'
    prepared=post('/context',action('model_outage','调查铜铃',outage))
    docker=os.getenv('DOCKER','docker');cmd=[docker,'compose']
    def compose(*args):subprocess.run([*cmd,*args],cwd=root,capture_output=True,check=True)
    try:
        compose('stop','ollama')
        post('/narrate',{'turn_id':prepared['turn_id']},503)
        post('/commit',{'turn_id':prepared['turn_id']},409)
        audit=subprocess.run([*cmd,'exec','-T','museum','python','audit.py',outage],cwd=root,
                             capture_output=True,text=True,check=True)
        stored=json.loads(audit.stdout)
        assert stored['players'][0]['version']==0 and stored['players'][0]['clues']=='[]'
        assert len(stored['turns'])==1 and not stored['turns'][0]['committed']
        results.update(model_outage_503=True,failed_model_leaves_player_unchanged=True,outage_store=stored)
    finally:compose('start','ollama')
(root/'evidence/guards.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(results,ensure_ascii=False),flush=True)
