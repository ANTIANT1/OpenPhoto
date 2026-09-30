# Security and privacy

## Report a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/ANTIANT1/OpenPhoto/security/advisories/new). Reports are received by the repository maintainer, [@ANTIANT1](https://github.com/ANTIANT1). Do not open a public issue with exploit details, session tokens, private catalogs, or photographs.

Include the version or commit, affected workflow, expected impact, and a minimal reproduction using synthetic data. Describe any sensitive attachment before sending it. This is a volunteer preview project; no response-time SLA is promised.

Security fixes target the latest source preview and `main`. Older development snapshots are not maintained as separate security branches. Report ordinary bugs through [Issues](https://github.com/ANTIANT1/OpenPhoto/issues/new/choose).

## Security model

The API binds to loopback and validates Host, Origin, and a per-launch token. Mutating requests require the token header. Image and event requests may use the session cookie. Access logging is disabled to avoid recording launch tokens.

Photo processing uses local engines and model files. Preparing dependencies requires network access; the pipeline does not upload photographs or fetch models during processing. Microsoft WebView2 is a separate system component with its own update behavior. Offline processing does not imply that every component of Windows is network-isolated.

Model SHA-256 values are pinned inside the application. A user-writable model directory cannot replace that trust manifest. Project locks, export ownership, and revision checks protect against concurrent modification; they do not protect against a malicious program running as the same Windows user.

## Dependency decisions

MediaPipe 0.10.21 is pinned because telemetry was observed in newer upstream binaries; see the [upstream report](https://github.com/google-ai-edge/mediapipe/issues/6291). Do not upgrade it independently of the numerical stack and privacy checks.

The bundled protobuf 4.25.9+openphoto.1 wheel contains a reproducible JSON recursion backport. Its native extension is unchanged. The patch covers the nested Any route and Struct/Value/ListValue route described in [the upstream fix](https://github.com/protocolbuffers/protobuf/commit/d2b0016) and [follow-up report](https://github.com/protocolbuffers/protobuf/issues/26432). Tests validate behavior and the installed module hash.

Dependency scanning explicitly normalizes local versions and records the narrowly reviewed protobuf exception. A scanner's inability to identify a local package is not a clean bill of health. See [dependency review](docs/DEPENDENCY-REVIEW.md).

## Release hygiene

Source archives use an explicit allowlist. Secret checks run locally with redacted results; photographs are not uploaded to a scanner. Never publish a working project, diagnostic session file, or raw private QA report. Review source archive contents and the history being pushed before publishing.
