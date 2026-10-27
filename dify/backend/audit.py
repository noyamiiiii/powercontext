"""Read-only inspection of game records, run inside the museum container."""
import json,sys
from app import connection
player=sys.argv[1]
with connection() as db,db.cursor() as cur:
    cur.execute('SELECT VERSION() AS version');version=cur.fetchone()['version']
    cur.execute('SELECT COUNT(*) AS count FROM exhibits');count=cur.fetchone()['count']
    cur.execute('SELECT id,version,trust,clues,ending FROM players WHERE id IN (%s,%s)',(player,player+'_other'))
    players=cur.fetchall()
    cur.execute('SELECT player_id,request_id,version,action,context_json,narration,model,result_json FROM turns WHERE player_id IN (%s,%s) ORDER BY player_id,version',(player,player+'_other'))
    turns=[]
    for row in cur.fetchall():
        context=json.loads(row.pop('context_json'));row.pop('narration')
        row['committed']=bool(row.pop('result_json'))
        row['remembered_actions']=[m['action'] for m in context['memories']]
        row['retrieval_hits']=[{'id':hit['id'],'score':hit.get('score')} for hit in context['retrieved']]
        turns.append(row)
print(json.dumps({'seekdb_version':version,'original_exhibits':count,'players':players,'turns':turns},ensure_ascii=False,indent=2,default=str))
