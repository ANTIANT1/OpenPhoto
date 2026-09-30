# Dependency review

Review baseline: 30 September 2026, OpenPhoto 0.2.4. Advisory databases change; CI checks current results rather than relying on this dated snapshot.

## Local versions and the protobuf patch

The application pins PyTorch 2.13.0+cu126, torchvision 0.28.0+cu126, MediaPipe 0.10.21, and protobuf 4.25.9+openphoto.1. A standard installed-environment scan cannot identify the local version strings on PyPI. The release audit therefore normalizes only these explicitly reviewed suffixes and audits their upstream versions.

For protobuf 4.25.9, PYSEC-2026-1805 / GHSA-7gcm-g887-7qv7 / CVE-2026-0994 describe JSON recursion exhaustion. The local wheel patches nested Any handling and the additional Struct/Value/ListValue path. `scripts/prepare_protobuf.py` records the upstream wheel hash and deterministically produces the backport; `tools/wheels` contains the wheel and its manifest. The native binary is unchanged.

`scripts/audit_dependencies.py` accepts only that advisory for upstream protobuf 4.25.9, only after verifying the local wheel and patched module hashes. Tests additionally check nested message behavior. A new advisory, unexpected local version, unrecognized package, or modified wheel fails the check. The exception does not claim that every possible protobuf vulnerability is fixed.

Primary references: [upstream Any fix](https://github.com/protocolbuffers/protobuf/commit/d2b0016), [Struct/Value/ListValue follow-up](https://github.com/protocolbuffers/protobuf/issues/26432).

## Offline model stack

MediaPipe 0.10.21 is retained because newer binaries introduced telemetry observed in upstream testing. See [the upstream issue](https://github.com/google-ai-edge/mediapipe/issues/6291). Upgrading it requires compatibility and network-behavior review, not just a higher version number.

CLIP and LAION weights are fixed by hashes in `src/openphoto/resources/models.lock.json`. The application does not accept arbitrary user-supplied weights. Photos and reference images are not treated as model files.

## Review process

Audit all lock-file versions; do not silently skip local packages. Record each remaining advisory with affected operation, reachability, mitigation, and evidence. Review the protobuf exception whenever its package or patch changes. Keep the scanner pinned; update its version deliberately.

The earlier full-environment audit covered 92 installed entries: OpenPhoto and three local dependency versions required separate treatment. Normalized torch and torchvision had no returned advisories; protobuf returned duplicate entries for the same CVE. This is historical evidence, not an evergreen claim of zero vulnerabilities.

Dependency license inventory is in `licenses/` and [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md). It is separate from the binary [redistribution review](REDISTRIBUTION.md).
