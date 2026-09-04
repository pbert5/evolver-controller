"""Fail-closed native release archive contract helpers."""
from __future__ import annotations

import posixpath
import shutil
import stat
import tarfile
from pathlib import Path


RESERVED_ARCHIVE_PATHS = frozenset({"manifest.json", "firmware.bin", "controller.tar.gz", "artifact.env"})


def validate_archive_members(archive: tarfile.TarFile) -> None:
    """Reject traversal, duplicate, link, and prefix-collision members."""
    seen: set[str] = set()
    kinds: dict[str, str] = {}
    for member in archive.getmembers():
        name = member.name
        if not name or name.startswith("/") or "\x00" in name:
            raise ValueError("native archive has an unsafe member path")
        normalized = posixpath.normpath(name)
        if normalized in {".", ".."} or normalized.startswith("../"):
            raise ValueError("native archive member escapes extraction root")
        if normalized in RESERVED_ARCHIVE_PATHS or normalized.startswith("firmware/"):
            raise ValueError("native archive contains a reserved release path")
        if normalized in seen:
            raise ValueError("native archive contains duplicate members")
        seen.add(normalized)
        if member.isdir():
            kinds[normalized.rstrip("/")] = "dir"
        elif member.isfile():
            kinds[normalized] = "file"
        else:
            raise ValueError("native archive contains links or special files")
    for name, kind in kinds.items():
        parent = posixpath.dirname(name)
        while parent:
            if kinds.get(parent) == "file":
                raise ValueError("native archive contains a file/directory prefix collision")
            parent = posixpath.dirname(parent)


def materialize_tree(source: Path, destination: Path) -> None:
    """Copy a tree, dereferencing only bounded in-tree symlinks."""
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"materialization source is not a directory: {source}")
    active: set[Path] = set()

    def copy_node(src: Path, dst: Path) -> None:
        lst = src.lstat()
        if stat.S_ISLNK(lst.st_mode):
            raw_target = src.readlink()
            if raw_target.is_absolute():
                raise ValueError(f"absolute symlink is not allowed: {src}")
            target = (src.parent / raw_target).resolve()
            try:
                target.relative_to(source)
            except ValueError as exc:
                raise ValueError(f"symlink escapes materialization tree: {src}") from exc
            if not target.exists():
                raise ValueError(f"dangling symlink: {src}")
            copy_node(target, dst)
            return
        if stat.S_ISDIR(lst.st_mode):
            real = src.resolve()
            if real in active:
                raise ValueError(f"symlink cycle detected at: {src}")
            active.add(real)
            dst.mkdir(parents=True, exist_ok=False)
            shutil.copystat(src, dst, follow_symlinks=False)
            for child in sorted(src.iterdir(), key=lambda p: p.name):
                copy_node(child, dst / child.name)
            active.remove(real)
            return
        if stat.S_ISREG(lst.st_mode):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst, follow_symlinks=False)
            return
        raise ValueError(f"unsupported source filesystem object: {src}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    copy_node(source, destination)
