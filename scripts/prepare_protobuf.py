"""Reproducible backport of bounded WKT JSON recursion to MediaPipe's protobuf 4 ABI.

Source fix: https://github.com/protocolbuffers/protobuf/commit/d2b0016
Also route Struct/Value/ListValue recursion through ConvertMessage (upstream #26432).
The upstream native extension is unchanged. No runtime monkey patch is used.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

URL = "https://files.pythonhosted.org/packages/f3/16/42a5c7f1001783d2b5bfcecde10127f09010f78982c86ae409122ce3ece6/protobuf-4.25.9-cp310-abi3-win_amd64.whl"
SHA256 = "3683c05154252206f7cb2d371626514b3708199d9bcf683b503dabf3a2e38e06"
VERSION = "4.25.9+openphoto.1"


def build(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=60) as response:
        original = response.read()
    if hashlib.sha256(original).hexdigest() != SHA256:
        raise RuntimeError("Upstream wheel checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        files = {
            name.replace("protobuf-4.25.9.dist-info", f"protobuf-{VERSION}.dist-info"): archive.read(name)
            for name in archive.namelist()
            if not name.endswith("/RECORD")
        }
    name = "google/protobuf/json_format.py"
    source = files[name].decode()
    start = source.index(
        "    if _IsWrapperMessage(message_descriptor):", source.index("  def _ConvertAnyMessage")
    )
    end = source.index("    # Sets Any message", start)
    source = (
        source[:start]
        + """    if _IsWrapperMessage(message_descriptor) or full_name in _WKTJSONMETHODS:
      self.ConvertMessage(value['value'], sub_message, '{0}.value'.format(path))
    else:
      payload = {key: item for key, item in value.items() if key != '@type'}
      self.ConvertMessage(payload, sub_message, path)
"""
        + source[end:]
    )
    for before, after in (
        (
            "self._ConvertStructMessage(value, message.struct_value, path)",
            "self.ConvertMessage(value, message.struct_value, path)",
        ),
        (
            "self._ConvertListValueMessage(value, message.list_value, path)",
            "self.ConvertMessage(value, message.list_value, path)",
        ),
        (
            "self._ConvertValueMessage(item, message.values.add(),",
            "self.ConvertMessage(item, message.values.add(),",
        ),
        (
            "self._ConvertValueMessage(value[key], message.fields[key],",
            "self.ConvertMessage(value[key], message.fields[key],",
        ),
    ):
        if before not in source:
            raise RuntimeError("Expected upstream patch location is missing")
        source = source.replace(before, after)
    files[name] = source.encode()
    metadata = f"protobuf-{VERSION}.dist-info/METADATA"
    files[metadata] = files[metadata].replace(b"Version: 4.25.9\n", f"Version: {VERSION}\n".encode())
    files["google/protobuf/__init__.py"] = files["google/protobuf/__init__.py"].replace(
        b"'4.25.9'", repr(VERSION).encode()
    )
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for entry, contents in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).rstrip(b"=").decode()
        writer.writerow((entry, "sha256=" + digest, len(contents)))
    writer.writerow((f"protobuf-{VERSION}.dist-info/RECORD", "", ""))
    files[f"protobuf-{VERSION}.dist-info/RECORD"] = record.getvalue().encode()
    output = directory / f"protobuf-{VERSION}-cp310-abi3-win_amd64.whl"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry, contents in sorted(files.items()):
            info = zipfile.ZipInfo(entry, (2026, 9, 13, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, contents)
    manifest = {
        "version": VERSION,
        "upstream_url": URL,
        "upstream_sha256": SHA256,
        "wheel_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "json_format_sha256": hashlib.sha256(files[name]).hexdigest(),
        "fixes": ["CVE-2026-0994", "protobuf-issue-26432"],
    }
    output.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1] / "tools/wheels")
