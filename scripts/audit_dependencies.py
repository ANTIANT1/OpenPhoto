"""Audit every locked Python version, including reviewed local-version normalization."""
import argparse
import hashlib
import json
import os
import subprocess
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIP_AUDIT_VERSION = "2.10.1"
PROTOBUF_EXCEPTIONS = {"CVE-2026-0994", "GHSA-7gcm-g887-7qv7", "PYSEC-2026-1805"}


def backport_verified():
    wheel = ROOT / "tools/wheels/protobuf-4.25.9+openphoto.1-cp310-abi3-win_amd64.whl"
    record = json.loads(wheel.with_suffix(".json").read_text())
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != record["wheel_sha256"]:
        return False
    with zipfile.ZipFile(wheel) as archive:
        source = archive.read("google/protobuf/json_format.py")
    return hashlib.sha256(source).hexdigest() == record["json_format_sha256"]


def classify(report, patched):
    unexpected, reviewed = [], []
    for dependency in report["dependencies"]:
        if dependency.get("skip_reason"):
            unexpected.append({"name": dependency["name"], "reason": dependency["skip_reason"]})
        for vulnerability in dependency.get("vulns", []):
            ids = {vulnerability["id"], *vulnerability.get("aliases", [])}
            entry = {"name": dependency["name"], "version": dependency.get("version"),
                     "id": vulnerability["id"]}
            if (patched and dependency["name"] == "protobuf" and dependency.get("version") == "4.25.9"
                    and ids & PROTOBUF_EXCEPTIONS):
                reviewed.append(entry)
            else:
                unexpected.append(entry)
    return {"audited_versions": len(report["dependencies"]), "reviewed_backport_findings": reviewed,
            "unexpected_findings": unexpected, "backport_verified": patched}


def run(output):
    output = output.resolve()
    if not output.is_relative_to(ROOT / ".cache"):
        raise ValueError("Keep audit output under .cache")
    output.mkdir(parents=True, exist_ok=False)
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    versions = {}
    for package in lock["package"]:
        name, version = package["name"], package["version"]
        if name == "openphoto":
            continue
        if "+" in version:
            allowed = {"torch": "2.13.0+cu126", "torchvision": "0.28.0+cu126",
                       "protobuf": "4.25.9+openphoto.1"}
            if allowed.get(name) != version:
                raise ValueError("Unreviewed local version: " + name)
            version = version.split("+", 1)[0]
        if name in versions and versions[name] != version:
            raise ValueError("Review multiple locked versions for " + name)
        versions[name] = version
    requirements = output / "requirements.txt"
    requirements.write_text("".join(f"{name}=={version}\n" for name, version in sorted(versions.items())))
    raw = output / "pip-audit.json"
    environment = dict(os.environ)
    for key, folder in (("UV_CACHE_DIR", "uv"), ("UV_TOOL_DIR", "uv-tools"), ("UV_TOOL_BIN_DIR", "uv-bin")):
        environment.setdefault(key, str(ROOT / ".cache" / folder))
    result = subprocess.run([
        "uv", "tool", "run", "--from", "pip-audit==" + PIP_AUDIT_VERSION, "pip-audit",
        "--requirement", str(requirements), "--no-deps", "--disable-pip",
        "--cache-dir", str(ROOT / ".cache/pip-audit"), "--format", "json", "--output", str(raw),
    ], env=environment)
    if result.returncode not in (0, 1) or not raw.is_file():
        raise RuntimeError("Dependency audit did not finish")
    summary = classify(json.loads(raw.read_text()), backport_verified())
    if summary["audited_versions"] != len(versions):
        raise ValueError("Audit omitted locked versions")
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))
    return 1 if summary["unexpected_findings"] or not summary["backport_verified"] else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(run(parser.parse_args().output))
