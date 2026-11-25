"""Workspace layout and media constants for G2S."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".heic",
        ".heif",
        ".webp",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".raw",
        ".dng",
        ".cr2",
        ".nef",
        ".arw",
        ".mp4",
        ".mov",
        ".m4v",
        ".avi",
        ".3gp",
        ".mkv",
        ".webm",
        ".mts",
    }
)


@dataclass(frozen=True)
class WorkLayout:
    """Defines all working directories under `work_dir` (defaults to D:\\G2S)."""

    work_dir: Path = Path("D:/G2S")

    @property
    def takeout_dir(self) -> Path:
        return self.work_dir / "takeout"

    @property
    def extracted_dir(self) -> Path:
        return self.work_dir / "extracted"

    @property
    def staging_dir(self) -> Path:
        return self.work_dir / "staging"

    @property
    def state_dir(self) -> Path:
        return self.work_dir / "state"

    @property
    def manifest_db(self) -> Path:
        return self.state_dir / "manifest.db"

    @property
    def tmp_dir(self) -> Path:
        return self.work_dir / "tmp"

    @property
    def tools_dir(self) -> Path:
        return self.work_dir / "tools"

    @property
    def reports_dir(self) -> Path:
        return self.work_dir / "reports"

    def ensure_dirs(self) -> None:
        """Create all working directories if they do not exist."""
        for directory in (
            self.work_dir,
            self.takeout_dir,
            self.extracted_dir,
            self.staging_dir,
            self.state_dir,
            self.tmp_dir,
            self.tools_dir,
            self.reports_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
