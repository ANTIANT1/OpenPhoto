# Release checklist

The first milestone is a source preview. A binary release requires additional evidence. Use one accepted commit and version throughout the release; do not reuse QA results from a different executable without explicitly establishing what remained unchanged.

## Source preview

1. Update README, changelog, limitations, and roadmap. Keep experimental features explicit.
2. Run [development checks](DEVELOPMENT.md), including Python, frontend, browser, dependency, source-manifest, and secret checks.
3. Review Git history and the complete source inventory. Exclude photos, catalogs, model weights, private logs, and development environments.
4. Confirm GitHub CI is green on the commit being tagged.
5. Create a fresh source staging directory with `scripts/stage_release.py`; verify it with `scripts/verify_source.py` and scan it with `scripts/scan_secrets.py`.
6. Archive that directory, publish its SHA-256, and create a GitHub pre-release. State clearly when a release contains source only. Link setup instructions, known limitations, and the private security-reporting channel.

The archive's `SOURCE-SHA256.txt` describes its files; do not commit a stale generated manifest into the repository.

## Windows package

- [ ] Complete [REDISTRIBUTION](REDISTRIBUTION.md), preserving vendor notices and providing required corresponding source.
- [ ] Build from the accepted commit using `scripts/build_windows.ps1`; pass an Inno compiler to produce an installer.
- [ ] Compare bundled sources, compiled modules, UI, models, and installed files with that build.
- [ ] Test on a clean Windows VM without Python, Node, or an existing WebView2 runtime. Disable network after obtaining the complete installer.
- [ ] Complete import → CPU analysis → manual edit → JPEG/TIFF export → close → reopen. Verify original hashes and saved edits.
- [ ] Check native close with unsaved edits, switching projects, repeated launch, pause/resume, interrupted jobs, and recovery after a crash.
- [ ] Test upgrade from the previous release and uninstall without removing user projects or photographs.
- [ ] Check GPU operation separately and record hardware, driver, memory, and storage evidence.
- [ ] Record signature status, required free disk space, and supported Windows versions. Publish checksums for every EXE/BIN asset and explain that all parts belong in one folder.
- [ ] Publish only sanitized evidence. Never attach private source photos or diagnostic sessions.

## Stable release

Additionally accept a representative photographic benchmark, whole-shoot throughput, 300/1000 RAW stress tests, resource cleanup, and compatibility of recipes/catalog recovery. Measure user time and quality against an agreed baseline. Do not promote targets into claims without evidence.
