"""Preserve notices for the frozen Python environment and shipped JavaScript dependencies."""
import importlib.metadata
import json
import re
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
directory = root / "licenses"
inventory = []
for distribution in importlib.metadata.distributions():
    name = distribution.metadata.get("Name", "unknown")
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    inventory.append({"name":name,"version":distribution.version,"license":distribution.metadata.get("License-Expression") or distribution.metadata.get("License")})
    for item in distribution.files or []:
        if any(token in str(item).lower() for token in ("license", "copying", "notice")):
            source = Path(distribution.locate_file(item))
            if source.is_file():
                target = directory / "python" / slug / Path(str(item)).name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or target.read_bytes() == source.read_bytes():
                    shutil.copyfile(source, target)
                else:
                    # Some wheels contain several vendor notices with the same base name.
                    import hashlib
                    shutil.copyfile(source, target.with_name(hashlib.sha256(str(item).encode()).hexdigest()[:10] + '-' + target.name))
(directory / "python-build-environment.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
pending = list(json.loads((root / "frontend/package.json").read_text())["dependencies"])
visited = set()
while pending:
    name = pending.pop()
    if name in visited:
        continue
    visited.add(name)
    package = root / "frontend/node_modules" / name
    metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
    pending.extend(metadata.get("dependencies", {}))
    target = directory / "javascript" / name.replace("/", "_")
    target.mkdir(parents=True, exist_ok=True)
    (target / "package.json").write_text(json.dumps({k: metadata.get(k) for k in ("name", "version", "license", "repository")}, indent=2), encoding="utf-8")
    for source in package.iterdir():
        if source.is_file() and any(x in source.name.lower() for x in ("license", "copying", "notice")):
            shutil.copyfile(source, target / source.name)
print(f"Notices: {len(inventory)} Python distributions, {len(visited)} JavaScript packages")
