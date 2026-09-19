"""Staging is a security boundary: an archive is untrusted input."""
from __future__ import annotations

import hashlib
import stat
import zipfile
from pathlib import Path

import pytest

from dronebench_ingest import stage_archive
from dronebench_ingest.errors import IngestError
from dronebench_ingest.staging import MAX_ENTRIES, load_staged


def _zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


def test_rejects_path_traversal(tmp_path):
    archive = _zip(tmp_path / "evil.zip", {"../escaped.stl": b"x", "ok.stl": b"y"})
    with pytest.raises(IngestError) as exc:
        stage_archive(archive, tmp_path / "design")
    assert exc.value.envelope.code.value == "INPUT_REJECTED"
    assert "traversal" in exc.value.envelope.message
    assert not (tmp_path / "design" / "sources").exists()
    assert not (tmp_path / "escaped.stl").exists()


def test_rejects_absolute_member(tmp_path):
    archive = _zip(tmp_path / "abs.zip", {"/etc/passwd": b"x"})
    with pytest.raises(IngestError) as exc:
        stage_archive(archive, tmp_path / "design")
    assert "absolute" in exc.value.envelope.message


def test_rejects_symlink_in_zip(tmp_path):
    archive = tmp_path / "link.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("link.stl")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
        zf.writestr("real.stl", b"solid")
    with pytest.raises(IngestError) as exc:
        stage_archive(archive, tmp_path / "design")
    assert "symbolic link" in exc.value.envelope.message


def test_rejects_symlink_in_folder(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "real.stl").write_bytes(b"solid")
    (src / "link.stl").symlink_to("/etc/passwd")
    with pytest.raises(IngestError) as exc:
        stage_archive(src, tmp_path / "design")
    assert "symbolic link" in exc.value.envelope.message


def test_rejects_oversize_expansion(tmp_path, monkeypatch):
    import dronebench_ingest.staging as staging
    monkeypatch.setattr(staging, "MAX_EXPANDED_BYTES", 1024)
    archive = _zip(tmp_path / "big.zip", {"big.stl": b"0" * 4096})
    with pytest.raises(IngestError) as exc:
        staging.stage_archive(archive, tmp_path / "design")
    assert "size limit" in exc.value.envelope.message


def test_rejects_too_many_entries(tmp_path):
    archive = _zip(tmp_path / "many.zip", {f"f{i}.stl": b"x" for i in range(MAX_ENTRIES + 1)})
    with pytest.raises(IngestError) as exc:
        stage_archive(archive, tmp_path / "design")
    assert "too many entries" in exc.value.envelope.message


def test_staged_bytes_are_identical_and_hashed(tmp_path):
    payload = b"solid demo\nfacet\n" * 10
    archive = _zip(tmp_path / "ok.zip", {"Wings/wing1.stl": payload})
    staged = stage_archive(archive, tmp_path / "design")
    assert [f.source_path for f in staged.files] == ["Wings/wing1.stl"]
    entry = staged.files[0]
    assert Path(entry.staged_path).read_bytes() == payload
    assert entry.sha256 == hashlib.sha256(payload).hexdigest()
    assert entry.folder_hint == "Wings"
    assert staged.origin_sha256 is not None
    # re-reading the staged directory reproduces the same content hash
    assert load_staged(tmp_path / "design").content_sha256 == staged.content_sha256


def test_will_not_stage_twice_into_the_same_design(tmp_path):
    archive = _zip(tmp_path / "ok.zip", {"a.stl": b"x"})
    stage_archive(archive, tmp_path / "design")
    with pytest.raises(IngestError):
        stage_archive(archive, tmp_path / "design")


def test_real_archive_is_staged_unchanged(staged):
    _, archive, _ = staged
    assert len(archive.files) == 24
    for entry in archive.files:
        original = Path(archive.origin) / entry.source_path
        assert Path(entry.staged_path).read_bytes() == original.read_bytes()
        assert entry.folder_hint  # every vendor file sits in a named folder
