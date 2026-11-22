"""Read-only production check: publishable key alone must expose no OCR rows.

Uses only the bundled public config. No login, admin secret, database mutation
or OCR admission. Response bodies and identities are never printed.
"""
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TABLES = ('ocr_clients', 'ocr_jobs', 'ocr_daily_usage', 'ocr_admins', 'ocr_settings',
          'ocr_audit', 'ocr_v2_intents', 'ocr_v2_reservations', 'ocr_v2_ingress_capacity')


def main():
    public = json.loads((ROOT / 'apps/android/assets/config/supabase.json').read_text(encoding='utf-8-sig'))
    if not public['url'].startswith('https://') or not public['url'].endswith('.supabase.co'):
        raise ValueError('Expected project HTTPS origin')
    report = []
    for table in TABLES:
        request = urllib.request.Request(
            public['url'] + '/rest/v1/' + table + '?select=*&limit=1',
            headers={'apikey': public['publishableKey'], 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                body = response.read(65537)
                rows = json.loads(body) if len(body) <= 65536 else None
                report.append({'table': table, 'http': response.status,
                               'noAnonymousRows': isinstance(rows, list) and len(rows) == 0})
        except urllib.error.HTTPError as error:
            report.append({'table': table, 'http': error.code,
                           'noAnonymousRows': error.code in (401, 403)})
    print(json.dumps({'scope': 'Current project, publishable key without a user session; read-only table access', 'checks': report}))
    return not all(row['noAnonymousRows'] for row in report)


if __name__ == '__main__':
    raise SystemExit(main())
