"""Safe ZIP extraction for uploaded datasets.

Security rules (V8.2 §30):
  * no path traversal (``../`` or absolute paths or drive letters)
  * no symlinks
  * only expected data file types are extracted (image/label/metadata)
  * executables, scripts and archives inside the ZIP are rejected/skipped
  * per-file and total size limits guard against zip bombs
  * nothing extracted is ever executed
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import List

# Whitelist: only these file types are ever extracted.
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
DATA_EXTENSIONS = {".csv", ".tsv", ".json", ".txt", ".md"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | DATA_EXTENSIONS

# Anything with these extensions makes the archive suspicious (rejected).
DANGEROUS_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib", ".bat", ".cmd", ".sh", ".ps1",
    ".py", ".pyc", ".js", ".vbs", ".jar", ".msi", ".app", ".com", ".scr",
}

MAX_TOTAL_UNCOMPRESSED = 4 * 1024 * 1024 * 1024   # 4 GB
MAX_SINGLE_FILE = 512 * 1024 * 1024                # 512 MB
MAX_COMPRESSION_RATIO = 300.0                      # zip-bomb guard
MAX_MEMBERS = 200_000


class UnsafeZipError(Exception):
    """The archive violates a safety rule and must not be processed."""


@dataclass
class ExtractionResult:
    extracted: List[Path] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)      # non-whitelisted but harmless
    warnings: List[str] = field(default_factory=list)


def _member_is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o120000 == 0o120000


def validate_member_name(name: str) -> None:
    """Raise UnsafeZipError for traversal / absolute / dangerous member names."""
    pure = PurePosixPath(name.replace("\\", "/"))
    if pure.is_absolute() or (len(name) >= 2 and name[1] == ":"):
        raise UnsafeZipError(f"Absolute path in archive rejected: {name!r}")
    if any(part == ".." for part in pure.parts):
        raise UnsafeZipError(f"Path traversal in archive rejected: {name!r}")
    suffix = pure.suffix.lower()
    if suffix in DANGEROUS_EXTENSIONS:
        raise UnsafeZipError(
            f"Executable/script file in archive rejected: {name!r}. "
            "Dataset archives must contain only images and label/metadata files.")


def extract_dataset_zip(zip_path: Path, dest_dir: Path) -> ExtractionResult:
    """Safely extract a dataset ZIP.  Never executes anything.

    Raises :class:`UnsafeZipError` on any rule violation and extracts nothing
    in that case (validation happens before extraction starts).
    """
    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)
    if not zipfile.is_zipfile(zip_path):
        raise UnsafeZipError("The selected file is not a valid ZIP archive.")

    result = ExtractionResult()
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.infolist()
        if len(members) > MAX_MEMBERS:
            raise UnsafeZipError(f"Archive has too many members ({len(members)}).")

        total_uncompressed = 0
        to_extract: List[zipfile.ZipInfo] = []
        for info in members:
            if info.is_dir():
                continue
            validate_member_name(info.filename)
            if _member_is_symlink(info):
                raise UnsafeZipError(f"Symlink in archive rejected: {info.filename!r}")
            if info.file_size > MAX_SINGLE_FILE:
                raise UnsafeZipError(f"File too large in archive: {info.filename!r}")
            if info.compress_size > 0 and info.file_size / max(1, info.compress_size) > MAX_COMPRESSION_RATIO:
                raise UnsafeZipError(f"Suspicious compression ratio (zip bomb?): {info.filename!r}")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_TOTAL_UNCOMPRESSED:
                raise UnsafeZipError("Archive exceeds the total uncompressed size limit.")

            suffix = PurePosixPath(info.filename.replace("\\", "/")).suffix.lower()
            if suffix in ALLOWED_EXTENSIONS:
                to_extract.append(info)
            else:
                # Harmless but unexpected (e.g. .xml, .DS_Store) — skip, never extract.
                result.skipped.append(info.filename)

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_resolved = dest_dir.resolve()
        for info in to_extract:
            target = (dest_dir / info.filename.replace("\\", "/")).resolve()
            if not str(target).startswith(str(dest_resolved)):
                raise UnsafeZipError(f"Archive member escapes destination: {info.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            result.extracted.append(target)

    if result.skipped:
        result.warnings.append(
            f"{len(result.skipped)} non-data file(s) were skipped (only images and "
            "label/metadata files are extracted; nothing is ever executed).")
    return result
