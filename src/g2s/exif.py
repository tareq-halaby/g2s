"""ExifTool batch-mode runner with TEMP/TMP pinned to the D: workspace."""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from g2s.config import WorkLayout


def find_exiftool(layout: WorkLayout) -> Path | None:
    """Locate exiftool in D:\\G2S\\tools, system PATH, or standard Windows install paths."""
    for name in ("exiftool.exe", "exiftool(-k).exe", "exiftool"):
        candidate = layout.tools_dir / name
        if candidate.is_file():
            return candidate
    found = shutil.which("exiftool")
    if found:
        return Path(found)
    for win_path in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ExifTool" / "ExifTool.exe",
        Path("C:/Program Files/ExifTool/ExifTool.exe"),
    ):
        if win_path.is_file():
            return win_path
    return None


class ExifToolRunner:
    """Runs ExifTool in -stay_open batch mode with TEMP pinned to tmp_dir."""

    def __init__(self, exiftool_path: Path, tmp_dir: Path) -> None:
        self.exiftool_path = Path(exiftool_path)
        self.tmp_dir = Path(tmp_dir)
        self._proc: subprocess.Popen[str] | None = None

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        env["TMP"] = str(self.tmp_dir)
        env["TEMP"] = str(self.tmp_dir)
        return env

    def __enter__(self) -> ExifToolRunner:
        self._proc = subprocess.Popen(
            [str(self.exiftool_path), "-stay_open", "True", "-@", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self._build_env(),
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.write("-stay_open\nFalse\n")
                    self._proc.stdin.flush()
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.kill()
            finally:
                self._proc = None

    def apply_metadata(self, file_path: Path, meta: dict[str, Any]) -> None:
        """Write capture time, GPS, and description tags into file_path."""
        args: list[str] = ["-overwrite_original", "-P"]

        ts = meta.get("timestamp")
        if ts is not None:
            dt = datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc)
            dt_str = dt.strftime("%Y:%m:%d %H:%M:%S")
            args.extend(
                [
                    f"-DateTimeOriginal={dt_str}",
                    f"-CreateDate={dt_str}",
                    f"-ModifyDate={dt_str}",
                ]
            )

        lat = meta.get("latitude")
        lon = meta.get("longitude")
        if lat is not None and lon is not None:
            lat_ref = "N" if lat >= 0 else "S"
            lon_ref = "E" if lon >= 0 else "W"
            args.extend(
                [
                    f"-GPSLatitude={abs(float(lat))}",
                    f"-GPSLatitudeRef={lat_ref}",
                    f"-GPSLongitude={abs(float(lon))}",
                    f"-GPSLongitudeRef={lon_ref}",
                ]
            )
            alt = meta.get("altitude")
            if alt is not None and alt != 0.0:
                args.append(f"-GPSAltitude={abs(float(alt))}")

        desc = meta.get("description")
        if desc:
            clean_desc = str(desc).replace("\r", " ").replace("\n", " ")
            args.append(f"-ImageDescription={clean_desc}")
            args.append(f"-Caption-Abstract={clean_desc}")

        if len(args) <= 2:
            return

        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("ExifToolRunner must be used as a context manager.")

        cmd_lines = [*args, str(file_path), "-execute\n"]
        self._proc.stdin.write("\n".join(cmd_lines))
        self._proc.stdin.flush()

        while True:
            line = self._proc.stdout.readline()
            if not line or line.strip() == "{ready}":
                break
