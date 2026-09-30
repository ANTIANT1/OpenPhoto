"""Install official portable engines into the workspace and verify pinned archives."""
from pathlib import Path
import hashlib
import json
import zipfile

import httpx

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    "rawtherapee": {
        "version": "5.13", "archive": "rawtherapee-5.13.zip",
        "url": "https://github.com/RawTherapee/RawTherapee/releases/download/5.13/RawTherapee_5.13_win64_x86_64_release.zip",
        "sha256": "ba29d23f3f12097c925bdab6d80e831a84ed3a88a81ce94606e4dcc796fa87ee", "license": "GPL-3.0",
        "executable": "rawtherapee-cli.exe",
    },
    "exiftool": {
        "version": "13.59", "archive": "exiftool-13.59_64.zip",
        "url": "https://sourceforge.net/projects/exiftool/files/exiftool-13.59_64.zip/download",
        "sha256": "44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec", "license": "Artistic-1.0-Perl OR GPL-1.0-or-later",
        "executable": "exiftool.exe",
    },
}


def install():
    for name, asset in ASSETS.items():
        target = ROOT / "tools" / "vendor" / name
        target.mkdir(parents=True, exist_ok=True)
        archive = ROOT / ".cache" / asset["archive"]
        archive.parent.mkdir(exist_ok=True)
        if not archive.exists():
            with httpx.stream("GET", asset["url"], follow_redirects=True, timeout=120) as response:
                response.raise_for_status()
                with archive.open("wb") as stream:
                    for block in response.iter_bytes(1024 * 1024):
                        stream.write(block)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != asset["sha256"]:
                raise RuntimeError(f"Archive checksum mismatch: {archive}")
        if not list(target.rglob(asset["executable"])):
            with zipfile.ZipFile(archive) as zipped:
                for member in zipped.infolist():
                    if not (target / member.filename).resolve().is_relative_to(target.resolve()):
                        raise ValueError("Unsafe archive path")
                zipped.extractall(target)
            if name == "exiftool":
                source = next(target.rglob("exiftool(-k).exe"))
                source.rename(source.with_name("exiftool.exe"))
        expected = set()
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                if member.is_dir():
                    continue
                path = target / member.filename
                if name == "exiftool" and path.name == "exiftool(-k).exe":
                    path = path.with_name("exiftool.exe")
                if not path.resolve().is_relative_to(target.resolve()) or path.is_symlink():
                    raise ValueError("Engine file escapes its installation")
                expected.add(path.resolve())
                if not path.is_file():
                    raise RuntimeError(f"Engine file missing: {path.name}")
                with zipped.open(member) as source, path.open("rb") as installed:
                    if hashlib.file_digest(source, "sha256").digest() != hashlib.file_digest(installed, "sha256").digest():
                        raise RuntimeError(f"Engine file changed: {path.name}; restore it from the pinned archive")
        if any(p.resolve() not in expected for p in target.rglob("*") if p.is_file()):
            raise RuntimeError(f"Unexpected files in bundled {name}; inspect before packaging")
        print(f"Ready: {name} {asset['version']}", flush=True)
    (ROOT / "tools" / "engines.lock.json").write_text(json.dumps(ASSETS, indent=2), encoding="utf-8")


if __name__ == "__main__":
    install()
