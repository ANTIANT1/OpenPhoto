"""Install the pinned Windows scanner after verifying the upstream archive."""
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    lock = json.loads((ROOT / "tools/gitleaks.lock.json").read_text())
    archive = ROOT / ".cache" / ("gitleaks-" + lock["version"] + ".zip")
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        with urllib.request.urlopen(lock["url"], timeout=120) as response:
            contents = response.read()
        if hashlib.sha256(contents).hexdigest() != lock["archive_sha256"]:
            raise ValueError("Gitleaks download checksum mismatch")
        archive.write_bytes(contents)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != lock["archive_sha256"]:
        raise ValueError("Cached Gitleaks checksum mismatch")
    destination = ROOT / "tools/security"
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        for name in ("gitleaks.exe", "LICENSE"):
            contents = zipped.read(name)
            target = destination / name
            if not target.exists() or target.read_bytes() != contents:
                target.write_bytes(contents)
    print("Ready: Gitleaks " + lock["version"])
    return destination / "gitleaks.exe"


if __name__ == "__main__":
    prepare()
