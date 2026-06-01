---
name: release
description: Build and publish a new lmu-ep-client release (version bump → build exe → tufup sign → upload to gh-pages + rolling release → push main). Use when the user asks to "do a release", "build and publish", "ship a new version", or "release X.Y.Z".
---

# Release runbook

Cut and publish a new auto-update release. Run the happy path end-to-end **without
asking questions**. The moment anything deviates from the expected output below,
**stop and report it before continuing** — do not paper over or retry blindly.

Single source of truth for the version is `src/lmu_ep_client/__init__.py`
(`__version__`); pyproject and tufup both read it. See README "Releasing updates"
and CLAUDE.md "Versioning & auto-update".

## Environment gotchas (these bit me — honor them)

- **Use the `PowerShell` tool for every `.venv` / python / pyinstaller / git /
  gh command.** The `Bash` tool mangles Windows paths like
  `.\.venv\Scripts\python.exe` into garbage (`..venvScriptspython.exe: command
  not found`).
- **Scope pytest to `tests/`.** A bare `pytest` at the repo root fails collection
  on stale `pytest-tmp-*` dirs that OneDrive locks (`PermissionError WinError 5`).
  Those dirs are unrelated leftovers — note them, don't try to delete them mid-run.
- **PowerShell wraps native-command stderr in red `NativeCommandError` text** for
  `git`/`gh`. That is NOT a failure. Judge success by the real output line (e.g.
  `ae175aa..9bf9673  main -> main`), not by the red wrapper.
- **No `<` or `>` in `git commit -m` here-strings** — PowerShell mis-parses them.
  Keep commit messages free of angle brackets.
- **The exe is windowed (`runw.exe`).** It can still print `--version`, but it
  writes to the console device (`CONOUT$`), which **bypasses a captured
  PowerShell pipe** — `$v = & .\dist\...exe --version` comes back empty. Capture
  it through cmd instead, which hands the exe a real inherited console:
  `cmd /c ".\dist\lmu-ep-client.exe --version"` → prints `lmu-ep-client X.Y.Z`.

## Steps

### 0. Pre-flight (report any failure, then stop)
- `git status` → working tree clean apart from the `pytest-tmp-*` warnings. If
  there are uncommitted source changes, report them and stop (don't release a
  dirty tree).
- Confirm there are unreleased commits worth shipping: `git log origin/main..HEAD --oneline`.
- Confirm prereqs exist: `.venv\Scripts\python.exe`, `.venv\Scripts\pyinstaller.exe`,
  `packaging/keys/` (8 key files), `packaging/repository/metadata/`, and
  `gh auth status` shows logged in. Missing any → report and stop.

### 1. Tests
```
.\.venv\Scripts\python.exe -m pytest tests -q
```
Any failure → report and stop.

### 2. Bump version + commit
- Read current `__version__` and bump the **patch** by default (e.g. 0.1.5 → 0.1.6).
  If the unreleased commits clearly warrant a minor/major bump, that is a
  judgement call worth a one-line heads-up — but patch is the happy-path default.
- Edit `src/lmu_ep_client/__init__.py`.
- Commit (no angle brackets in the message):
```
git add src/lmu_ep_client/__init__.py
git commit -m @'
release: X.Y.Z

<one-line summary of what the unreleased commits deliver>; published through
auto-update.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

### 3. Build the exe
```
.\.venv\Scripts\pyinstaller.exe lmu-ep-client.spec --noconfirm
```
Expect `Build complete!` and `dist/lmu-ep-client.exe`. Build error → report and stop.

Then verify the built exe reports the bumped version (must match step 2):
```
cmd /c ".\dist\lmu-ep-client.exe --version"
```
Expect `lmu-ep-client X.Y.Z`. Mismatch or empty → report and stop (do not publish
an exe whose version you could not confirm).

### 4. Sign, upload, and push metadata
```
.\.venv\Scripts\python.exe packaging\publish_release.py --upload
```
`--upload` uploads BOTH target files (`...-X.Y.Z.tar.gz` + `...-X.Y.Z.patch`) to
the `updates` release AND pushes signed metadata to `gh-pages`. Expect to see
`Signed optional update vX.Y.Z`, `Uploading 2 target file(s)`, `Pushed metadata
to 'gh-pages'`, `Published vX.Y.Z`. Any upload/push error → report and stop.

Use `--required` instead of `--upload`'s optional default only when the user asks
for a forced update (`publish_release.py --required --upload`).

### 5. Finalize git
- `git status` → if `packaging/trusted/root.json` changed (root was re-signed),
  commit it: `git add packaging/trusted/root.json; git commit -m "..."`. Usually
  it does NOT change.
- Push: `git push origin main` (carries the release commit + the feature commits).

### 6. Verify
```
gh release view updates --json assets --jq '.assets[].name'
```
Confirm `lmu-ep-client-X.Y.Z.tar.gz` and `lmu-ep-client-X.Y.Z.patch` are listed.

## Done report
Summarize: version, test result, assets uploaded, gh-pages metadata pushed,
whether root.json changed, and the `main` push ref range. Note that Pages can
take a minute or two to propagate, and that clients pick up optional updates on
next launch.
