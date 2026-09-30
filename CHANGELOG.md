# Changelog

## Unreleased

- Prepare the public repository: English documentation, Russian quick start, contributor guidance, private vulnerability reporting, and a staged roadmap.
- Make browser dependencies and the secret scanner reproducible; extend source CI with browser regressions, dependency auditing, and source archive checks.
- Consolidate public documentation into the repository root and `docs/`.

## 0.2.4 — source preview

- Add a resumable automatic shoot workflow: analysis and culling, reference color, gentle retouching, previews, and optional JPEG export.
- Preserve manual sections and unsaved drafts; retry failed stages without duplicating completed work.
- Resize crops from all four edges and corners, move the crop, zoom with Ctrl+wheel, and fit the image to the window.
- Reuse analysis when color, retouching, or cropping changes; recompute for new development and geometry.

## 0.2.3

- Select all filtered photos across catalog pages, including catalogs larger than 1000 cards.
- Remove photos from the catalog, restore them, and undo catalog decisions without deleting originals.
- Add individual file selection and explain the native Windows folder dialog.
- Reuse ready previews and request full resolution only for 1:1 viewing.

## 0.2.2

- Fix Windows cache lease cleanup when readers temporarily lock the lease file.
- Preserve images protected by a partially written lease; retry deferred cleanup.
- Isolate QA caches from application installation directories.

## 0.2.1

- Preserve highlight headroom in float32 intermediate TIFFs; keep final TIFF exports 16-bit.
- Improve highlight recovery and reference exposure matching.
- Preserve earlier recipe mathematics and require explicit processing-version migration.

## 0.2.0

- Add reliable draft saving, history, batch edits, comparison, project switching, catalog backups, and independent restoration.
- Improve RAW+JPEG pairing, import idempotency, job history, and export recovery.
- Support flattened RGB PSD references and protect edits during desktop close.

These versions describe local development milestones. They do not imply that corresponding public installers have been released or independently certified.
