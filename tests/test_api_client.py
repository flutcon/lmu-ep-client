import io
import json
import logging
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from lmu_ep_client.api_client import (
    DEFAULT_API_HOST,
    DEFAULT_API_URL,
    ApiError,
    TrackingClient,
    _normalize_base_url,
)


def test_default_api_url():
    assert DEFAULT_API_HOST == "lmu-ep.vercel.app"
    assert DEFAULT_API_URL == "https://lmu-ep.vercel.app"


def test_normalize_bare_host_adds_https():
    assert _normalize_base_url("lmu-ep.vercel.app") == "https://lmu-ep.vercel.app"


def test_normalize_strips_trailing_slash():
    assert _normalize_base_url("https://lmu-ep.vercel.app/") == "https://lmu-ep.vercel.app"


def test_normalize_preserves_explicit_scheme():
    assert _normalize_base_url("http://localhost:3000") == "http://localhost:3000"


def test_normalize_preserves_path_prefix():
    assert _normalize_base_url("https://host.com/staging/") == "https://host.com/staging"


def test_normalize_rejects_empty():
    with pytest.raises(ValueError):
        _normalize_base_url("   ")


def test_client_rejects_empty_key():
    with pytest.raises(ValueError):
        TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="")


def test_client_repr_does_not_leak_key():
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="lmu_secret_12345")
    assert "secret" not in repr(c)
    assert "12345" not in repr(c)


def test_build_url_handles_leading_slash():
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="k")
    assert c._build_url("/api/tracking/registrations") == "https://lmu-ep.vercel.app/api/tracking/registrations"
    assert c._build_url("api/tracking/registrations") == "https://lmu-ep.vercel.app/api/tracking/registrations"


def test_build_url_with_path_prefix():
    c = TrackingClient(api_url="https://host.com/staging", api_key="k")
    assert c._build_url("/api/tracking/registrations") == "https://host.com/staging/api/tracking/registrations"


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_get_sends_bearer_and_parses_json():
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="lmu_abc_123")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["auth"] = req.get_header("Authorization")
        captured["accept"] = req.get_header("Accept")
        captured["timeout"] = timeout
        return _FakeResponse(b'[{"id":"r1"}]')

    with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=fake_urlopen):
        result = c.get("/api/tracking/registrations")

    assert result == [{"id": "r1"}]
    assert captured["url"] == "https://lmu-ep.vercel.app/api/tracking/registrations"
    assert captured["method"] == "GET"
    assert captured["auth"] == "Bearer lmu_abc_123"
    assert captured["accept"] == "application/json"


def test_post_sends_json_body_with_content_type():
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="k")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["method"] = req.get_method()
        captured["content_type"] = req.get_header("Content-type")
        captured["body"] = req.data
        return _FakeResponse(b'{"id":"e1"}')

    with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=fake_urlopen):
        result = c.post("/api/tracking/events", body={"type": "pitstop"})

    assert result == {"id": "e1"}
    assert captured["method"] == "POST"
    assert captured["content_type"] == "application/json"
    assert json.loads(captured["body"]) == {"type": "pitstop"}


def test_delete_returns_none_for_empty_body():
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="k")

    def fake_urlopen(req, timeout):
        assert req.get_method() == "DELETE"
        assert req.data is None
        return _FakeResponse(b"")

    with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=fake_urlopen):
        assert c.delete("/api/tracking/events/abc") is None


def test_patch_with_body():
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="k")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["method"] = req.get_method()
        captured["body"] = req.data
        return _FakeResponse(b'{"status":"ended"}')

    with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=fake_urlopen):
        result = c.patch("/api/tracking/registrations/r1/session", body={"status": "ended"})

    assert result == {"status": "ended"}
    assert captured["method"] == "PATCH"
    assert json.loads(captured["body"]) == {"status": "ended"}


def test_http_error_parses_envelope():
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="k")
    err_body = json.dumps({"error": "Registration not found", "code": "NOT_FOUND"}).encode("utf-8")
    http_err = HTTPError(
        url="https://lmu-ep.vercel.app/x",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=io.BytesIO(err_body),
    )

    with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=http_err):
        with pytest.raises(ApiError) as excinfo:
            c.get("/x")

    assert excinfo.value.status == 404
    assert excinfo.value.code == "NOT_FOUND"
    assert excinfo.value.message == "Registration not found"


