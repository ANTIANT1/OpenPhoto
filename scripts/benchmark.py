"""Repeatable stress test; generated fixtures are explicitly not photographic quality evidence."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import psutil
from PIL import Image

from openphoto.api import resource_root
from openphoto.database import Catalog, PhotoAsset, ProcessingJob, loads
from openphoto.service import Pipeline, enqueue


def run(directory, count, analyze_count):
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "generated"
    source.mkdir(exist_ok=True)
    for i in range(count):
        path = source / f"Съёмка {i:04d}.jpg"
        if not path.exists():
            rng = np.random.default_rng(i)
            pixels = rng.integers(0, 255, (360, 540, 3), dtype=np.uint8)
            Image.fromarray(pixels).save(path, quality=80)
    catalog = Catalog(directory / "project")
    catalog.initialize()
    catalog.set_setting("models_directory", str(resource_root() / "models"))
    pipeline = Pipeline(catalog.directory)
    started = time.perf_counter()
    job = enqueue(catalog, "import", {"paths": [str(source)], "shoot_name": "Synthetic stress"})
    pipeline.run(job)
    report = {"fixture": "synthetic 540x360 JPEG; not an ARW/shoot quality benchmark", "count": count,
              "import_seconds": time.perf_counter()-started}
    with catalog.session() as s:
        ids = [p.id for p in s.query(PhotoAsset).order_by(PhotoAsset.name)]
        report["imported"] = len(ids)
        report["import_errors"] = loads(s.get(ProcessingJob, job).result).get("errors", [])
    progress = directory / "report.json"
    progress.write_text(json.dumps(report, indent=2), encoding="utf-8")
    rss = []
    connections = []
    start = time.perf_counter()
    for index, identifier in enumerate(ids[:analyze_count]):
        pipeline.analyze_photo(identifier, {})
        rss.append(psutil.Process().memory_info().rss)
        connections.extend([str(c.raddr) for c in psutil.Process().net_connections() if c.raddr])
        if index == 299:
            report['first_300_analysis_seconds'] = time.perf_counter()-start
        if index % 50 == 0:
            print(f"Analyzed {index+1}/{min(count,analyze_count)}", flush=True)
    report["analysis_seconds"] = time.perf_counter()-start
    report["analyzed"] = min(count, analyze_count)
    report["peak_rss_gb"] = max(rss, default=0)/1024**3
    report["rss_last100_growth_mb"] = (rss[-1]-rss[-100])/1024**2 if len(rss) >= 100 else None
    report["device"] = pipeline.models.device
    report["observed_network_connections"] = sorted(set(connections))
    if pipeline.models.device == "cuda":
        import torch
        report["gpu_peak_allocated_gb"] = torch.cuda.max_memory_allocated()/1024**3
        report["gpu_peak_reserved_gb"] = torch.cuda.max_memory_reserved()/1024**3
    progress.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path(".cache/benchmark"))
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--analyze", type=int, default=300)
    args = parser.parse_args()
    run(args.directory.resolve(), args.count, args.analyze)
