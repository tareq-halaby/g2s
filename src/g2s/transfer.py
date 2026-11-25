"""Atomic SMB transfer from local staging to Synology NAS."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable

from g2s.config import WorkLayout
from g2s.db import ManifestDB
from g2s.takeout import sha256_file


def transfer_to_nas(
    layout: WorkLayout,
    db: ManifestDB,
    dest_root: Path,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Copy staged files to dest_root atomically via .g2s_tmp + os.replace."""
    dest_root = Path(dest_root)
    rows = db.get_by_status("staged") + db.get_by_status("verify_failed")
    transferred = 0
    skipped_existing = 0

    for row in rows:
        src = layout.staging_dir / row["staged_path"]
        dest = dest_root / row["staged_path"]

        if (
            dest.is_file()
            and dest.stat().st_size == row["staged_size"]
            and sha256_file(dest) == row["staged_sha256"]
        ):
            db.update_transfer(row["id"], str(dest))
            transferred += 1
            skipped_existing += 1
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp_dest = dest.with_name(dest.name + ".g2s_tmp")

        shutil.copy2(src, tmp_dest)
        os.replace(tmp_dest, dest)
        db.update_transfer(row["id"], str(dest))
        transferred += 1

        if on_progress and transferred % 50 == 0:
            on_progress(f"Transferred {transferred}/{len(rows)} files to NAS...")

    return {"transferred": transferred, "skipped_existing": skipped_existing}
