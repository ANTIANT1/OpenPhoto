<p align="center"><img src="docs/assets/mark.svg" width="72" height="72" alt="OpenPhoto aperture"></p>

# OpenPhoto

An open-source AI photo editor for organizing, culling, editing, and retouching photos. Everything runs locally on your computer, keeping your photos private.

[![Source checks](https://github.com/ANTIANT1/OpenPhoto/actions/workflows/check.yml/badge.svg)](https://github.com/ANTIANT1/OpenPhoto/actions/workflows/check.yml)
[![License: GPL v3+](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)
![Platform: Windows x64](https://img.shields.io/badge/platform-Windows%20x64-0078D4)
![Status: Preview](https://img.shields.io/badge/status-preview-b8d49b)

[Getting started](#getting-started) · [User guide](docs/USER-GUIDE.md) · [Roadmap](docs/ROADMAP.md) · [Contributing](CONTRIBUTING.md) · [Русский](docs/README.ru.md)

## What it does

| Workflow | Features |
|---|---|
| Organize and cull | Import Sony ARW and JPEG, link RAW+JPEG pairs, compare frames, rate photos, and review AI selections |
| Develop and edit | Reversible recipes, color from reference images, crop and rotation, before/after comparison, and batch adjustments |
| Retouch portraits | Face and body skin masks, adjustable smoothing and color evenness, protected areas, and local corrections |
| Process a shoot | Run analysis, selection, color, retouching, and previews as a resumable job; optionally export JPEG |
| Export | JPEG sRGB, 16-bit TIFF, rating XMP, and OpenPhoto recipes |

Originals stay in place. Edits have a history, manual changes take priority, and removing a photo from the catalog does not delete its source file. After dependencies, engines, and models are prepared, photo processing works offline.

## Project status

**0.2.4 is a source preview for Windows x64.** The desktop interface is currently in Russian. Sony ARW and JPEG are the tested primary workflow; other camera formats and operating systems are not supported targets yet.

Automatic results need a photographer's review. Automatic crop application is off by default. PSD files can be used as flattened RGB references, not edited as layered documents. See [limitations](LIMITATIONS.md) and [validation](docs/VALIDATION.md).

A public Windows installer is pending clean-machine acceptance and completion of the bundled dependency redistribution checklist. Build from source below or download a source preview from [GitHub Releases](https://github.com/ANTIANT1/OpenPhoto/releases). Installer progress is tracked in the [roadmap](docs/ROADMAP.md).

## Getting started

You need **Windows x64, Python 3.12, [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js 22, and Git**. Preparing the full environment downloads several GB of dependencies, engines, and model weights. NVIDIA acceleration is available with a compatible driver; CPU processing is supported. Hardware minimums are still being measured.

Run these commands in PowerShell:

```powershell
git clone https://github.com/ANTIANT1/OpenPhoto.git
cd OpenPhoto
uv sync --frozen --extra desktop --extra ml --extra dev
.venv\Scripts\python scripts\install_engines.py
.venv\Scripts\python scripts\install_models.py
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.venv\Scripts\python -m openphoto
```

The desktop window uses Microsoft WebView2. If its runtime is missing, install it from [Microsoft](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) before launching the source build.

1. Add a shoot using **«Новая съёмка»**. Choose a folder or individual ARW/JPEG files.
2. Select **«Обработать съёмку»** for the automatic workflow, or **«Обрабатывать вручную»** to edit yourself.
3. Review the selection, color, retouching, and crop. Export to a separate folder.

The [user guide](docs/USER-GUIDE.md) explains controls, references, export, and recovery. Developers can run the [core checks without downloading ML models](docs/DEVELOPMENT.md).

## Contribute

Useful contributions include reproducible bug reports, camera compatibility evidence, improvements to the editing workflow, documentation, and tests. Start with [CONTRIBUTING](CONTRIBUTING.md) and [the architecture](docs/ARCHITECTURE.md).

- [Report a bug or propose a feature](https://github.com/ANTIANT1/OpenPhoto/issues/new/choose).
- [Report a security issue privately](https://github.com/ANTIANT1/OpenPhoto/security/advisories/new).
- Read the [release checklist](docs/RELEASING.md) before distributing binaries.

## License

OpenPhoto is licensed under [GPL-3.0-or-later](LICENSE). Engines, libraries, and model weights retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md). Your photographs, imported references, and editing decisions remain your data.
