# Changelog

## Unreleased

No changes yet.

## 0.2.5 — tester workflow fixes (3 October 2026)

- Remove shoots directly from the sidebar, including shoots with zero active photos. Cards move to Removed; original files, ratings, recipes, and history remain intact.
- Restore a removed card on explicit re-import instead of silently treating it as a duplicate. Re-importing a moved source reconnects the existing card.
- Add a four-step first-run guide, a permanent Removed navigation entry, recovery hints, and reusable shortcut help.
- Pan photos by dragging, with the hand tool, or with Space+drag while cropping/retouching. Add +/- zoom, Ctrl+0 fit, Ctrl+1 actual size, B before/after, and Ctrl+Enter apply.
- Add numeric adjustment entry, per-parameter resets, black point, RAW white-balance tint, and a preview RGB histogram.
- Refresh a clean editor to the revision produced by automatic work while preserving unsaved manual edits. Scope workflow status to the displayed photos and show actual preview counts and unavailable AI components.
- Clarify that automatic processing without a color reference preserves the original color and exposure; reference matching and personal selection learning are separate features. Pinterest board import is not implemented.

## 0.2.4 — source preview (1 October 2026)

- Prepare the public repository: English documentation, Russian quick start, contributor guidance, private vulnerability reporting, and a staged roadmap.
- Make browser dependencies and the secret scanner reproducible; extend source CI with browser regressions, dependency auditing, and source archive checks.
- Consolidate public documentation into the repository root and `docs/`.
- Verify the first public commit on a fresh GitHub Windows runner and update pinned CI actions for Node.js 24.
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
