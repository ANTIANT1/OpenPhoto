# Components and redistribution

OpenPhoto source: GPL-3.0-or-later; see LICENSE. Original photographs, imported references and user decisions remain the user's data and are not licensed by this project.

| Component | Pinned version/source | License |
|---|---|---|
| RawTherapee | [5.13 source](https://github.com/RawTherapee/RawTherapee/tree/5.13), official Windows portable release | GPL-3.0; vendor distribution includes its notices |
| ExifTool | [13.59](https://exiftool.org/), official Windows archive | Perl Artistic License / GPL; preserve exiftool_files |
| OpenAI CLIP ViT-B/32 | [OpenAI CLIP](https://github.com/openai/CLIP), checkpoint hash in models.lock.json | MIT |
| LAION aesthetic linear B/32 | [LAION-AI/aesthetic-predictor](https://github.com/LAION-AI/aesthetic-predictor) | MIT |
| MediaPipe face, pose and selfie models | Google MediaPipe storage, version 1; URLs and SHA-256 in models.lock.json | Apache-2.0; [upstream license](https://github.com/google-ai-edge/mediapipe/blob/master/LICENSE) |
| PyTorch / torchvision | 2.13.0 / 0.28.0, CUDA 12.6 wheels | BSD-3-Clause; NVIDIA libraries retain their own redistribution terms |
| Protocol Buffers | 4.25.9+openphoto.1, reproducible local JSON recursion backport in tools/wheels | BSD-3-Clause; original wheel license retained |
| rawpy / LibRaw | uv.lock | MIT / LGPL-2.1-or-later or CDDL-1.0 |
| NumPy, SciPy, scikit-learn | uv.lock | BSD-3-Clause |
| OpenCV | uv.lock | Apache-2.0 |
| imagecodecs / LittleCMS | uv.lock | BSD-3-Clause / MIT; individual codec licenses included upstream |
| psd-tools | 1.19.0; saved merged RGB references, no layer recompositing | MIT |
| Pillow / tifffile | uv.lock | HPND / BSD-3-Clause |
| FastAPI, SQLAlchemy, Alembic, pywebview, React, Vite | uv.lock / frontend/package-lock.json | MIT |
| PyInstaller | uv.lock | GPL-2.0-or-later with bootloader exception |
| Python | 3.12 | PSF-2.0 |

The build includes installed package license files and dependency metadata. The source distribution includes the lock files and build scripts. If distributing binary releases externally, provide the corresponding source of copyleft components with the release, preserve all vendor notices and comply with NVIDIA's redistribution terms. Do not relicense vendor weights or libraries as OpenPhoto code.

QA-only images are not included in the application: the Sony ILCE-7M3 example from raw.pixls.us is CC0; Google's MediaPipe portrait.jpg is a public test fixture. They are not the user's photographs and cannot establish portrait/fashion quality acceptance.

**Offline dependency choice:** the Python runtime is pinned to MediaPipe 0.10.21 and a compatible NumPy 1.26 stack. Newer MediaPipe PyPI binaries include Clearcut telemetry without an opt-out. This was observed during testing of 0.10.35 and confirmed by the [upstream issue and maintainer response](https://github.com/google-ai-edge/mediapipe/issues/6291). Do not upgrade this dependency automatically; use a reviewed source build or repeat the network audit. No current telemetry-bearing binary is intended for the release.

RawTherapee integration follows the [CLI documentation](https://rawpedia.rawtherapee.com/Command-Line_Options), [profile format](https://rawpedia.rawtherapee.com/Sidecar_Files_-_Processing_Profiles), and [isolated settings directories](https://rawpedia.rawtherapee.com/File_paths).

Microsoft WebView2: the installer includes the signed x64 Evergreen Standalone Installer from Microsoft, with source, resolved URL and SHA-256 recorded in tools/webview2.lock.json. It is installed only if absent. It remains a Microsoft component under its own runtime redistribution terms. See [Microsoft deployment documentation](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution). The shared Evergreen runtime can update through the system; OpenPhoto photo processing does not depend on those updates.
