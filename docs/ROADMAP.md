# Roadmap

The first public milestone is a useful, reviewable Windows source preview. Dates are not promised; milestones have observable completion criteria. Code that exists and product quality that needs evidence are tracked separately.

## Source preview

- [x] Import, cull, edit, retouch, and export Sony ARW/JPEG locally.
- [x] Preserve original files, recipe history, drafts, and resumable jobs.
- [x] Prepare source under GPL-3.0-or-later with locked dependencies and model hashes.
- [x] Document setup, architecture, limitations, contribution rules, and security reporting.
- [ ] Confirm the published commit passes GitHub source checks.

## Windows preview

- [ ] Complete the [redistribution checklist](REDISTRIBUTION.md) for the exact bundled binaries.
- [ ] Install on clean Windows without Python, Node.js, or an existing WebView2 runtime.
- [ ] Run the full CPU workflow offline; verify GPU processing separately.
- [ ] Verify saving on native window close, reopening, project switching, upgrades, and uninstall data preservation.
- [ ] Publish measured disk/RAM requirements and supported Windows versions.
- [ ] Decide on code signing; disclose signature status and publish checksums.

Completion means a new user can install and complete a shoot workflow without relying on the developer's machine. It does not establish universal AI quality.

## Stable photo workflow

- [ ] Evaluate selection, skin masks, reference color, and crop proposals on multiple independent shoots.
- [ ] Measure keeper recall, crop acceptance, and working time against a manual baseline.
- [ ] Test 300 and then 1000 full-resolution RAW files, recording memory, disk use, pauses, and crash recovery.
- [ ] Improve navigation latency by profiling ready frames and first RAW renders separately.
- [ ] Verify update and catalog recovery compatibility across released versions.

Earlier goals of 95% keeper recall, 90% crop acceptance, and 30% time savings are targets, not achieved product claims.

## English interface

- [ ] Extract hardcoded frontend strings into `en` and `ru` message catalogs.
- [ ] Give backend errors stable codes and translate user-visible messages consistently.
- [ ] Add language selection and preserve the preference across launches.
- [ ] Run editor, dialogs, shortcuts, and layout checks in both languages.

Repository documentation is English; translating documentation does not translate the application. Localization can be delivered independently of image-processing changes.

## Later candidates

Keyboard accessibility, a lighter CPU package, broader camera compatibility, and incremental separation of large API/pipeline modules. Standalone composition analysis needs further work. Cloud services, social-board imports, and other operating systems are outside the first-release scope.

Propose a use case through [Issues](https://github.com/ANTIANT1/OpenPhoto/issues/new/choose). Scope and priority are maintained by [@ANTIANT1](https://github.com/ANTIANT1).
