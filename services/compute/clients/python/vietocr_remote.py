"""Dependency-free async-job client for desktop applications.

Never embeds a shared secret. Store the API key with Windows Credential Manager
in a GUI integration; scripts can supply VIETOCR_API_KEY via their environment.
"""
import json
import mimetypes
from pathlib import Path
import secrets
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


class ServerError(RuntimeError):
    pass


class RemoteCancelled(ServerError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an API credential or image to a redirect destination.
        raise urllib.error.HTTPError(req.full_url, code, 'Redirect refused', headers, fp)


class VietOcrClient:
    def __init__(self, origin, api_key, timeout=180, allow_insecure_lan=False):
        parsed = urlparse(origin)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
            raise ValueError("Invalid server origin")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"} and not allow_insecure_lan:
            raise ValueError("Use HTTPS outside loopback, or explicitly allow a trusted development LAN.")
        self.origin = origin.rstrip("/")
        self._key = api_key
        self.timeout = timeout
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def _request(self, method, path, data=None, headers=None):
        token = self._key() if callable(self._key) else self._key
        if not token:
            raise ServerError("Đăng nhập Google trước khi nhận diện.")
        request = urllib.request.Request(self.origin + path, data=data, method=method,
            headers={"Authorization": "Bearer " + token, **(headers or {})})
        try:
            with self.http.open(request, timeout=20) as response:
                payload = response.read(2_000_000)
                return json.loads(payload) if payload else None
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read(8192))
            except (ValueError, OSError):
                detail = {}
            if detail.get('error') in ('daily_quota', 'minute_quota', 'account_disabled'):
                error = ServerError(detail.get('message') or 'Tài khoản hết hạn mức hoặc bị khoá.')
                error.permanent = True
                raise error from None
            if exc.code in (429, 503):
                retry = ServerError(f"Server busy ({exc.code}). Retry after {exc.headers.get('Retry-After', '3')} seconds.")
                try:
                    retry.retry_after = min(30, max(1, int(exc.headers.get("Retry-After", "3"))))
                except ValueError:
                    retry.retry_after = 3
                raise retry from None
            if exc.code == 401:
                error = ServerError("Phiên đăng nhập hết hạn. Đăng nhập Google lại trong OCR Server.")
                error.permanent = True
                raise error from None
            raise ServerError(f"Server rejected the request ({exc.code}).") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ServerError("Server connection failed.") from None

    def submit(self, path, layout="auto", idempotency_key=None):
        source = Path(path)
        if source.stat().st_size > 16 * 1048576:
            raise ValueError("Image exceeds 16 MiB")
        if layout not in ("auto", "line"):
            raise ValueError("Unknown layout")
        boundary = "vietocr-" + secrets.token_hex(16)
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"layout\"\r\n\r\n{layout}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"image\"\r\n"
                f"Content-Type: {mime}\r\n\r\n").encode() + source.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        return self._request("POST", "/api/v1/jobs", body,
            {"Content-Type": f"multipart/form-data; boundary={boundary}",
             "Idempotency-Key": idempotency_key or secrets.token_hex(16)})

    def check(self):
        return self._request("GET", "/api/v1/status")

    def account(self):
        return self._request("GET", "/api/v1/me")

    def history(self):
        return self._request("GET", "/api/v1/jobs")

    def get(self, job_id, wait=0):
        self._check_id(job_id)
        suffix=f"?wait={min(10,max(0,int(wait)))}" if wait else ""
        return self._request("GET", "/api/v1/jobs/" + job_id + suffix)

    def cancel(self, job_id):
        self._check_id(job_id)
        return self._request("DELETE", "/api/v1/jobs/" + job_id)

    @staticmethod
    def _check_id(value):
        if len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("Invalid job ID")

    def recognize(self, path, layout="auto", cancel=None, on_state=None):
        cancel = cancel or threading.Event()
        deadline = time.monotonic() + self.timeout
        idem = secrets.token_hex(16)
        job = None
        # Same idempotency key survives ambiguous upload failures.
        for attempt in range(3):
            if cancel.is_set():
                raise RemoteCancelled("Recognition cancelled.")
            try:
                job = self.submit(path, layout, idem)
                break
            except ServerError as error:
                if attempt == 2 or getattr(error, 'permanent', False):
                    raise
                if cancel.wait(getattr(error, "retry_after", 2)):
                    raise RemoteCancelled("Recognition cancelled.") from None
        assert job is not None
        try:
            while True:
                if cancel.is_set():
                    raise RemoteCancelled("Recognition cancelled.")
                if on_state:
                    on_state(job["state"])
                if job["state"] == "succeeded":
                    return job["text"]
                if job["state"] in ("failed", "cancelled"):
                    raise ServerError(job.get("error") or "Recognition failed.")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Server recognition timed out.")
                if cancel.wait(.03):
                    raise RemoteCancelled("Recognition cancelled.")
                try:
                    job = self.get(job["id"],wait=2)
                except ServerError as error:
                    if getattr(error, 'permanent', False):
                        raise
                    if cancel.wait(getattr(error, "retry_after", 2)):
                        raise RemoteCancelled("Recognition cancelled.") from None
        except (RemoteCancelled, TimeoutError):
            try:
                self.cancel(job["id"])
            except ServerError:
                pass
            raise
