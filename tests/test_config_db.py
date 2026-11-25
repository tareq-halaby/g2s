from pathlib import Path
from g2s.config import WorkLayout, MEDIA_EXTENSIONS
from g2s.db import ManifestDB


def test_work_layout_defaults_to_d_drive(tmp_path: Path):
    default = WorkLayout()
    assert default.work_dir == Path("D:/G2S")
    custom = WorkLayout(tmp_path / "G2S")
    custom.ensure_dirs()
    for d in (
        custom.takeout_dir,
        custom.extracted_dir,
        custom.staging_dir,
        custom.state_dir,
        custom.tmp_dir,
        custom.tools_dir,
        custom.reports_dir,
    ):
        assert d.is_dir()
    assert ".jpg" in MEDIA_EXTENSIONS and ".mp4" in MEDIA_EXTENSIONS


def test_manifest_db_lifecycle(tmp_path: Path):
    db = ManifestDB(tmp_path / "manifest.db")
    db.init_schema()
    assert not db.is_archive_extracted("takeout-001.zip")
    db.mark_archive_extracted("takeout-001.zip", 1024)
    assert db.is_archive_extracted("takeout-001.zip")

    row_id = db.upsert_scanned(
        source_path="a/IMG_1.jpg",
        raw_sha256="abc",
        raw_size=100,
        json_path="a/IMG_1.jpg.json",
        capture_year="2024",
        capture_month="05",
    )
    assert db.find_canonical_by_raw_hash("abc") is None
    db.update_stage(
        row_id, staged_path="2024/05/IMG_1.jpg", staged_sha256="def", staged_size=110
    )
    assert db.find_canonical_by_raw_hash("abc")["id"] == row_id
    db.update_transfer(row_id, dest_path="\\\\nas\\photo\\2024\\05\\IMG_1.jpg")
    db.update_verify(row_id, verified=True, error=None)
    assert db.summary_counts()["verified"] == 1
