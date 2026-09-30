"""Explicit, resumable preparation; inference itself is always offline."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import httpx


def install(directory):
    directory.mkdir(parents=True, exist_ok=True)
    lock = Path(__file__).resolve().parents[1] / 'src/openphoto/resources/models.lock.json'
    pinned = json.loads(lock.read_text(encoding='utf-8'))
    assets = {name: (entry['url'], entry['license'], entry['sha256']) for name, entry in pinned.items()}
    manifest = {}
    for name, (url, license_name, expected) in assets.items():
        target = directory / name
        if not target.exists():
            partial = target.with_suffix(target.suffix + ".partial")
            print(f"Downloading {name}", flush=True)
            with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
                response.raise_for_status()
                with partial.open("wb") as stream:
                    for chunk in response.iter_bytes(1024 * 1024):
                        stream.write(chunk)
            with partial.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if expected and digest != expected:
                raise RuntimeError(f"Checksum mismatch for {name}")
            partial.replace(target)
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if expected and expected != digest:
            raise RuntimeError(f"Installed checksum mismatch: {name}")
        manifest[name] = {"url": url, "sha256": digest, "license": license_name, "bytes": target.stat().st_size}
        print(f"Ready: {name}", flush=True)
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path("models"))
    install(parser.parse_args().directory)
