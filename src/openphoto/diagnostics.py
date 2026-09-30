"""Reproducible diagnostics for both the source and frozen distributions."""
from pathlib import Path
import json
import os
import sys
import traceback


def self_test(output: Path, root: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    os.environ["MPLCONFIGDIR"] = str(output.resolve().parent / "cache" / "matplotlib")
    report = {"frozen": bool(getattr(sys, "frozen", False)), "python": sys.version, "checks": {}}
    try:
        import numpy as np
        import tifffile
        import rawpy
        import webview
        from .analysis import LocalModels
        from .imaging import icc_profile, convert, write_image, read_rgb
        from .database import Catalog
        import torch

        report['checks']['imports'] = bool(rawpy and webview)
        image = np.linspace(0, 1, 128*128*3, dtype=np.float32).reshape(128,128,3)
        linear = convert(image, icc_profile('srgb'))
        path = output.parent / 'diagnostic.tiff'
        write_image(path, linear, 'tiff', 'prophoto')
        report['checks']['tiff16'] = bool(tifffile.imread(path).dtype == np.uint16)
        report['checks']['color_roundtrip'] = float(np.max(np.abs(linear-read_rgb(path)))) < .001
        catalog = Catalog(output.parent / 'diagnostic-catalog')
        catalog.initialize()
        catalog.engine.dispose()
        report['checks']['migrations'] = True
        models = LocalModels(root / 'models')
        embedding, aesthetic = models.embedding(np.uint8(image*255))
        models.landmarks(np.uint8(image*255))
        report['checks']['clip'] = bool(embedding and len(embedding)==512 and aesthetic is not None)
        report['checks']['landmarkers'] = all((models.face, models.pose, models.skin))
        report['device'] = models.device
        report['gpu'] = torch.cuda.get_device_name() if torch.cuda.is_available() else None
        report['errors'] = models.errors
        report['ok'] = all(report['checks'].values()) and not models.errors
    except Exception:
        report['ok'] = False
        report['exception'] = traceback.format_exc()
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if report['ok'] else 1
