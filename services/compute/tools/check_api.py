"""End-to-end checks against the real C# API and Supabase; no fake database.

Creates individually labelled test keys/jobs and revokes them on completion.
Run the server first. --inference additionally exercises its real model worker.
Credentials are read from a private local file, never printed.
"""
import argparse
import hashlib
import http.cookiejar
import json
from pathlib import Path
import secrets
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "clients/python"))
from vietocr_remote import VietOcrClient


def check(args):
    cookie = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(cookie))
    created, checks = [], []
    def request(path, method="GET", payload=None, token=None, expected=200):
        headers = {}
        if token:
            headers["X-CSRF-TOKEN"] = token
        data = None if payload is None else json.dumps(payload).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = opener.open(urllib.request.Request(args.origin + path, method=method, data=data, headers=headers), timeout=100)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            assert response.code == expected, f"{method} {path}: {response.code}, expected {expected}"
            content = response.read()
            return json.loads(content) if content else None
    def passed(name):
        checks.append(name)
        print("PASS", name)
    try:
        request("/api/admin/snapshot", expected=401)
        request("/api/v1/jobs", "POST", {}, expected=401)
        request("/api/admin/clients", "POST", {}, expected=401)
        passed("authentication and CSRF fail closed")
        password = (ROOT / "runtime/admin-first-login.txt").read_text().split("Password: ", 1)[1].strip()
        token = request("/api/admin/auth/csrf")["token"]
        request("/api/admin/auth/login", "POST", {"username": "admin", "password": password}, token)
        token = request("/api/admin/auth/csrf")["token"]
        request("/api/admin/clients", "POST", {"name":"csrf-reject"}, expected=400)
        passed("admin login and authenticated CSRF session")
        stamp = secrets.token_hex(4)
        for platform in ("desktop", "android"):
            entry = request("/api/admin/clients", "POST", {"name": f"validation-{platform}-{stamp}", "ratePerMinute": 60}, token)
            created.append(entry)
        one, two = [VietOcrClient(args.origin, item["key"]) for item in created]
        passed("separate API identities")
        idem = secrets.token_hex(16)
        job = one.submit(args.image, "line", idem)
        duplicate = one.submit(args.image, "line", idem)
        assert duplicate["id"] == job["id"]
        passed("idempotent upload returns original job")
        assert one.account()['usedToday']==1
        passed("duplicate upload consumes only one OCR credit")
        try:
            two.get(job["id"],wait=10)
            raise AssertionError("Cross-client result was readable")
        except Exception as exc:
            assert "404" in str(exc)
        passed("cross-client job ownership enforced")
        try:
            one.submit(args.image, "auto", idem)
            raise AssertionError("Idempotency conflict was accepted")
        except Exception as exc:
            assert "409" in str(exc)
        passed("idempotency rejects changed layout")
        result = None
        if args.inference:
            started = time.perf_counter()
            while time.perf_counter()-started < 120:
                result = one.get(job["id"],wait=2)
                if result["state"] in {"succeeded", "failed", "cancelled"}:
                    break
                time.sleep(.5)
            assert result and result["state"] == "succeeded", "Real model inference did not succeed"
            assert result["text"] and result["width"] > 0 and result["height"] > 0
            passed("native model inference through authenticated API")
        else:
            one.cancel(job["id"])
            assert one.get(job["id"])["state"] == "cancelled"
            passed("queued job cancellation")
        for _ in range(20):
            if not (ROOT / f"runtime/images/{job['id']}.image").exists():
                break
            time.sleep(.2)
        assert not (ROOT / f"runtime/images/{job['id']}.image").exists()
        passed("terminal image is removed")
        snapshot = request("/api/admin/snapshot")
        assert snapshot["database"] == "connected"
        assert snapshot["capacity"]["reserveMiB"] >= 1024
        passed("real metrics and hardware reserve")
        visible = request("/api/admin/clients")
        assert all("key" not in item and "keyHash" not in item for item in visible)
        passed("client list never reveals API secrets")
        request("/api/admin/clients/" + created[1]["client"]["id"], "DELETE", token=token, expected=204)
        try:
            two.get(job["id"])
            raise AssertionError("Revoked API key remained active")
        except Exception as exc:
            assert getattr(exc, 'permanent', False)
        passed("key revocation effective immediately")
        report = {"checks": checks, "count": len(checks), "gpu": snapshot.get("gpu"), "capacity": snapshot["capacity"],
                  "workers": snapshot["workers"], "result": None if result is None else {k: result[k] for k in ("state", "queueMs", "inferenceMs", "totalMs", "width", "height")}}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        for item in created:
            try:
                request("/api/admin/clients/" + item["client"]["id"], "DELETE", token=token, expected=204)
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:5080")
    parser.add_argument("--image", type=Path, default=ROOT.parents[1] / "shared/contracts/fixtures/images/test.jpg")
    parser.add_argument("--inference", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "validation/api-checks.json")
    check(parser.parse_args())
