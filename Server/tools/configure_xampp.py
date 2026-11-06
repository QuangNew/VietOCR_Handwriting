"""Configure a dedicated local XAMPP database/user, without logging credentials.

Existing databases/users are never dropped or reset. Root credentials stay out
of shell arguments and are read from MYSQL_PWD only when the user supplies it.
"""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def configure(mysql, port):
    config = ROOT / "server.local.json"
    if config.exists():
        print("Keeping existing Server/server.local.json")
        return
    args = [str(mysql), "--protocol=tcp", "--host=127.0.0.1", f"--port={port}", "--user=root",
            "--connect-timeout=5", "--batch", "--skip-column-names"]
    password = ""
    def execute(sql):
        result = subprocess.run(args, input=sql, text=True, encoding="utf-8", capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        if result.returncode:
            diagnostic=result.stderr.replace(password,"[redacted]") if password else result.stderr
            raise RuntimeError("XAMPP database setup failed: "+diagnostic[:1000])
        return result.stdout.strip()
    exists = execute("SELECT COUNT(*) FROM mysql.user WHERE User='vietocr_app' AND Host='127.0.0.1';")
    if exists != "0":
        raise RuntimeError("vietocr_app already exists; configure server.local.json manually to avoid replacing credentials.")
    password = secrets.token_hex(24)
    execute("CREATE DATABASE IF NOT EXISTS vietocr_server CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
            f"CREATE USER 'vietocr_app'@'127.0.0.1' IDENTIFIED BY '{password}';\n"
            "GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,INDEX,ALTER,REFERENCES ON vietocr_server.* TO 'vietocr_app'@'127.0.0.1';")
    config.write_text(json.dumps({"Server": {"ConnectionString": f"Server=127.0.0.1;Port={port};Database=vietocr_server;"
          f"User ID=vietocr_app;Password={password};MaximumPoolSize=12;ConnectionTimeout=5;DefaultCommandTimeout=10"}}, indent=2), encoding="utf-8")
    print(f"Created dedicated vietocr_server database on 127.0.0.1:{port}; credentials in ignored Server/server.local.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mysql", type=Path, required=True)
    parser.add_argument("--port", type=int, default=3306)
    args = parser.parse_args()
    configure(args.mysql, args.port)
