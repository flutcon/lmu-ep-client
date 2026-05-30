"""In-app auto-update via tufup (TUF-signed updates).

The client checks a signed update repository on startup and, depending on the
caller's policy, silently downloads and installs a newer build. Updates are
only ever applied to the *frozen* PyInstaller exe — never in a dev checkout.

Design notes:
- The update *channel* is signed (TUF), so a compromised host cannot push
  arbitrary code. The trust anchor (`root.json`) is bundled inside the exe and
  copied to the per-user metadata dir on first run.
- Every code path **fails open**: any network/verification error logs and
  returns SKIP so a down or unreachable update host never blocks launch.
- `tufup.client.Client.download_and_apply_update` launches a Windows batch
  script that swaps the files once this process exits, then calls
  ``sys.exit(0)`` itself. That exit must happen on the *main* thread so the
  whole process dies and releases the exe lock — never call apply from a Qt
  worker thread.
- GUI relaunches automatically (it takes no args). CLI must NOT auto-relaunch:
  an argless restart would drop the user's flags and fall back into GUI mode,
  so CLI applies-then-exits and asks the user to re-run.
"""

from __future__ import annotations

import enum
import logging
import os
import shutil
import socket
import sys
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "lmu-ep-client"

# Hosting (GitHub Pages for metadata, a rolling GitHub release for targets).
# Both are overridable via env so the host can change without a rebuild.
DEFAULT_METADATA_BASE_URL = "https://flutcon.github.io/lmu-ep-client/metadata/"
DEFAULT_TARGET_BASE_URL = (
    "https://github.com/flutcon/lmu-ep-client/releases/download/updates/"
)

ENV_METADATA_URL = "LMU_EP_UPDATE_METADATA_URL"
ENV_TARGET_URL = "LMU_EP_UPDATE_TARGET_URL"
ENV_DISABLE = "LMU_EP_DISABLE_UPDATE"

TRUSTED_ROOT_FILENAME = "root.json"

# Bound any single socket operation during the update so a stalled connection
# can't hang startup indefinitely. Applies per-recv, not to the whole download.
_NETWORK_TIMEOUT_S = 15.0

# Custom Windows batch that moves the new files in, then relaunches the exe.
# Template vars ({src_dir}, {dst_dir}, {robocopy_options}, {log_lines},
# {delete_self}) are filled by tufup's _install_update_win.
_WIN_RESTART_BATCH = (
    "@echo off\n"
    "{log_lines}\n"
    "echo Moving app files...\n"
    'robocopy "{src_dir}" "{dst_dir}" {robocopy_options}\n'
    "echo Restarting...\n"
    'start "" "{dst_dir}\\' + APP_NAME + '.exe"\n'
    "{delete_self}\n"
)


class Action(enum.Enum):
    """What the updater decided to do on a given startup."""

    SKIP = "skip"  # not frozen, disabled, or an error occurred (fail open)
    UP_TO_DATE = "up_to_date"
    NOTIFY_ONLY = "notify_only"  # update exists but policy declined to apply it
    APPLY = "apply"  # update is being installed (process will exit)


def is_frozen() -> bool:
    """True when running as the bundled PyInstaller exe (vs. a dev checkout)."""
    return bool(getattr(sys, "frozen", False))


def update_disabled() -> bool:
    return bool(os.environ.get(ENV_DISABLE, "").strip())


def _update_data_dir() -> Path:
    """Per-user, machine-local dir for tufup's metadata + target caches.

    Mirrors logging_setup.default_log_dir: LOCALAPPDATA on Windows so the cache
    doesn't roam.
    """
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / APP_NAME / "update"


def _metadata_dir() -> Path:
    return _update_data_dir() / "metadata"


def _target_dir() -> Path:
    return _update_data_dir() / "target"


def _metadata_base_url() -> str:
    return os.environ.get(ENV_METADATA_URL, "").strip() or DEFAULT_METADATA_BASE_URL


def _target_base_url() -> str:
    return os.environ.get(ENV_TARGET_URL, "").strip() or DEFAULT_TARGET_BASE_URL


def _bundled_root_path() -> Path:
    """Path to the trust anchor bundled into the exe (via the PyInstaller spec)."""
    base = getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent
    return Path(base) / TRUSTED_ROOT_FILENAME


def _ensure_trusted_root(metadata_dir: Path) -> bool:
    """Seed the metadata dir with the bundled root.json if it's not there yet.

    Returns False (and logs) if no trust anchor is available, in which case the
    updater cannot run.
    """
    dst = metadata_dir / TRUSTED_ROOT_FILENAME
    if dst.exists():
        return True
    src = _bundled_root_path()
    if not src.exists():
        logger.warning("No bundled trust anchor at %s; auto-update disabled.", src)
        return False
    metadata_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    logger.info("Installed trusted root metadata to %s", dst)
    return True


