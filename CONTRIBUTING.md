# Contributing to OpenPhoto

OpenPhoto is maintained by [@ANTIANT1](https://github.com/ANTIANT1). The current focus is a reliable local Windows workflow for Sony ARW/JPEG portrait shoots. See the [roadmap](docs/ROADMAP.md) before starting a large feature.

## Start here

Use the [development guide](docs/DEVELOPMENT.md) to install the small core test environment or the full application. Read the [architecture](docs/ARCHITECTURE.md) for processing, data ownership, and versioning rules.

Bug reports and contributions are welcome in English or Russian. Describe what you did, what you expected, what happened, and the application version. Use synthetic examples where possible. Do not attach private photos, catalogs, access tokens, or unredacted logs. Report vulnerabilities through the [private security channel](SECURITY.md).

## Pull requests

1. Work in a branch with a separate test project.
2. Keep the change focused. Explain the user-visible problem and resulting behavior.
3. Run the checks relevant to your change and record the result in the PR.
4. Add a regression for changes to saving, undo, exports, migrations, or process cleanup. Documentation-only corrections do not need new tests.
5. Update user documentation when behavior changes. Do not present a model recommendation as a verified photographic result.

Changes to dependencies require lock-file updates, license review, and vulnerability review. Changes to the catalog require a migration and a recovery check. Preserve recipe compatibility: a new algorithm must not silently change old edits.

## Project boundaries

- Preserve original files. Exports and temporary files must have explicit ownership.
- Keep processing local. Do not add telemetry, runtime model downloads, or cloud calls to the photo pipeline.
- Use the shared preview/export geometry and color path.
- Run heavy acceptance checks sequentially. `scripts/run_owned.py` cleans up the process tree created by a check.
- Keep photographs, model weights, catalogs, local reports, and build outputs out of Git. Generate test images in temporary directories.

The files at the repository root and in `docs/` are the canonical public documentation. There is no separate mirrored copy to edit. Before distributing a binary, complete [RELEASING](docs/RELEASING.md) and [REDISTRIBUTION](docs/REDISTRIBUTION.md).

Contributions are made under GPL-3.0-or-later. Preserve third-party attribution. Treat contributors respectfully, discuss the work rather than the person, and do not post anyone's private information. The maintainer may moderate abusive or off-topic participation.
