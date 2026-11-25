import json
from pathlib import Path
from g2s.config import WorkLayout
from g2s.db import ManifestDB
from g2s.exif import ExifToolRunner, find_exiftool
from g2s.stage import stage_media


class FakeExifRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, dict]] = []

    def apply_metadata(self, file_path: Path, meta: dict) -> None:
        self.calls.append((file_path, meta))
        file_path.write_bytes(file_path.read_bytes() + b"_EXIF")


def test_find_exiftool_checks_tools_dir(tmp_path: Path):
    layout = WorkLayout(tmp_path / "G2S")
    layout.ensure_dirs()
    exe = layout.tools_dir / "exiftool.exe"
    exe.write_bytes(b"stub")
    assert find_exiftool(layout) == exe


def test_exif_runner_pins_tmp_to_work_dir(tmp_path: Path):
    runner = ExifToolRunner(Path("exiftool.exe"), tmp_path / "tmp")
    env = runner._build_env()
    assert env["TMP"] == str(tmp_path / "tmp")
    assert env["TEMP"] == str(tmp_path / "tmp")


def test_stage_dedup_and_collision_handling(tmp_path: Path):
    layout = WorkLayout(tmp_path / "G2S")
    layout.ensure_dirs()
    db = ManifestDB(layout.manifest_db)
    db.init_schema()

    f1 = layout.extracted_dir / "a" / "IMG.jpg"
    f2 = layout.extracted_dir / "b" / "IMG.jpg"  # duplicate content
    f3 = layout.extracted_dir / "c" / "IMG.jpg"  # same name, different content
    for f in (f1, f2, f3):
        f.parent.mkdir(parents=True, exist_ok=True)
    f1.write_bytes(b"same")
    f2.write_bytes(b"same")
    f3.write_bytes(b"different")

    j1 = layout.extracted_dir / "a" / "IMG.jpg.json"
    j1.write_text(json.dumps({"photoTakenTime": {"timestamp": "1700000000"}}))

    db.upsert_scanned(
        str(f1.relative_to(layout.extracted_dir)),
        "h_same",
        4,
        str(j1.relative_to(layout.extracted_dir)),
        "2023",
        "11",
    )
    db.upsert_scanned(
        str(f2.relative_to(layout.extracted_dir)), "h_same", 4, None, "2023", "11"
    )
    db.upsert_scanned(
        str(f3.relative_to(layout.extracted_dir)), "h_diff", 9, None, "2023", "11"
    )

    fake = FakeExifRunner()
    stats = stage_media(layout, db, exif_runner=fake)
    assert stats["staged"] == 2
    assert stats["duplicate_skipped"] == 1
    assert (layout.staging_dir / "2023" / "11" / "IMG.jpg").exists()
    assert (layout.staging_dir / "2023" / "11" / "IMG_2.jpg").exists()
