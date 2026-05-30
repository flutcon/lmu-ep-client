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
    bundle_dir = cfg.PACKAGING_DIR / "bundle"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)
    shutil.copyfile(exe, bundle_dir / cfg.EXE_NAME)
    return bundle_dir


def _upload(targets_dir, metadata_dir, *, do_upload: bool) -> None:
    archive = targets_dir / f"{cfg.APP_NAME}-{__version__}.tar.gz"
    new_targets = [p for p in (archive,) if p.exists()]
    new_targets += list(targets_dir.glob(f"{cfg.APP_NAME}-{__version__}.*.patch"))

    print("\nTo publish this release to the update host:")
    print(f"  1. Upload target archive(s) to the '{cfg.GITHUB_RELEASE_TAG}' release:")
    files = " ".join(f'"{p}"' for p in new_targets)
    gh_cmd = ["gh", "release", "upload", cfg.GITHUB_RELEASE_TAG, *[str(p) for p in new_targets], "--clobber"]
    print(f"       gh release upload {cfg.GITHUB_RELEASE_TAG} {files} --clobber")
    print(f"  2. Publish the metadata in {metadata_dir} to the '{cfg.PAGES_BRANCH}' "
          "branch under /metadata/ (GitHub Pages).")

    if do_upload:
        print("\n--upload: running the gh release upload step (additive)...")
        result = subprocess.run(gh_cmd)
        if result.returncode != 0:
            raise SystemExit("gh release upload failed; see output above.")
        print("Targets uploaded. Metadata must still be pushed to Pages (step 2).")


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
        help="Also run the (additive) gh release upload for the new archive.",
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
    print(f"Published {kind} update v{__version__}.")
    _upload(cfg.REPO_DIR / "targets", cfg.REPO_DIR / "metadata", do_upload=args.upload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
