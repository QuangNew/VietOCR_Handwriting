"""One-time copy of old admins/API identities to Supabase; leaves XAMPP unchanged.

Run while the old database is available. Privileged SQL stays in ignored runtime/.
No passwords, hashes or API keys are printed. Original keys retain their SHA-256 hash.
"""
import json
import os
import pathlib
import subprocess
import argparse

ROOT = pathlib.Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mysql', required=True)
    parser.add_argument('--root-read', action='store_true', help='Use existing local root access for read-only export')
    args = parser.parse_args()
    cfg = json.loads((ROOT / 'server.local.json').read_text(encoding='utf-8-sig'))
    parts = dict(x.split('=', 1) for x in cfg['Server'].get('ConnectionString', '').split(';') if '=' in x)
    if not parts:
        print('No legacy MySQL connection configured. Nothing to migrate.')
        return
    env = os.environ.copy()
    env['MYSQL_PWD'] = parts.get('Password', '')
    if args.root_read:
        env['MYSQL_PWD'] = os.environ.get('MYSQL_PWD', '')
    command = [args.mysql, '--host=' + parts.get('Server', '127.0.0.1'), '--port=' + parts.get('Port', '3306'),
               '--user=' + ('root' if args.root_read else parts.get('User ID', 'vietocr_app')), '--database=' + parts['Database'],
               '--batch', '--raw', '--skip-column-names']
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'" if value is not None else 'null'
    sql, counts = [], {}
    for table, fields in [('admins', ['id', 'username', 'password_hash']),
                          ('clients', ['id', 'name', 'prefix', 'key_hash', 'rate_per_minute', 'enabled', 'created_at'])]:
        query = 'SELECT JSON_OBJECT(' + ','.join(quote(f) + ',' + f for f in fields) + ') FROM ' + table
        result = subprocess.run(command + ['-e', query], env=env, capture_output=True, text=True, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('Legacy database unavailable. Start XAMPP MySQL and retry; source was not changed.')
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        counts[table] = len(rows)
        for row in rows:
            if table == 'clients':
                row['rate_per_minute'] = min(60, row['rate_per_minute'])
                row['created_at'] += '+00'
            sql.append('insert into public.ocr_' + table + '(' + ','.join(fields) + ') values(' +
                       ','.join(quote(row[f]) for f in fields) + ') on conflict(id) do nothing;')
    destination = ROOT / 'runtime/legacy-migration.sql'
    destination.write_text('\n'.join(sql), encoding='utf-8')
    cli = subprocess.run(['supabase.cmd', 'db', 'query', '--linked', '--file', str(destination), '--output', 'json'],
                         cwd=ROOT.parent, capture_output=True, text=True)
    if cli.returncode:
        raise RuntimeError('Supabase import failed. Inspect SQL privately in runtime/; legacy database untouched.')
    print(json.dumps({'copied': counts, 'sourceRetained': True, 'keysRetainHashes': True}))

if __name__ == '__main__':
    main()
