# Binary redistribution review

**Status: incomplete for a public Windows installer.** The source preview is available for development; existing local binaries have not completed this distribution review. Do not mistake the license inventory for proof that every redistribution obligation is fulfilled.

| Component | Existing evidence | Required before a binary release |
|---|---|---|
| OpenPhoto | GPL-3.0-or-later, source and build scripts | Exact release commit, corresponding source archive, notices |
| RawTherapee 5.13 | Pinned official binary archive, GPL notice, source tag link | Verify corresponding source/build information for the binary; provide clear source access with the release |
| rawpy / LibRaw | Lock entry and upstream license files | Record exact bundled LibRaw version, selected license terms, and corresponding source obligations |
| ExifTool | Pinned official Windows archive and license | Preserve vendor files and verify distribution terms |
| PyTorch / CUDA libraries | Locked wheels and collected notices | Identify redistributed NVIDIA libraries and confirm their applicable redistribution terms |
| CLIP / LAION / MediaPipe models | URLs, hashes, and declared licenses in the model manifest | Verify license coverage of the exact weights and preserve required notices |
| Microsoft WebView2 | Signed upstream installer, locked URL/hash | Confirm current runtime redistribution terms and required notices |
| Remaining Python/native/JS components | Lock files and license inventory | Review exact binary inventory, source obligations, exceptions, and attribution |

For each release record the component version, binary hash, license, source location where required, local modifications, build instructions, and how the obligation is fulfilled. Review the entire inventory, not only this abbreviated table.

GPL-covered binaries require corresponding source through an applicable distribution method. Source may be hosted separately when the license conditions are met; users need clear directions adjacent to the binaries. See [GPLv3 sections 1 and 6](https://opensource.org/license/gpl-3.0) and [third-party notices](../THIRD_PARTY_NOTICES.md).

The maintainer owns completion of this checklist. Unresolved entries block the installer release; they do not imply that all listed components are incompatible or improperly licensed.
