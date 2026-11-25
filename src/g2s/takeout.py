"""Google Takeout archive extraction, JSON sidecar matching, and media scanning."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Callable

from g2s.config import MEDIA_EXTENSIONS, WorkLayout
from g2s.db import ManifestDB

_DUP_RE = re.compile(r"^(?P<stem>.+)\((?P<num>\d+)\)(?P<ext>\.[^.]+)$")
_EDITED_SUFFIXES = ("-edited", "-edytowane", "-bearbeitet", "-modifié", "-modificado")
_FILENAME_DATE_RE = re.compile(
    r"(?:^|[^\d])(?P<year>19\d{2}|20\d{2})[-_.]?(?P<month>0[1-9]|1[0-2])[-_.]?(?P<day>0[1-9]|[12]\d|3[01])(?:[^\d]|$)"
)
_FOLDER_YEAR_RE = re.compile(r"Photos from (?P<year>19\d{2}|20\d{2})", re.IGNORECASE)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute SHA-256 hex digest of a file in streaming chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def extract_archives(
    layout: WorkLayout,
    db: ManifestDB,
    on_progress: Callable[[str], None] | None = None,
) -> list[str]:
    """Extract unextracted .zip archives from takeout_dir into extracted_dir."""
    extracted: list[str] = []
    for zpath in sorted(layout.takeout_dir.glob("*.zip")):
        if db.is_archive_extracted(zpath.name):
            continue
        if on_progress:
            on_progress(f"Extracting {zpath.name}...")
        with zipfile.ZipFile(zpath, "r") as zf:
            zf.extractall(layout.extracted_dir)
        db.mark_archive_extracted(zpath.name, zpath.stat().st_size)
        extracted.append(zpath.name)
    return extracted


def _candidate_json_names(filename: str) -> list[str]:
    """Generate candidate Google Takeout sidecar filenames in priority order."""
    candidates: list[str] = [
        f"{filename}.supplemental-metadata.json",
        f"{filename}.json",
    ]
    # Truncated long filenames (Takeout truncates full name at ~46-51 chars)
    for limit in (46, 47, 48, 49, 50, 51):
        if len(filename) > limit:
            prefix = filename[:limit]
            candidates.append(f"{prefix}.supplemental-metadata.json")
            candidates.append(f"{prefix}.json")

    # Numbered duplicate: IMG_003(1).jpg -> IMG_003.jpg(1).json
    m = _DUP_RE.match(filename)
    if m:
        reordered = f"{m.group('stem')}{m.group('ext')}({m.group('num')})"
        candidates.append(f"{reordered}.supplemental-metadata.json")
        candidates.append(f"{reordered}.json")

    # Edited suffix: IMG_002-edited.jpg -> IMG_002.jpg.json
    stem = Path(filename).stem
    ext = Path(filename).suffix
    for suffix in _EDITED_SUFFIXES:
        if stem.lower().endswith(suffix):
            orig_name = f"{stem[: -len(suffix)]}{ext}"
            candidates.append(f"{orig_name}.supplemental-metadata.json")
            candidates.append(f"{orig_name}.json")
            break

    return candidates


def find_sidecar_json(media_path: Path) -> Path | None:
    """Locate the matching Google Takeout .json sidecar in the same directory."""
    parent = media_path.parent
    for name in _candidate_json_names(media_path.name):
        candidate = parent / name
        if candidate.is_file():
            return candidate
    return None


def parse_sidecar_metadata(json_path: Path) -> dict[str, Any]:
    """Extract timestamp, GPS coordinates, and description from a Takeout JSON file."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    ts_raw = (
        data.get("photoTakenTime", {}).get("timestamp")
        or data.get("creationTime", {}).get("timestamp")
    )
    timestamp = int(ts_raw) if ts_raw is not None and str(ts_raw).isdigit() else None

    geo = data.get("geoData") or data.get("geoDataExif") or {}
    lat = geo.get("latitude")
    lon = geo.get("longitude")
    alt = geo.get("altitude")
    if lat == 0.0 and lon == 0.0:
        lat, lon, alt = None, None, None

    desc = data.get("description") or None
    return {
        "timestamp": timestamp,
        "latitude": lat,
        "longitude": lon,
        "altitude": alt,
        "description": desc,
    }


def _infer_year_month(path: Path, ts: int | None) -> tuple[str, str]:
    if ts is not None:
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        return (f"{dt.year:04d}", f"{dt.month:02d}")
    m_name = _FILENAME_DATE_RE.search(path.stem)
    if m_name:
        return (m_name.group("year"), m_name.group("month"))
    for part in path.parts:
        m_folder = _FOLDER_YEAR_RE.search(part)
        if m_folder:
            return (m_folder.group("year"), "00")
    return ("UnknownDate", "00")


def scan_takeout(
    layout: WorkLayout,
    db: ManifestDB,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Extract any new archives and inventory all media files into ManifestDB."""
    extract_archives(layout, db, on_progress=on_progress)

    scanned = 0
    missing_json = 0
    for path in sorted(layout.extracted_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("._"):
            continue
        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue

        rel_source = path.relative_to(layout.extracted_dir).as_posix()
        sidecar = find_sidecar_json(path)
        rel_json = (
            sidecar.relative_to(layout.extracted_dir).as_posix()
            if sidecar is not None
            else None
        )

        ts: int | None = None
        if sidecar is not None:
            try:
                ts = parse_sidecar_metadata(sidecar)["timestamp"]
            except (json.JSONDecodeError, OSError):
                ts = None
        else:
            missing_json += 1

        year, month = _infer_year_month(path, ts)
        raw_hash = sha256_file(path)
        raw_size = path.stat().st_size
        db.upsert_scanned(
            source_path=rel_source,
            raw_sha256=raw_hash,
            raw_size=raw_size,
            json_path=rel_json,
            capture_year=year,
            capture_month=month,
        )
        scanned += 1
        if on_progress and scanned % 250 == 0:
            on_progress(f"Scanned {scanned} media files...")

    return {"scanned": scanned, "missing_json": missing_json}
