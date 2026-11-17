"""Keep Flutter's compatibility import on gateway v2; never copy retired v1 SDKs."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
target = ROOT.parent / 'Mobile/lib/services/vietocr_remote.dart'
target.write_text("export 'gateway_client.dart';\n", encoding='utf-8')
print('Flutter transport: Raspberry v2. Desktop transport is native Rust.')
