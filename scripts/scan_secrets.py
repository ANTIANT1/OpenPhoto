"""Scan an explicit source tree or Git history, with redaction and a failing exit code."""
import argparse
import json
import subprocess
from pathlib import Path

from prepare_security import ROOT, prepare


def run(source, output, history=False):
    source, output = source.resolve(), output.resolve()
    if not source.is_dir():
        raise ValueError("Source directory does not exist")
    if not output.is_relative_to(ROOT / ".cache"):
        raise ValueError("Keep reports in the workspace .cache directory")
    output.mkdir(parents=True, exist_ok=False)
    report = output / "gitleaks.json"
    command = [str(prepare()), "git" if history else "dir", str(source),
               "--config", str(ROOT / ".gitleaks.toml"), "--redact=100", "--no-banner", "--no-color",
               "--report-format", "json", "--report-path", str(report)]
    if history:
        command.append("--log-opts=--all")
    result = subprocess.run(command, capture_output=True, text=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode not in (0, 1):
        raise RuntimeError("Gitleaks failed: " + result.stderr[-1500:])
    findings = json.loads(report.read_text(encoding="utf-8") or "[]")
    summary = {"findings": len(findings), "redacted": True, "history": history}
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    return 1 if findings or result.returncode else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(args.source, args.output, args.history))
