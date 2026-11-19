"""Read-only check for the actual host secrets in tracked files and client artifacts.

Never prints a secret, its hash, matching content or user session files. This is
a narrowly scoped packaging check, not a complete security assessment.
Run: services/compute/.venv/Scripts/python.exe tools/check_client_secrets.py [EXE/APK...]
"""
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    public = json.loads((ROOT / 'apps/android/assets/config/supabase.json').read_text(encoding='utf-8-sig'))
    if set(public) != {'url', 'publishableKey'} or not public['publishableKey'].startswith('sb_publishable_'):
        raise ValueError('Client public configuration has unexpected fields or key type.')
    settings = ROOT / 'services/compute/server.local.json'
    needles = []
    if settings.exists():
        private = json.loads(settings.read_text(encoding='utf-8-sig'))['Server']
        for key in ('SupabaseServiceKey', 'SupabaseSecretKey'):
            if private.get(key):
                needles.append(private[key])
    for name in ('ingress.token', 'telemetry.token'):
        token = ROOT / '.toolchain/refactor/pairing' / name
        if token.exists():
            needles.append(token.read_text(encoding='ascii').strip())
    if not needles or any(len(value) < 32 for value in needles):
        raise ValueError('Known host secrets required for a meaningful local check.')
    encoded = [value.encode(encoding) for value in needles for encoding in ('utf-8', 'utf-16-le')]
    tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, check=True, capture_output=True).stdout
    targets = [ROOT / name.decode('utf-8') for name in tracked.split(b'\0') if name]
    targets += [Path(name).resolve() for name in sys.argv[1:]]
    checked = 0
    findings = []
    for target in dict.fromkeys(targets):
        if not target.is_file():
            continue  # Tracked deletions are not shipped.
        data = target.read_bytes()
        checked += 1
        if any(secret in data for secret in encoded):
            findings.append(str(target.relative_to(ROOT)))
        if target.suffix == '.apk':
            with zipfile.ZipFile(target) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    checked += 1
                    if any(secret in archive.read(info) for secret in encoded):
                        findings.append(f'{target.name}: packaged entry')
    report = {'checkedEntries': checked, 'knownHostCredentials': len(needles),
              'matches': findings, 'publicConfigType': 'publishable',
              'scope': 'Exact current host secret values, UTF8/UTF16, tracked files and supplied artifacts; not a historical Git or full security audit.'}
    print(json.dumps(report))
    return bool(findings)


if __name__ == '__main__':
    raise SystemExit(main())
