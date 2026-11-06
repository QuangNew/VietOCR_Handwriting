"""Read keys via the already-authenticated Supabase CLI; never print private keys."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

SERVER=Path(__file__).resolve().parents[1]
REPO=SERVER.parent

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project-ref',default='rrdxhztiikizgogxtlhu')
    args=parser.parse_args()
    if not args.project_ref.isalpha() or len(args.project_ref)!=20:
        raise ValueError('Invalid project reference')
    result=subprocess.run(['supabase.cmd','projects','api-keys','--project-ref',args.project_ref,'--output','json'],
        capture_output=True,text=True,check=True,cwd=REPO)
    keys=json.loads(result.stdout)
    public=next((r['api_key'] for r in keys if r.get('type')=='publishable'),None) or next(r['api_key'] for r in keys if r['name']=='anon')
    secret=next(r['api_key'] for r in keys if r['name']=='service_role')
    destination=SERVER/'server.local.json'
    config=json.loads(destination.read_text(encoding='utf-8-sig')) if destination.exists() else {'Server':{}}
    if 'ConnectionString' in config['Server']:
        backup=SERVER/'runtime/legacy-mysql-config.json';backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():shutil.copy2(destination,backup)
        del config['Server']['ConnectionString']
    config['Server'].update(SupabaseUrl=f'https://{args.project_ref}.supabase.co',SupabasePublishableKey=public,SupabaseServiceKey=secret)
    destination.write_text(json.dumps(config,indent=2),encoding='utf-8')
    client_config=json.dumps({'url':config['Server']['SupabaseUrl'],'publishableKey':public},indent=2)
    for path in [REPO/'Mobile/assets/config/supabase.json',REPO/'VietHandOCR_API_Release/desktop/cloud_config.json']:
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(client_config,encoding='utf-8')
    print(f'Configured {args.project_ref}. Private service credential: Server/server.local.json; clients contain publishable key only.')

if __name__=='__main__':main()
