"""Create a reviewable source distribution from an explicit allowlist."""

import argparse
import hashlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LIMITATIONS.md",
    "CHANGELOG.md",
    ".gitleaks.toml",
    "tools/gitleaks.lock.json",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "uv.lock",
    ".gitignore",
    "Start-OpenPhoto.cmd",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/index.html",
    "frontend/vite.config.ts",
    "frontend/tsconfig.json",
    "tools/engines.lock.json",
    "tools/webview2.lock.json",
    ".gitattributes",
]
DIRECTORIES = ["src", "frontend/src", "tests", "packaging", "licenses", "tools/wheels", ".github"]
FILES += ["docs/" + name for name in (
    "ARCHITECTURE.md", "DEVELOPMENT.md", "ROADMAP.md", "RELEASING.md",
    "REDISTRIBUTION.md", "VALIDATION.md", "DEPENDENCY-REVIEW.md",
    "USER-GUIDE.md", "README.ru.md", "assets/mark.svg",
)]
FILES += [
    "scripts/" + name
    for name in (
        "build_windows.ps1",
        "collect_notices.py",
        "create_icon.py",
        "install_engines.py",
        "install_models.py",
        "prepare_protobuf.py",
        "prepare_webview2.py",
        "stage_release.py",
        "verify_packaged.py",
        "verify_personal.py",
        "resume_acceptance.py",
        "verify_quality.py",
        "scan_secrets.py",
        "prepare_security.py",
        "audit_dependencies.py",
        "verify_source.py",
        "run_owned.py",
        "verify_ui.cjs",
        "verify_editor_races.py",
        "verify_editor_races.cjs",
        "benchmark.py",
    )
]


def stage(destination):
    destination = destination.resolve()
    if not destination.is_relative_to(ROOT / ".cache"):
        raise ValueError("Release staging must be inside the workspace .cache directory")
    destination.mkdir(parents=True, exist_ok=False)
    paths = [ROOT / name for name in FILES]
    missing = [p.relative_to(ROOT).as_posix() for p in paths if not p.is_file()]
    if missing:
        raise ValueError("Required release files are missing: " + ", ".join(missing))
    for name in DIRECTORIES:
        paths.extend(p for p in (ROOT / name).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    for source in paths:
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
            raise ValueError("Release sources must belong to the workspace")
        if source.name.lower().startswith(".env") or source.name.lower() in {
            "credentials.json", "credentials", "id_rsa", "id_ed25519", ".netrc", ".npmrc"
        } or source.suffix.lower() in {
            ".arw",
            ".jpg",
            ".jpeg",
            ".psd",
            ".tif",
            ".tiff",
            ".dng",
            ".sqlite",
            ".sqlite-wal",
            ".sqlite-shm",
            ".db",
            ".env",
            ".log",
            ".pfx",
            ".p12",
            ".pem",
            ".key",
        }:
            raise ValueError("Private data is not allowed in the source distribution: " + source.name)
        target = destination / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    inventory = {
        str(p.relative_to(destination)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in destination.rglob("*")
        if p.is_file()
    }
    (destination / "SOURCE-SHA256.txt").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(inventory.items())), encoding="utf-8"
    )
    print(f"Staged {len(inventory)} files from the allowlist")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    stage(parser.parse_args().directory)
