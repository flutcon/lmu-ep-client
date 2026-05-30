import pytest

from lmu_ep_client import updater
from lmu_ep_client.updater import Action, _decide, maybe_update


# --- _decide: the pure policy, exhaustively ---------------------------------

def test_decide_skips_when_not_frozen():
    assert _decide(
        frozen=False, disabled=False, update_available=True, required=True, apply_optional=True
    ) is Action.SKIP


def test_decide_skips_when_disabled():
    assert _decide(
        frozen=True, disabled=True, update_available=True, required=True, apply_optional=True
    ) is Action.SKIP


def test_decide_up_to_date_when_no_update():
    assert _decide(
        frozen=True, disabled=False, update_available=False, required=False, apply_optional=True
    ) is Action.UP_TO_DATE


def test_decide_applies_optional_when_caller_opts_in():
    assert _decide(
        frozen=True, disabled=False, update_available=True, required=False, apply_optional=True
    ) is Action.APPLY


def test_decide_notify_only_for_optional_when_caller_declines():
    assert _decide(
        frozen=True, disabled=False, update_available=True, required=False, apply_optional=False
    ) is Action.NOTIFY_ONLY


def test_decide_applies_required_even_when_caller_declines():
    assert _decide(
        frozen=True, disabled=False, update_available=True, required=True, apply_optional=False
    ) is Action.APPLY


# --- maybe_update: integration over a fake client (no network) --------------

class _FakeTarget:
    def __init__(self, version="0.1.1", required=False):
        self.version = version
        self.custom_internal = {"required": True} if required else {}


class _FakeClient:
    def __init__(self, *, update=None, raises=False):
        self._update = update
        self._raises = raises
        self.applied = False
        self.apply_kwargs = None

    def check_for_updates(self):
        if self._raises:
            raise RuntimeError("network down")
        return self._update

    def download_and_apply_update(self, **kwargs):
        # The real installer exits the process here; the fake just records.
        self.applied = True
        self.apply_kwargs = kwargs


@pytest.fixture
def frozen_enabled(monkeypatch):
    """Pretend we are a frozen build with update enabled and a trust anchor."""
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater, "update_disabled", lambda: False)
    monkeypatch.setattr(updater, "_ensure_trusted_root", lambda _dir: True)


def _run(client, *, apply_optional, relaunch=False):
    return maybe_update(
        apply_optional=apply_optional,
        relaunch=relaunch,
        current_version="0.1.0",
        client_factory=lambda _v: client,
    )


def test_maybe_update_skips_when_not_frozen(monkeypatch):
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    called = False

    def factory(_v):
        nonlocal called
        called = True
        return _FakeClient()

    assert maybe_update(apply_optional=True, relaunch=True, client_factory=factory) is Action.SKIP
    assert called is False  # never even built a client


def test_maybe_update_skips_when_disabled(monkeypatch, frozen_enabled):
    monkeypatch.setattr(updater, "update_disabled", lambda: True)
    client = _FakeClient(update=_FakeTarget())
    assert _run(client, apply_optional=True) is Action.SKIP
    assert client.applied is False


def test_maybe_update_up_to_date(frozen_enabled):
    assert _run(_FakeClient(update=None), apply_optional=True) is Action.UP_TO_DATE


def test_maybe_update_applies_optional_when_opted_in(frozen_enabled):
    client = _FakeClient(update=_FakeTarget(required=False))
    assert _run(client, apply_optional=True) is Action.APPLY
    assert client.applied is True


def test_maybe_update_notify_only_for_optional_headless(frozen_enabled):
    client = _FakeClient(update=_FakeTarget(required=False))
    assert _run(client, apply_optional=False) is Action.NOTIFY_ONLY
    assert client.applied is False


def test_maybe_update_applies_required_even_headless(frozen_enabled):
    client = _FakeClient(update=_FakeTarget(required=True))
    assert _run(client, apply_optional=False) is Action.APPLY
    assert client.applied is True


def test_maybe_update_fails_open_on_error(frozen_enabled):
    client = _FakeClient(raises=True)
    assert _run(client, apply_optional=True) is Action.SKIP
    assert client.applied is False


def test_maybe_update_skips_when_no_trust_anchor(monkeypatch, frozen_enabled):
    monkeypatch.setattr(updater, "_ensure_trusted_root", lambda _dir: False)
    client = _FakeClient(update=_FakeTarget())
    assert _run(client, apply_optional=True) is Action.SKIP
    assert client.applied is False


def test_maybe_update_fails_open_when_trust_anchor_seeding_raises(monkeypatch, frozen_enabled):
    # An unwritable LOCALAPPDATA / blocked metadata path must not crash startup.
    def boom(_dir):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(updater, "_ensure_trusted_root", boom)
    client = _FakeClient(update=_FakeTarget())
    assert _run(client, apply_optional=True) is Action.SKIP
    assert client.applied is False
