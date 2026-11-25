"""Stage media files into YYYY/MM structure, deduplicate, and restore EXIF."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable, Protocol

from g2s.config import WorkLayout
from g2s.db import ManifestDB
from g2s.takeout import parse_sidecar_metadata, sha256_file


class MetadataApplier(Protocol):
    def apply_metadata(self, file_path: Path, meta: dict[str, Any]) -> None: ...


def _unique_dest_path(target_dir: Path, filename: str) -> Path:
    """Return a non-colliding path in target_dir, appending _2, _3 if needed."""
    candidate = target_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    idx = 2
    while True:
        candidate = target_dir / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def stage_media(
    layout: WorkLayout,
    db: ManifestDB,
    exif_runner: MetadataApplier | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Deduplicate scanned files, copy to staging/YYYY/MM, apply EXIF, and hash."""
    rows = db.get_by_status("scanned")
    staged = 0
    duplicate_skipped = 0

    for row in rows:
        canonical = db.find_canonical_by_raw_hash(row["raw_sha256"])
        if canonical is not None:
            db.mark_duplicate_skipped(row["id"], canonical["id"])
            duplicate_skipped += 1
            continue

        src = layout.extracted_dir / row["source_path"]
        dest_dir = layout.staging_dir / row["capture_year"] / row["capture_month"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = _unique_dest_path(dest_dir, src.name)

        shutil.copy2(src, dest)

        if exif_runner is not None and row["json_path"] is not None:
            json_full = layout.extracted_dir / row["json_path"]
            if json_full.is_file():
                meta = parse_sidecar_metadata(json_full)
                exif_runner.apply_metadata(dest, meta)

        staged_hash = sha256_file(dest)
        staged_size = dest.stat().st_size
        rel_staged = dest.relative_to(layout.staging_dir).as_posix()
        db.update_stage(row["id"], rel_staged, staged_hash, staged_size)
        staged += 1
        if on_progress and staged % 100 == 0:
            on_progress(f"Staged {staged} files ({duplicate_skipped} duplicates skipped)...")

    return {"staged": staged, "duplicate_skipped": duplicate_skipped}
