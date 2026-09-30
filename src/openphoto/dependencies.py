"""Relocatable bundled dependencies; explicit overrides stay user owned."""

from pathlib import Path


def resolve_dependencies(catalog, root):
    settings = catalog.settings()
    defaults = {
        "rawtherapee": next((root / "tools/vendor/rawtherapee").rglob("rawtherapee-cli.exe"), None),
        "exiftool": next((root / "tools/vendor/exiftool").rglob("exiftool.exe"), None),
        "models_directory": root / "models",
    }
    for name, candidate in defaults.items():
        current = settings.get(name)
        mode = settings.get(name + "_source")
        if mode == "custom":
            continue
        is_bundled = mode == "bundled" or not current or not Path(current).exists()
        if current and Path(current).is_relative_to(root):
            is_bundled = True
        if is_bundled and candidate and candidate.exists():
            catalog.set_setting(name, str(candidate.resolve()))
            catalog.set_setting(name + "_source", "bundled")
        elif current and mode is None:
            catalog.set_setting(name + "_source", "custom")
