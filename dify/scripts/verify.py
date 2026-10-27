"""Real end-to-end proof: published Dify workflow -> Ollama -> seekdb.

No fake model or replacement workflow runner is used by this script.
"""
from pathlib import Path
import json,os,time,uuid
import httpx

root=Path(__file__).resolve().parents[1]
runtime=root/'runtime'
api=os.getenv('DIFY_CONSOLE_URL','http://localhost:18081')
key=(runtime/'app-key').read_text().strip()
evidence=root/'evidence';evidence.mkdir(exist_ok=True)
player='verify_'+uuid.uuid4().hex[:12]
traces=[]
with httpx.Client(timeout=5,trust_env=False) as client:
    for attempt in range(90):
        try:
            r=client.get(api+'/console/api/setup')
            if r.status_code==200 and r.json().get('step')=='finished':break
        except (httpx.HTTPError,ValueError):pass
        time.sleep(2)
    else:raise RuntimeError('Published Dify service did not become ready')
def play(action,request_id=None,who=player):
    inputs={'player_id':who,'request_id':request_id or uuid.uuid4().hex,'action':action}
    started=time.monotonic()
    with httpx.Client(timeout=300,trust_env=False) as client:
        r=client.post(api+'/v1/workflows/run',headers={'Authorization':'Bearer '+key},
            json={'inputs':inputs,'response_mode':'blocking','user':who})
        if r.status_code!=200:raise RuntimeError(str(r.status_code)+' '+r.text[:1000])
        response=r.json();data=response.get('data',{})
        if data.get('status')!='succeeded':raise RuntimeError(json.dumps(response,ensure_ascii=False)[:2000])
        result=json.loads(data['outputs']['result'])
    assert result['storage']=='seekdb' and result['model'].startswith('qwen3')
    assert result['narrative'].strip()
    trace={'inputs':inputs,'workflow_run_id':response.get('workflow_run_id',data.get('id')),
           'status':data['status'],'total_steps':data.get('total_steps'),'elapsed_seconds':round(time.monotonic()-started,3),
           'outputs':result}
    traces.append(trace)
    print('PASS Dify turn',result['version'],action,'clues',len(result['clues']),'memories',result['remembered_turns'],flush=True)
    (evidence/'actual-playthrough.json').write_text(json.dumps(traces,ensure_ascii=False,indent=2),encoding='utf8')
    return result,inputs

first,inputs=play('调查铜铃，看看铃舌里藏着什么')
assert first['version']==1 and [x['id'] for x in first['clues']]==['bell']
replay,_=play(inputs['action'],inputs['request_id'])
assert replay==first, 'Replay must return exactly the same committed result'
second,_=play('对着镜子做个恶作剧，假装自己是馆长')
assert second['trust']==first['trust']-1 and second['remembered_turns']>=1
third,_=play('调查镜子背面。你还记得我刚才的恶作剧吗？')
assert third['remembered_turns']>=2 and len(third['clues'])==2
fourth,_=play('翻看登记簿第0017号记录')
assert len(fourth['clues'])==3
fifth,_=play('安抚守夜员，出示证据，揭晓真相')
assert fifth['ending']=='reunion'
fresh,_=play('刚才我调查过铜铃吗？',who=player+'_other')
assert fresh['remembered_turns']==0 and fresh['clues']==[] and fresh['version']==1
with httpx.Client(timeout=10,trust_env=False) as client:
    r=client.get(os.getenv('MUSEUM_URL','http://localhost:18091')+'/state/'+player)
    r.raise_for_status();restored=r.json()
    assert restored['started'] and restored['result']==fifth
summary={'passed':True,'real_dify_runs':len(traces),'replay_exact':True,'cross_request_memory':True,
         'player_isolation':True,'three_clues_and_ending':True,'page_progress_restore':True,'player_id':player,
         'model':fifth['model'],'storage':'seekdb','dify_version':'1.9.2'}
(evidence/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=False),flush=True)
