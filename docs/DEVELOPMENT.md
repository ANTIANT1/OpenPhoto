# Development

Use Windows x64, Python 3.12, uv, Node.js 22, Git, and Microsoft Edge. The [README](../README.md) covers running the complete application. The following commands run from the repository root in PowerShell.

## Core checks without models

This environment does not download PyTorch, models, or RAW engines. The one PyTorch-specific unit test is expected to skip.

```powershell
uv sync --frozen --extra desktop --extra dev
uv pip install tools/wheels/protobuf-4.25.9+openphoto.1-cp310-abi3-win_amd64.whl
.venv\Scripts\ruff check src scripts tests
.venv\Scripts\python scripts\run_owned.py .venv\Scripts\python -m pytest
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.venv\Scripts\python scripts\verify_editor_races.py .cache\browser-check
```

Use a fresh output directory for each browser run. Playwright is pinned in `frontend/package-lock.json`; the scripts resolve it there, with no global `NODE_PATH` needed. The browser tests use installed Microsoft Edge and synthetic images. They cover races, drafts, catalog selection, comparison, workflow launch, and crop controls; they do not accept the native WebView2 lifecycle or AI image quality.

Switching back to full application work requires `uv sync --frozen --extra desktop --extra ml --extra dev` and the engine/model preparation commands from the README. Core and ML environments can be kept in separate checkouts.

## Source and security checks

```powershell
.venv\Scripts\python scripts\stage_release.py --directory .cache\source-check
.venv\Scripts\python scripts\verify_source.py .cache\source-check
.venv\Scripts\python scripts\scan_secrets.py --source .cache\source-check --output .cache\secret-check
.venv\Scripts\python scripts\scan_secrets.py --source . --history --output .cache\history-check
.venv\Scripts\python scripts\audit_dependencies.py --output .cache\dependency-check
npm.cmd --prefix frontend audit --audit-level=low
```

The secret scanner prepares pinned Gitleaks 8.30.1 using a verified archive hash. It returns failure for findings; reports redact matching values. The dependency check queries advisories for all Python versions in `uv.lock`, including ML packages without installing them. The protobuf backport has a narrow, hash-verified exception; unreviewed findings and skipped packages fail the check. Git-history scanning requires a Git checkout, not a source ZIP.

## Full application and package checks

Use a separate project with photographs you are authorized to test. Do not run acceptance against your only copy of a catalog. Configure `--project` when launching a test instance.

```powershell
.venv\Scripts\python -m openphoto --project .cache\manual-project
.venv\Scripts\python -m openphoto --self-test .cache\diagnostic
```

For the portable application:

```powershell
.\scripts\build_windows.ps1
```

For an installer, install Inno Setup separately and supply its compiler path:

```powershell
.\scripts\build_windows.ps1 -InnoCompiler 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

Both builds include substantial local dependencies. See [release checks](RELEASING.md) before sharing a package. `verify_packaged.py`, `verify_personal.py`, and `verify_quality.py` offer additional acceptance tools; inspect their `--help` and use fresh output directories. Private reports must not be uploaded as public CI artifacts.

## Dependency maintenance

Use `uv.lock` and `frontend/package-lock.json`, not unpinned manual installation. The ML stack deliberately pins MediaPipe, NumPy, and a locally patched protobuf. Review upgrades together, including offline behavior, model hashes, image output compatibility, and licenses. See [dependency review](DEPENDENCY-REVIEW.md).
