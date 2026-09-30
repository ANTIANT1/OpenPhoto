# Validation and evidence

OpenPhoto separates source correctness, binary installation, and photographic quality. A passed unit or browser test does not validate all three.

## First public source checks

The [first GitHub run](https://github.com/ANTIANT1/OpenPhoto/actions/runs/36783826858) passed on commit `73962a5` using a fresh hosted Windows runner:

| Check | Result |
|---|---|
| Python core suite and Ruff | 112 passed, one PyTorch-specific skip; no lint errors |
| React production build | Passed |
| Browser regressions in Microsoft Edge | 13 scenarios passed, no JavaScript errors |
| Source inventory and manifest | Passed |
| Source and complete Git history secret scans | Zero findings |
| Locked Python dependency audit | 93 versions checked; no unexpected findings; local protobuf backport verified |
| JavaScript dependency audit | Zero findings |

The core job deliberately does not install ML weights or test AI output quality. The protobuf advisory exception is tied to the reviewed wheel and patch hashes; see [dependency review](DEPENDENCY-REVIEW.md). Use the [current Actions results](https://github.com/ANTIANT1/OpenPhoto/actions/workflows/check.yml) for later commits.

## Baseline before public repository preparation

On 30 September 2026, the local 0.2.4 snapshot passed:

| Check | Result | Scope |
|---|---|---|
| Python tests with ML installed | 110 passed | Existing regression suite |
| Separate core environment | 109 passed, one PyTorch-specific skip | Same Windows host, cached dependencies; not a clean OS |
| Browser regressions | 13 scenarios, no JavaScript errors | Real React build, controlled API responses, synthetic photos |
| Source archive | 429 files matched its prepared source tree and manifest | The pre-publication archive, not a permanent file count |
| Gitleaks | No findings in that source archive | No Git history existed at that point |
| Portable application | Matching source/frontend and 22 compiled modules per EXE | Existing local binaries |

The published repository adds release-tool tests and CI. The [Actions page](https://github.com/ANTIANT1/OpenPhoto/actions/workflows/check.yml) is the source of current commit-specific results; this historical table is not a CI badge substitute. Raw local reports are withheld because they can contain personal paths and project data.

## Earlier installed-application evidence

The 29 September 0.2.4 check compared 6622 installed files with the local package. One actual Sony ARW+JPEG pair completed import, automatic processing, and full-resolution JPEG export without changing originals. Those observations were on the development computer.

Twelve transitions among four ready photos measured a median 694 ms from click to decoded frame. One RAW workflow measured 3.09 s import, 19.61 s processing, 20.84 s export, and 3598 MiB peak process-tree RAM. These small samples are not whole-shoot throughput or minimum hardware requirements. The native window check was interrupted, so normal closing of that installed run was not accepted.

## Not yet established

Clean-Windows installation without preinstalled WebView2; the complete latest native lifecycle; sustained 1000 full-resolution RAW processing; a representative photographic quality benchmark; keeper recall, crop acceptance, or editing-time savings across independent shoots. These remain explicit items in [ROADMAP](ROADMAP.md).

Before publishing a Windows build, record its hash, OS and hardware, workflow, input provenance, CPU/GPU mode, preservation checks, cleanup, and outcomes. Share sanitized summaries and synthetic evidence, not private catalogs or raw logs.
