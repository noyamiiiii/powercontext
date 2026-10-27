"""Generate local secrets once, never replace existing configuration."""
import os
from pathlib import Path
import secrets
root=Path(__file__).resolve().parents[1]
env=root/'.env'
names=['DIFY_SECRET_KEY','POSTGRES_PASSWORD','REDIS_PASSWORD','SANDBOX_KEY',
       'PLUGIN_KEY','SEEKDB_PASSWORD','MUSEUM_TOOL_TOKEN']
if not env.exists():
    env.write_text('\n'.join(f'{name}={secrets.token_hex(24)}' for name in names)+'\n',encoding='utf8')
    env.chmod(0o600)
runtime=root/'runtime';runtime.mkdir(exist_ok=True)
admin=runtime/'admin.json'
if not admin.exists():
    import json
    admin.write_text(json.dumps({'email':'curator@example.com','password':'Museum-'+secrets.token_hex(12),'name':'午夜博物馆'},ensure_ascii=False),encoding='utf8')
    admin.chmod(0o600)
print('Local configuration ready. Credentials are in ignored .env and runtime/admin.json; no secrets printed.')
