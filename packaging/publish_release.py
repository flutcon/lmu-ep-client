"""Package the current exe as a new signed update and publish it.

Run after building (`pyinstaller lmu-ep-client.spec`) so `dist/lmu-ep-client.exe`
reflects the version in `lmu_ep_client.__version__`:

    python packaging/publish_release.py            # optional update
    python packaging/publish_release.py --required # forced update
    python packaging/publish_release.py --upload    # also push to the host

Steps performed locally (always):
  1. stage the exe into a one-file bundle dir,
  2. tufup add_bundle (reads the version from lmu_ep_client.__version__),
  3. tufup publish_changes (signs targets/snapshot/timestamp metadata).

Publishing to the host (GitHub Pages metadata + a rolling GitHub release for
the target archives) is additive and only runs with --upload; otherwise the
exact commands are printed for you to review and run.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import repo_settings as cfg

cfg.enter_packaging_dir()

from lmu_ep_client import __version__  # noqa: E402
from tufup.repo import Repository  # noqa: E402


def _stage_bundle() -> "object":
    exe = cfg.DIST_DIR / cfg.EXE_NAME
    if not exe.exists():
        raise SystemExit(
            f"Built exe not found at {exe}. Run `pyinstaller lmu-ep-client.spec` first."
        )
    # Stage into a fresh temp dir (outside the OneDrive-synced tree) — deleting
    # a dir under OneDrive can intermittently fail with WinError 5 while the
    # sync client holds a handle. add_bundle only needs a dir holding the exe.
    bundle_dir = Path(tempfile.mkdtemp(prefix="lmu-ep-bundle-"))
    shutil.copyfile(exe, bundle_dir / cfg.EXE_NAME)
    return bundle_dir


def _new_target_files(targets_dir):
    archive = targets_dir / f"{cfg.APP_NAME}-{__version__}.tar.gz"
    files = [p for p in (archive,) if p.exists()]
    files += sorted(targets_dir.glob(f"{cfg.APP_NAME}-{__version__}.*.patch"))
    return files


def _git(*args, cwd=cfg.PROJECT_ROOT, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check)


def _upload_targets(targets_dir) -> None:
    """Attach the new version's archive (+ any patch) to the rolling release."""
    files = _new_target_files(targets_dir)
    if not files:
        raise SystemExit(f"No target files for v{__version__} found in {targets_dir}.")
    print(f"Uploading {len(files)} target file(s) to the '{cfg.GITHUB_RELEASE_TAG}' release...")
    result = subprocess.run(
        ["gh", "release", "upload", cfg.GITHUB_RELEASE_TAG, *map(str, files), "--clobber"]
    )
    if result.returncode != 0:
        raise SystemExit("gh release upload failed; see output above.")


def _push_metadata_to_pages(metadata_dir) -> None:
    """Sync the freshly-signed metadata into the gh-pages branch and push.

    Uses a throwaway detached worktree based on origin/<PAGES_BRANCH> and pushes
    HEAD back to that branch, so it always fast-forwards from the remote tip and
    never disturbs the maintainer's main checkout or a local branch.
    """
    metadata_dir = metadata_dir.resolve()
    worktree = Path(tempfile.mkdtemp(prefix="lmu-ep-pages-"))
    try:
        _git("fetch", "origin", cfg.PAGES_BRANCH)
        _git("worktree", "add", "--detach", str(worktree), f"origin/{cfg.PAGES_BRANCH}")
        dst = worktree / "metadata"
        dst.mkdir(exist_ok=True)
        for f in metadata_dir.iterdir():
            if f.is_file():
                shutil.copyfile(f, dst / f.name)
        _git("add", "metadata", cwd=worktree)
        if _git("diff", "--cached", "--quiet", cwd=worktree, check=False).returncode == 0:
            print("Pages metadata already up to date; nothing to push.")
            return
        _git("commit", "-m", f"Publish update metadata v{__version__}", cwd=worktree)
        _git("push", "origin", f"HEAD:{cfg.PAGES_BRANCH}", cwd=worktree)
        print(f"Pushed metadata to '{cfg.PAGES_BRANCH}' (served at the Pages metadata URL).")
    finally:
        _git("worktree", "remove", str(worktree), "--force", check=False)
        _git("worktree", "prune", check=False)


def _print_manual_steps(targets_dir, metadata_dir) -> None:
    files = " ".join(f'"{p}"' for p in _new_target_files(targets_dir))
    print("\nNot published (run again with --upload, or do it manually):")
    print(f"  1. gh release upload {cfg.GITHUB_RELEASE_TAG} {files} --clobber")
    print(f"  2. Push the metadata in {metadata_dir} to the "
          f"'{cfg.PAGES_BRANCH}' branch under /metadata/.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a signed client update.")
    parser.add_argument(
        "--required",
        action="store_true",
        help="Mark this release as a forced update (clients cannot defer it).",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Publish to the host: upload the archive to the rolling release AND "
             "push the signed metadata to the gh-pages branch.",
    )
    args = parser.parse_args()

    bundle_dir = _stage_bundle()

    repo = Repository.from_config()
    repo.add_bundle(new_bundle_dir=bundle_dir, required=args.required)
    repo.publish_changes(private_key_dirs=[cfg.KEYS_DIR])

    # Refresh the committed trust anchor in case root was re-signed.
    root_src = cfg.REPO_DIR / "metadata" / "root.json"
    if root_src.exists():
        shutil.copyfile(root_src, cfg.TRUSTED_DIR / "root.json")

    kind = "required" if args.required else "optional"
    print(f"Signed {kind} update v{__version__}.")

    targets_dir = (cfg.PACKAGING_DIR / cfg.REPO_DIR / "targets")
    metadata_dir = (cfg.PACKAGING_DIR / cfg.REPO_DIR / "metadata")
    if args.upload:
        _upload_targets(targets_dir)
        _push_metadata_to_pages(metadata_dir)
        print(f"\nPublished v{__version__}. Commit packaging/trusted/root.json if it changed.")
    else:
        _print_manual_steps(targets_dir, metadata_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
