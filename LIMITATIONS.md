# Preview limitations

OpenPhoto 0.2.4 is a Windows source preview. Passing software tests establishes engineering behavior, not photographic quality across all subjects and lighting.

- **Platform:** Windows x64, Python 3.12, and Node.js 22 for development. Linux, macOS, and Windows ARM are not validated targets. The application interface is currently in Russian.
- **Inputs:** Sony ARW and JPEG are the primary tested workflow. RAW support must be validated per camera and mode; do not assume every format supported by an underlying library is supported by OpenPhoto.
- **AI selection:** recommendations and review queues need a photographer's judgement. Originals are never deleted by selection.
- **Cropping:** face and pose detection can fail. Automatic crop application is off until the user explicitly validates it. Standalone symmetry, diagonal, and motion-direction analysis is not complete.
- **Retouching:** check hair, makeup, jewelry, clothing boundaries, and difficult poses. Manual recipes start at zero retouching. The automatic workflow defaults to a gentle strength of 0.15, which can be disabled before starting.
- **References:** color matching does not reproduce another photograph's lighting or every local Photoshop adjustment. PSD support is limited to a saved merged RGB 8/16-bit image with embedded ICC, up to 60 MP and 1 GB. Layers and effects are not recomposited.
- **Personalization:** requires explicit comparisons across multiple shoots and an independent holdout. A trained model is only promoted after comparison with the baseline and incumbent; improvement is not guaranteed.
- **Interoperability:** XMP carries supported ratings and labels. Color and retouching are delivered as rendered images; OpenPhoto recipes are application-specific.
- **Repeatability:** older recipes retain their processing version. Exact reproduction requires the compatible runtime, models, profiles, and original files.
- **Performance:** full-shoot quality, 1000 full-resolution RAW operation, hardware minimums, and clean-Windows installation remain release acceptance work. A synthetic catalog test is not a full RAW benchmark.
- **Backups:** catalog backups do not back up original photographs. Keep separate backups of source photos and the project folder, including references.

No published claim of 95% keeper recall, 90% crop acceptance, or 30% time savings has been established. See [validation](docs/VALIDATION.md) and [the roadmap](docs/ROADMAP.md).
