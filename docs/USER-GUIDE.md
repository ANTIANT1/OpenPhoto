# User guide

The interface is currently in Russian. This guide includes the button labels you will see. For source installation, start with [README](../README.md).

## Import and review

Choose **«Новая съёмка»** and select a folder or individual ARW/JPEG files. The native folder picker displays folders, not image files; images appear after import. Matching RAW+JPEG files share a catalog card. Originals stay where they are.

Use **«Обработать съёмку»** to analyze, suggest a selection, apply the selected reference style and gentle retouching, and prepare previews. **«Настроить»** controls style, scope, retouching, and optional JPEG export. Wait for import to finish before starting. Results still need review.

Use **«Обрабатывать вручную»** or open a card to edit manually. Manual recipe sections are preserved by automatic work. Resolve an unsaved draft before retrying a workflow stage that reports it.

The first-run guide explains import, automatic processing, navigation, and removal. Dismissal is saved in the project. Reopen it from **«Горячие клавиши» → «Пройти короткое обучение»**.

Without a reference profile, automatic processing keeps the original color and exposure. Gentle retouching acts on detected skin, so a photo without skin may look unchanged. Follow the current stage and prepared-preview count in **«Прогресс и результаты»**. AI limitations are reported per workflow and under the photo's **«Анализ»** tab. Preview preparation and JPEG export are separate operations unless automatic export is explicitly enabled.

| Shortcut | Action |
|---|---|
| P / X | Keep / reject |
| 1–5 | Assign a rating |
| Ctrl+A in the catalog | Select the entire current filter, across pages |
| Delete in the catalog | Remove cards without deleting originals |
| Ctrl+Z in the catalog | Undo the latest catalog action |
| Ctrl+mouse wheel or + / − in the editor | Zoom around the cursor / viewport center |
| Ctrl+0 / Ctrl+1 | Fit to window / actual pixels, including small photos |
| Drag or H | Pan / toggle the hand tool |
| Space+drag or middle-button drag | Pan while using crop or retouch tools |
| B or a short Space tap | Before / after |
| Ctrl+Enter | Apply manual changes and prepare a new preview |

Text fields keep their normal keyboard behavior. Removed cards can be restored from **«Удалённые»**. Use **«По окну»** to fit an image. Crop handles resize the frame; drag inside it to move the crop.

The trash button beside a shoot removes it from the sidebar and moves its cards to **«Удалённые»**, without deleting source files or editing history. Restore a card or explicitly re-import its source to reveal the shoot again. Re-import restores the existing card and reports how many photos were added, restored, or already present; it does not create duplicates. A shoot with pending work must finish or have its jobs cancelled before removal. An empty shoot can also be removed.

## References and edits

Add reference files or folders under **«Референсы и стили»**. Use separate profiles for distinct lighting or looks. PSD references need a saved merged RGB image and an ICC profile; Photoshop layers are not edited.

Pinterest boards cannot be connected yet. Use locally saved reference images that you are entitled to use. Reference color matching creates style proposals; personal culling learns from your comparisons and ratings. Neither feature trains a new generative image model from a board.

Basic controls include exposure, temperature, RAW white-balance tint, contrast, saturation, color tint, shadows, highlights, black point, crop, and retouching. Enter values directly or move a slider; ↺ resets that parameter. Apply changes to update the rendered photo and its RGB preview histogram. The histogram describes the displayed preview, not raw sensor data. Curves, HSL color ranges, and adjustment layers are not available yet.

Review color, skin boundaries, and crop before applying settings to a series. Retouching starts at zero in manual recipes and at 0.15 in the automatic workflow. Automatic crop application is disabled until validated in settings. Compare the linked camera JPEG when available.

Edits are saved before navigation and export. Previous versions remain in history. A change to processing compatibility creates a new revision rather than silently replacing an old result.

## Export and recovery

Choose **«Экспорт»** and a separate destination. JPEG, TIFF, XMP ratings, and OpenPhoto recipes have different purposes; full processing is not transferable through rating XMP alone. Name collisions receive suffixes instead of overwriting output.

Under **«Обработка и экспорт»**, inspect results, retry failed work, or choose **«Открыть папку результата»**. Paused jobs retain checkpoints. Jobs interrupted by a crash are available for explicit continuation on the next launch.

**«Проекты и библиотека»** creates and opens projects and offers catalog backups. Restore creates an independent project copy. Back up originals and the project folder separately; a catalog backup is not a backup of all photographs. See [limitations](../LIMITATIONS.md).
