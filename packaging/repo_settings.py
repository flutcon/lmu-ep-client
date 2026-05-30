"""Shared configuration for the tufup update-repository tooling.

These scripts run on the *maintainer's* machine, not in the shipped client.
tufup stores its repo config (.tufup-repo-config) in the current working
directory, so both repo_init.py and publish_release.py chdir into this
`packaging/` folder (via `enter_packaging_dir`) before touching the repo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "lmu-ep-client"
APP_VERSION_ATTR = "lmu_ep_client.__version__"

PACKAGING_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGING_DIR.parent

# Relative to PACKAGING_DIR (the scripts chdir there). tufup writes its config
# with cwd-relative paths, so keep these relative for portability.
REPO_DIR = Path("repository")  # holds metadata/ and targets/ (gitignored)
KEYS_DIR = Path("keys")  # PRIVATE signing keys — gitignored, BACK UP
TRUSTED_DIR = PACKAGING_DIR / "trusted"  # committed; public root.json for bundling

DIST_DIR = PROJECT_ROOT / "dist"  # PyInstaller output
EXE_NAME = f"{APP_NAME}.exe"

# Generous lifetimes for a low-cadence solo project; long enough that clients
# keep verifying between releases without constant re-signing.
EXPIRATION_DAYS = {"root": 365, "targets": 30, "snapshot": 30, "timestamp": 7}

# Rolling GitHub release tag that holds the target archives, and the Pages
# branch that serves the metadata. Used by publish_release.py.
GITHUB_RELEASE_TAG = "updates"
PAGES_BRANCH = "gh-pages"


def enter_packaging_dir() -> None:
    """Put `src/` on the path (so `lmu_ep_client.__version__` imports) and
    chdir into `packaging/` so tufup's config + relative paths resolve here."""
    src = str(PROJECT_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    os.chdir(PACKAGING_DIR)
