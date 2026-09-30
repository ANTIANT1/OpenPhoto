"""Verify a staged manifest, public documentation links, and source boundaries."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def verify(directory):
    directory = directory.resolve()
    manifest = directory / "SOURCE-SHA256.txt"
    expected = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or name in expected:
            raise ValueError("Invalid or duplicate manifest path")
        expected[name] = digest
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    if actual != set(expected) | {"SOURCE-SHA256.txt"}:
        raise ValueError("Source manifest does not describe the complete archive")
    for name, digest in expected.items():
        path = directory / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Source checksum mismatch: " + name)
        if any(part in {".git", ".venv", "node_modules", "__pycache__", "projects", "outputs", "models"}
               for part in Path(name).parts):
            raise ValueError("Private or generated directory in source: " + name)
        if path.suffix in {".md", ".py", ".json", ".toml", ".ts", ".tsx", ".cjs", ".yml", ".ps1"}:
            text = path.read_text(encoding="utf-8")
            if re.search(r"[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|Default\b)[A-Za-z0-9_-]+[\\/]", text):
                raise ValueError("Machine-local user path in source: " + name)
        if path.suffix == ".md" and "licenses" not in path.parts:
            for link in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if "://" in link or link.startswith("#") or link.startswith("mailto:"):
                    continue
                target = (path.parent / link.split("#")[0]).resolve()
                if not target.is_relative_to(directory) or not target.exists():
                    raise ValueError(f"Broken relative link in {name}: {link}")
    result = {"ok": True, "source_files": len(expected), "manifest_files": len(actual)}
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    verify(parser.parse_args().directory)
