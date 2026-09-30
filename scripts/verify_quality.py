"""Full-resolution portrait invariants. Run sequentially after the API acceptance."""

import argparse
import json
import os
import time
from pathlib import Path

from openphoto.processes import configure_threads

configure_threads()


def run(project, directory):
    os.environ["MPLCONFIGDIR"] = str(directory / "cache" / "matplotlib")
    import cv2
    import numpy as np
    import psutil
    from PIL import Image
    from openphoto.analysis import analyze
    from openphoto.database import AnalysisResult, PhotoAsset, loads
    from openphoto.imaging import RawDeveloper, apply_recipe, resize, to_srgb, write_image
    from openphoto.schemas import Color, Crop, Retouch
    from openphoto.service import Pipeline

    cv2.setNumThreads(4)
    directory.mkdir(parents=True, exist_ok=False)
    pipeline = Pipeline(project, lane="render")
    report = {"checks": {}, "ok": False}
    try:
        candidates = []
        with pipeline.catalog.session() as session:
            for photo, row in session.query(PhotoAsset, AnalysisResult).join(
                AnalysisResult, PhotoAsset.id == AnalysisResult.photo_id
            ):
                if Path(photo.relative_path).suffix.lower() != ".arw":
                    continue
                for face in loads(row.data, {}).get("faces", []):
                    x1, y1, x2, y2 = face["box"]
                    candidates.append(((x2 - x1) * (y2 - y1), photo.id))
        if not candidates:
            raise RuntimeError("No detected RAW portrait available for this check")
        _, identifier = max(candidates)
        photo, path, recipe, _ = pipeline.snapshot(identifier)
        recipe.color = Color()
        recipe.retouch = Retouch()
        recipe.crop = Crop()
        recipe.rotation = 0
        developer = RawDeveloper(pipeline.catalog.settings()["rawtherapee"], directory / "cache")
        started = time.perf_counter()
        linear = developer.develop(path, photo.fingerprint, recipe)
        aligned = analyze(
            np.uint8(to_srgb(resize(linear, 2048)) * 255 + 0.5), pipeline.models, source="developed"
        )
        assert aligned["faces"] and not pipeline.models.errors
        base, disabled = apply_recipe(linear, recipe, aligned)
        assert np.array_equal(base, linear) and not disabled.any()
        report["checks"]["disabled_retouch_identity"] = True
        recipe.retouch = Retouch(
            strength=0.25, color_evenness=0.15, body_strength=0.2, body_color_evenness=0.1
        )
        changed, mask = apply_recipe(linear, recipe, aligned)
        assert (mask > 0).sum() > 100
        outside = mask == 0
        assert np.array_equal(changed[outside], base[outside])
        report["checks"]["outside_mask_identity"] = True
        report["checks"]["changed_area_percent"] = round(float((mask > 0).mean() * 100), 3)
        report["checks"]["full_shape"] = list(linear.shape)
        face = max(aligned["faces"], key=lambda f: (f["box"][2] - f["box"][0]) * (f["box"][3] - f["box"][1]))
        cx = int((face["box"][0] + face["box"][2]) / 2 * linear.shape[1])
        cy = int((face["box"][1] + face["box"][3]) / 2 * linear.shape[0])
        left = max(0, min(linear.shape[1] - 1024, cx - 512))
        top = max(0, min(linear.shape[0] - 1024, cy - 512))
        patch = np.s_[top : top + 1024, left : left + 1024]
        write_image(directory / "face-before.jpg", base[patch])
        write_image(directory / "face-after.jpg", changed[patch])
        Image.fromarray(np.uint8(np.clip(mask[patch], 0, 1) * 255)).save(directory / "face-mask.png")
        write_image(directory / "result-2048.jpg", resize(changed, 2048))
        report["retouch_seconds"] = round(time.perf_counter() - started, 2)
        recipe.retouch = Retouch()
        preview = developer.develop(path, photo.fingerprint, recipe, 2048)
        export_small = resize(base, 2048)
        assert preview.shape == export_small.shape
        error = np.abs(to_srgb(preview) - to_srgb(export_small))
        report["checks"]["preview_export_srgb_rmse"] = round(float(np.sqrt(np.mean(error**2))), 6)
        report["checks"]["preview_export_srgb_p95"] = round(float(np.percentile(error, 95)), 6)
        assert report["checks"]["preview_export_srgb_rmse"] < 0.04, "Preview and export diverge"
        report["photo"] = photo.name
        memory = psutil.Process().memory_info()
        report["peak_rss_mb"] = round(getattr(memory, "peak_wset", memory.rss) / 1024**2, 1)
        report["ok"] = True
        print(json.dumps(report, ensure_ascii=False), flush=True)
    except BaseException as error:
        report["error"] = str(error)
        raise
    finally:
        pipeline.catalog.engine.dispose()
        (directory / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    run(args.project.resolve(), args.directory.resolve())
