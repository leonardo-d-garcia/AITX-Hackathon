"""Stage an uploaded archive or folder into a design directory.

Nothing is executed, nothing is rewritten: every staged file is byte-identical to its source and is
hashed on the way in. The limits below are refusals, not truncations — a rejected archive leaves no
partial staging behind (staging happens in a sibling temp dir that is moved into place at the end).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .errors import rejected

MAX_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_ENTRIES = 500
MESH_SUFFIXES = {".stl", ".obj", ".ply", ".3mf", ".step", ".stp", ".glb", ".gltf"}


class StagedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str          # path relative to the archive root, original filename preserved
    staged_path: str          # ABSOLUTE path of the staged byte-identical copy
    sha256: str
    size_bytes: int
    folder_hint: Optional[str] = None


class StagedArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str                 # ABSOLUTE path of <design_dir>/sources
    origin: str               # absolute path of the zip or folder that was staged
    origin_sha256: Optional[str] = None       # hash of the zip itself, when a zip was given
    files: list[StagedFile] = Field(default_factory=list)
    content_sha256: str = ""  # hash over (source_path, sha256) of every staged file, sorted

    def by_source(self, source_path: str) -> StagedFile:
        for f in self.files:
            if f.source_path == source_path:
                return f
        raise KeyError(source_path)

    @property
    def meshes(self) -> list[StagedFile]:
        return [f for f in self.files if Path(f.source_path).suffix.lower() in MESH_SUFFIXES]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_staged(design_dir: str | Path) -> StagedArchive:
    """Re-read an already staged design directory (``<design_dir>/sources``) and rehash it."""
    root = (Path(design_dir) / "sources").resolve()
    if not root.is_dir():
        raise rejected("design directory has no staged sources", path=str(root))
    files, content = [], hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        digest = sha256_file(path)
        parent = path.parent.relative_to(root).as_posix()
        files.append(StagedFile(source_path=rel, staged_path=str(path), sha256=digest,
                                size_bytes=path.stat().st_size,
                                folder_hint=parent if parent != "." else None))
        content.update(f"{rel}\0{digest}\n".encode())
    return StagedArchive(root=str(root), origin=str(root), files=files,
                         content_sha256=content.hexdigest())


def _check_member_name(name: str) -> str:
    """Return a safe relative path, or raise. Rejects absolute paths, drive letters and ``..``."""
    if not name or name.endswith("/"):
        raise rejected("archive entry has no file name", entry=name)
    norm = name.replace("\\", "/")
    if norm.startswith("/") or (len(norm) > 1 and norm[1] == ":"):
        raise rejected("archive entry uses an absolute path", entry=name)
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise rejected("archive entry escapes the archive root (path traversal)", entry=name)
    return "/".join(parts)


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    return info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16)


def _stage_zip(zip_path: Path, dest: Path) -> list[tuple[str, Path]]:
    staged: list[tuple[str, Path]] = []
    with zipfile.ZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_ENTRIES:
            raise rejected("archive has too many entries", entries=len(infos), limit=MAX_ENTRIES)
        total = 0
        for info in infos:
            if _is_zip_symlink(info):
                raise rejected("archive contains a symbolic link", entry=info.filename)
            rel = _check_member_name(info.filename)
            total += info.file_size
            if total > MAX_EXPANDED_BYTES:
                raise rejected("archive expands beyond the size limit",
                               expanded_bytes=total, limit=MAX_EXPANDED_BYTES)
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(out, "wb") as fh:
                written = 0
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > info.file_size or total - info.file_size + written > MAX_EXPANDED_BYTES:
                        raise rejected("archive entry is larger than it declares",
                                       entry=info.filename, declared=info.file_size)
                    fh.write(chunk)
            staged.append((rel, out))
    return staged


def _stage_dir(src_root: Path, dest: Path) -> list[tuple[str, Path]]:
    staged: list[tuple[str, Path]] = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(src_root):
        for name in sorted(dirnames):
            if (Path(dirpath) / name).is_symlink():
                raise rejected("source folder contains a symbolic link",
                               entry=str((Path(dirpath) / name).relative_to(src_root)))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = _check_member_name(str(path.relative_to(src_root)))
            if path.is_symlink():
                raise rejected("source folder contains a symbolic link", entry=rel)
            if len(staged) + 1 > MAX_ENTRIES:
                raise rejected("source folder has too many entries", limit=MAX_ENTRIES)
            total += path.stat().st_size
            if total > MAX_EXPANDED_BYTES:
                raise rejected("source folder exceeds the size limit",
                               expanded_bytes=total, limit=MAX_EXPANDED_BYTES)
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, out)
            staged.append((rel, out))
    return staged


def stage_archive(zip_or_dir: str | Path, out_dir: str | Path) -> StagedArchive:
    """Copy an archive (.zip) or folder into ``out_dir/sources`` unchanged, hashing every file.

    Rejects path traversal, symbolic links, more than 500 entries and more than 200 MB expanded.
    Nothing from the archive is executed or parsed here.
    """
    origin = Path(zip_or_dir).resolve()
    out_dir = Path(out_dir).resolve()   # staged paths are recorded absolute: a consumer of the
                                        # manifest has no reason to share this process's cwd
    root = out_dir / "sources"
    if not origin.exists():
        raise rejected("input does not exist", path=str(origin))
    if root.exists():
        raise rejected("staging directory already exists", path=str(root))

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".staging-", dir=out_dir))
    try:
        if origin.is_dir():
            entries = _stage_dir(origin, tmp)
            origin_hash = None
        elif zipfile.is_zipfile(origin):
            entries = _stage_zip(origin, tmp)
            origin_hash = sha256_file(origin)
        else:
            raise rejected("input is neither a folder nor a zip archive", path=str(origin))
        if not entries:
            raise rejected("input contains no files", path=str(origin))
        tmp.rename(root)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    files = []
    for rel, _ in sorted(entries):
        staged_path = root / rel
        parent = Path(rel).parent
        files.append(StagedFile(
            source_path=rel,
            staged_path=str(staged_path),
            sha256=sha256_file(staged_path),
            size_bytes=staged_path.stat().st_size,
            folder_hint=None if parent in (Path("."), Path("")) else str(parent),
        ))
    content = hashlib.sha256()
    for f in files:
        content.update(f"{f.source_path}\0{f.sha256}\n".encode())
    return StagedArchive(root=str(root), origin=str(origin), origin_sha256=origin_hash,
                         files=files, content_sha256=content.hexdigest())
