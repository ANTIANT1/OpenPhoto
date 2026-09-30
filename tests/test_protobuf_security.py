import hashlib
import json
from pathlib import Path

import pytest


def test_protobuf_backport_matches_manifest():
    from google.protobuf import json_format

    manifest_path = (
        Path(__file__).parents[1] / "tools/wheels/protobuf-4.25.9+openphoto.1-cp310-abi3-win_amd64.json"
    )
    expected = json.loads(manifest_path.read_text())["json_format_sha256"]
    assert hashlib.sha256(Path(json_format.__file__).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("kind", ["any", "struct", "list"])
def test_protobuf_recursion_limit_cannot_be_bypassed(kind):
    from google.protobuf import any_pb2, json_format, struct_pb2

    if kind == "any":
        value = {"@type": "type.googleapis.com/google.protobuf.Struct", "value": {"safe": 1}}
        for _ in range(30):
            value = {"@type": "type.googleapis.com/google.protobuf.Any", "value": value}
        message = any_pb2.Any()
    elif kind == "struct":
        value = {"safe": 1}
        for _ in range(30):
            value = {"nested": value}
        message = struct_pb2.Struct()
    else:
        value = [1]
        for _ in range(30):
            value = [value]
        message = struct_pb2.ListValue()
    with pytest.raises(json_format.ParseError, match="too deep"):
        json_format.ParseDict(value, message, max_recursion_depth=10)


def test_normal_protobuf_json_still_roundtrips():
    from google.protobuf import json_format, struct_pb2

    value = {"number": 3, "nested": [{"flag": True, "text": "портрет"}]}
    parsed = json_format.ParseDict(value, struct_pb2.Struct(), max_recursion_depth=30)
    assert json_format.MessageToDict(parsed) == value