def _decide(
    *,
    frozen: bool,
    disabled: bool,
    update_available: bool,
    required: bool,
    apply_optional: bool,
) -> Action:
    """Pure update policy. Kept side-effect-free so it's exhaustively testable.

    - Not frozen or disabled  -> SKIP (never touch a dev checkout / opt-out)
    - No newer version         -> UP_TO_DATE
    - Required, or caller opted to apply optional updates -> APPLY
    - Otherwise (optional, caller declined)               -> NOTIFY_ONLY
    """
    if not frozen or disabled:
        return Action.SKIP
    if not update_available:
        return Action.UP_TO_DATE
    if required or apply_optional:
        return Action.APPLY
    return Action.NOTIFY_ONLY


def _make_client(current_version: str):
    from tufup.client import Client

    # tufup/tuf do not create these cache dirs themselves; the target dir in
    # particular must exist before a download, or tuf raises FileNotFoundError
    # opening the destination file.
    metadata_dir = _metadata_dir()
    target_dir = _target_dir()
    metadata_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    return Client(
        app_name=APP_NAME,
        app_install_dir=Path(sys.executable).parent,
        current_version=current_version,
        metadata_dir=metadata_dir,
        metadata_base_url=_metadata_base_url(),
        target_dir=target_dir,
        target_base_url=_target_base_url(),
        refresh_required=False,
    )


def _is_required(target_meta) -> bool:
    from tufup.common import KEY_REQUIRED

    custom = getattr(target_meta, "custom_internal", None)
    return bool(custom and custom.get(KEY_REQUIRED))


def _apply(client, *, relaunch: bool, on_status: Callable[[str], None]) -> None:
    """Download and install the pending update. Does not return on success:
    tufup's installer launches the swap script and calls ``sys.exit(0)``.
    """

    def progress_hook(bytes_downloaded: int, bytes_expected: int) -> None:
        # tufup calls this with keyword args (bytes_downloaded=, bytes_expected=),
        # so the parameter names must match exactly.
        if bytes_expected:
            on_status(f"Downloading update… {bytes_downloaded / bytes_expected * 100:.0f}%")

    kwargs: dict = {"purge_dst_dir": False, "progress_hook": progress_hook}
    if os.name == "nt":
        import subprocess

        kwargs["log_file_name"] = "update-install.log"
        # Hide the batch console window from the user.
        kwargs["process_creation_flags"] = subprocess.CREATE_NO_WINDOW
        if relaunch:
            kwargs["batch_template"] = _WIN_RESTART_BATCH
    on_status("Installing update…")
    client.download_and_apply_update(skip_confirmation=True, **kwargs)


def maybe_update(
    *,
    apply_optional: bool,
    relaunch: bool,
    on_status: Callable[[str], None] | None = None,
    current_version: str | None = None,
    client_factory: Callable[[str], object] | None = None,
) -> Action:
    """Check for and, per policy, apply an update. Returns the chosen Action.

    On APPLY the process normally exits inside this call (tufup installer), so
    callers should treat a return as "did not restart".

    `apply_optional` controls whether *optional* updates are installed
    automatically (required updates always are). `relaunch` selects the GUI
    (auto-restart) vs. CLI (apply-then-exit) install behaviour. `client_factory`
    and `current_version` are injection seams for tests.
    """
    status = on_status or (lambda _msg: None)

    if not is_frozen():
        logger.debug("Not a frozen build; skipping update check.")
        return Action.SKIP
    if update_disabled():
        logger.info("Auto-update disabled via %s.", ENV_DISABLE)
        return Action.SKIP

    if current_version is None:
        from lmu_ep_client import __version__

        current_version = __version__

    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(_NETWORK_TIMEOUT_S)
    try:
        # Inside the try so a filesystem error (unwritable LOCALAPPDATA, a file
        # blocking the metadata path, a failed copy) fails open rather than
        # crashing startup.
        if not _ensure_trusted_root(_metadata_dir()):
            return Action.SKIP
        status("Checking for updates…")
        factory = client_factory or _make_client
        client = factory(current_version)
        new = client.check_for_updates()

        update_available = new is not None
        required = update_available and _is_required(new)
        action = _decide(
            frozen=True,
            disabled=False,
            update_available=update_available,
            required=required,
            apply_optional=apply_optional,
        )

        if action is Action.UP_TO_DATE:
            logger.info("Client is up to date (v%s).", current_version)
        elif action is Action.NOTIFY_ONLY:
            logger.info(
                "Update %s available but not applied (optional, policy declined).",
                getattr(new, "version", "?"),
            )
            status("An update is available. Restart interactively to install it.")
        elif action is Action.APPLY:
            logger.info(
                "Applying %supdate to %s.",
                "required " if required else "",
                getattr(new, "version", "?"),
            )
            _apply(client, relaunch=relaunch, on_status=status)  # exits on success
        return action
    except SystemExit:
        raise  # tufup's installer exiting the process — let it through
    except Exception:
        logger.exception("Update check failed; continuing with current version.")
        return Action.SKIP
    finally:
        socket.setdefaulttimeout(previous_timeout)
