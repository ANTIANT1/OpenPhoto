"""Stage the pinned, signed Microsoft offline runtime installer for packaging."""
import hashlib
import json
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
lock = json.loads((root / "tools/webview2.lock.json").read_text(encoding="utf-8"))
target = root / "tools/vendor/webview2/MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
target.parent.mkdir(parents=True, exist_ok=True)
if not target.is_file():
    partial = target.with_suffix(".partial")
    with httpx.stream("GET", lock["resolved_url"], follow_redirects=True, timeout=120) as response:
        response.raise_for_status()
        with partial.open("wb") as output:
            for chunk in response.iter_bytes(1024*1024):
                output.write(chunk)
    with partial.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != lock["sha256"]:
            raise RuntimeError("Runtime hash mismatch")
    partial.replace(target)
with target.open("rb") as stream:
    if hashlib.file_digest(stream, "sha256").hexdigest() != lock["sha256"]:
        raise RuntimeError("Runtime hash mismatch")
print("Ready: Microsoft WebView2 offline installer")