def test_http_error_with_non_json_body():
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="k")
    http_err = HTTPError(
        url="https://lmu-ep.vercel.app/x",
        code=500,
        msg="Internal",
        hdrs=None,
        fp=io.BytesIO(b"<html>oops</html>"),
    )

    with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=http_err):
        with pytest.raises(ApiError) as excinfo:
            c.get("/x")

    assert excinfo.value.status == 500
    assert excinfo.value.code == "UNKNOWN"
    assert "oops" in excinfo.value.message


def test_list_registrations_calls_correct_path():
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="k")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        return _FakeResponse(b"[]")

    with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=fake_urlopen):
        result = c.list_registrations()

    assert result == []
    assert captured["url"] == "https://lmu-ep.vercel.app/api/tracking/registrations"
    assert captured["method"] == "GET"


def test_create_session_posts_to_correct_path():
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="k")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        return _FakeResponse(b'{"id":"s1"}')

    with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=fake_urlopen):
        result = c.create_session("reg-uuid")

    assert result == {"id": "s1"}
    assert captured["url"] == "https://lmu-ep.vercel.app/api/tracking/registrations/reg-uuid/session"
    assert captured["method"] == "POST"


def test_get_session_calls_correct_path():
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="k")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        return _FakeResponse(b'{"id":"s1","teamMembers":[]}')

    with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=fake_urlopen):
        result = c.get_session("reg-uuid")

    assert result == {"id": "s1", "teamMembers": []}
    assert captured["url"] == "https://lmu-ep.vercel.app/api/tracking/registrations/reg-uuid/session"
    assert captured["method"] == "GET"


def test_network_error_wrapped():
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="k")

    with patch(
        "lmu_ep_client.api_client.urllib_request.urlopen",
        side_effect=URLError("connection refused"),
    ):
        with pytest.raises(ApiError) as excinfo:
            c.get("/x")

    assert excinfo.value.status == 0
    assert excinfo.value.code == "NETWORK"


class _StatusFakeResponse(_FakeResponse):
    def __init__(self, body: bytes, status: int = 200) -> None:
        super().__init__(body)
        self.status = status


def test_debug_logs_request_and_response(caplog):
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="lmu_secret_xyz")

    def fake_urlopen(req, timeout):
        return _StatusFakeResponse(b'{"id":"e1"}', status=201)

    with caplog.at_level(logging.DEBUG, logger="lmu_ep_client.api_client"):
        with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=fake_urlopen):
            c.post("/api/tracking/events", body={"type": "pitstop"})

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "-> POST https://lmu-ep.vercel.app/api/tracking/events" in text
    assert '"type": "pitstop"' in text
    assert "<- POST 201" in text
    assert '"id":"e1"' in text


def test_debug_logs_do_not_leak_bearer_token(caplog):
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="lmu_secret_xyz")

    def fake_urlopen(req, timeout):
        return _StatusFakeResponse(b'{}', status=200)

    with caplog.at_level(logging.DEBUG, logger="lmu_ep_client.api_client"):
        with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=fake_urlopen):
            c.get("/api/tracking/registrations")

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "lmu_secret_xyz" not in text
    assert "Bearer" not in text


def test_debug_logs_http_error_body(caplog):
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="k")
    err_body = json.dumps({"error": "Bad token", "code": "UNAUTHORIZED"}).encode("utf-8")
    http_err = HTTPError(
        url="https://lmu-ep.vercel.app/x",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=io.BytesIO(err_body),
    )

    with caplog.at_level(logging.DEBUG, logger="lmu_ep_client.api_client"):
        with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=http_err):
            with pytest.raises(ApiError):
                c.get("/x")

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "<- GET 401" in text
    assert "UNAUTHORIZED" in text


def test_debug_truncates_large_response(caplog):
    c = TrackingClient(api_url="https://lmu-ep.vercel.app", api_key="k")
    big = b'"' + b"x" * 5000 + b'"'

    def fake_urlopen(req, timeout):
        return _StatusFakeResponse(big, status=200)

    with caplog.at_level(logging.DEBUG, logger="lmu_ep_client.api_client"):
        with patch("lmu_ep_client.api_client.urllib_request.urlopen", side_effect=fake_urlopen):
            c.get("/x")

    body_lines = [r.getMessage() for r in caplog.records if "body:" in r.getMessage()]
    assert any("truncated" in line for line in body_lines)
