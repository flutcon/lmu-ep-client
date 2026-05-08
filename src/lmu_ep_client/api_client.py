from __future__ import annotations

import json
import logging
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger(__name__)

DEFAULT_API_HOST = "lmu-ep.vercel.app"
DEFAULT_API_URL = f"https://{DEFAULT_API_HOST}"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"[{status} {code}] {message}")
        self.status = status
        self.code = code
        self.message = message


def _normalize_base_url(api_url: str) -> str:
    s = api_url.strip()
    if not s:
        raise ValueError("api_url cannot be empty")
    if "://" not in s:
        s = "https://" + s
    return s.rstrip("/")


class TrackingClient:
    """Thin HTTP client for the lmu-ep tracking REST API.

    Constructs Bearer-authenticated JSON requests against `api_url`. No state
    is kept beyond credentials; methods are added as endpoints get wired up.
    """

    def __init__(self, api_url: str, api_key: str, timeout: float = 10.0) -> None:
        if not api_key:
            raise ValueError("api_key cannot be empty")
        self.base_url = _normalize_base_url(api_url)
        self._api_key = api_key
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"TrackingClient(base_url={self.base_url!r})"

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        url = self._build_url(path)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib_request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._api_key}")
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")

        try:
            with urllib_request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib_error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            raise ApiError(
                status=e.code,
                code=payload.get("code", "UNKNOWN"),
                message=payload.get("error", raw or e.reason or ""),
            ) from None
        except urllib_error.URLError as e:
            raise ApiError(status=0, code="NETWORK", message=str(e.reason)) from None

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, body: dict | None = None) -> Any:
        return self._request("POST", path, body=body)

    def patch(self, path: str, body: dict | None = None) -> Any:
        return self._request("PATCH", path, body=body)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def list_registrations(self) -> list[dict]:
        return self.get("/api/tracking/registrations")

    def create_session(self, registration_id: str) -> dict:
        return self.post(f"/api/tracking/registrations/{registration_id}/session")

    def get_session(self, registration_id: str) -> dict:
        return self.get(f"/api/tracking/registrations/{registration_id}/session")
