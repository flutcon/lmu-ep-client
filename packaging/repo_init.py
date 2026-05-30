"""One-time initialisation of the TUF update repository.

Generates the four TUF signing keys (root, targets, snapshot, timestamp) and
the initial signed metadata, then copies the public `root.json` to
`packaging/trusted/` so the PyInstaller spec can bundle it as the client's
trust anchor.

Run ONCE:

    python packaging/repo_init.py

Then **back up `packaging/keys/`** somewhere safe and offline. Losing those
private keys means you can no longer sign updates that existing clients will
trust — recovery requires shipping a fresh exe with a new root.json.
"""

from __future__ import annotations

import shutil
import sys

import repo_settings as cfg

cfg.enter_packaging_dir()

from tufup.repo import Repository  # noqa: E402  (after path setup)


def main() -> int:
    if cfg.KEYS_DIR.exists() and any(cfg.KEYS_DIR.iterdir()):
        print(
            f"Refusing to overwrite existing keys in {cfg.KEYS_DIR.resolve()}.\n"
            "Delete them manually only if you are certain you want to re-key "
            "(this invalidates all currently-installed clients)."
        )
        return 1

    repo = Repository(
        app_name=cfg.APP_NAME,
        app_version_attr=cfg.APP_VERSION_ATTR,
        repo_dir=cfg.REPO_DIR,
        keys_dir=cfg.KEYS_DIR,
        expiration_days=cfg.EXPIRATION_DAYS,
    )
    repo.save_config()
    repo.initialize()

    cfg.TRUSTED_DIR.mkdir(parents=True, exist_ok=True)
    root_src = cfg.REPO_DIR / "metadata" / "root.json"
    root_dst = cfg.TRUSTED_DIR / "root.json"
    shutil.copyfile(root_src, root_dst)

    print("Update repository initialised.")
    print(f"  metadata:     {(cfg.REPO_DIR / 'metadata').resolve()}")
    print(f"  signing keys: {cfg.KEYS_DIR.resolve()}  <-- BACK THIS UP")
    print(f"  trust anchor: {root_dst}  (committed + bundled into the exe)")
    print("\nNext: build the exe and run packaging/publish_release.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
