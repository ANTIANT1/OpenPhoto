"""Publication boundaries and vulnerability exceptions must fail closed."""
import hashlib

import pytest

from scripts.audit_dependencies import classify
from scripts.verify_source import verify


def stage_fixture(tmp_path, contents="Public source"):
    (tmp_path / "README.md").write_text(contents)
    digest = hashlib.sha256((tmp_path / "README.md").read_bytes()).hexdigest()
    (tmp_path / "SOURCE-SHA256.txt").write_text(digest + "  README.md\n")
    return tmp_path


def test_source_verifier_rejects_unlisted_and_modified_files(tmp_path):
    folder = stage_fixture(tmp_path)
    assert verify(folder)["ok"]
    private = folder / "private.txt"
    private.write_text("Not in the reviewed inventory")
    with pytest.raises(ValueError, match="complete archive"):
        verify(folder)
    private.unlink()
    (folder / "README.md").write_text("Unexpected modification")
    with pytest.raises(ValueError, match="checksum"):
        verify(folder)


def test_source_verifier_rejects_broken_documentation_links(tmp_path):
    with pytest.raises(ValueError, match="Broken relative link"):
        verify(stage_fixture(tmp_path, "[missing](missing.md)"))


def test_dependency_exception_requires_exact_package_version_and_patch():
    finding = {"id": "PYSEC-2026-1805", "aliases": ["CVE-2026-0994"]}
    report = {"dependencies": [{"name": "protobuf", "version": "4.25.9", "vulns": [finding]}]}
    assert not classify(report, True)["unexpected_findings"]
    assert classify(report, False)["unexpected_findings"]
    report["dependencies"][0]["version"] = "4.25.8"
    assert classify(report, True)["unexpected_findings"]
    report["dependencies"][0].update(version="4.25.9", vulns=[{"id": "NEW-UNREVIEWED"}])
    assert classify(report, True)["unexpected_findings"]
    report["dependencies"] = [{"name": "unknown-package", "skip_reason": "Not in advisory database"}]
    assert classify(report, True)["unexpected_findings"]
