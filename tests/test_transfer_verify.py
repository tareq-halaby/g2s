from pathlib import Path
from g2s.config import WorkLayout
from g2s.db import ManifestDB
from g2s.takeout import sha256_file
from g2s.transfer import transfer_to_nas
from g2s.verify import verify_nas, write_reports


def test_atomic_transfer_and_verify_pass_and_tamper_fail(tmp_path: Path):
    layout = WorkLayout(tmp_path / "G2S")
    layout.ensure_dirs()
    nas_dest = tmp_path / "NAS_SMB" / "Photos"
    db = ManifestDB(layout.manifest_db)
    db.init_schema()

    staged = layout.staging_dir / "2024" / "01" / "pic.jpg"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"realbytes")
    h = sha256_file(staged)

    rid = db.upsert_scanned("pic.jpg", "raw", 9, None, "2024", "01")
    db.update_stage(rid, "2024/01/pic.jpg", h, 9)

    # Simulate stale .g2s_tmp from interrupted run
    stale = nas_dest / "2024" / "01" / "pic.jpg.g2s_tmp"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"partial")

    t_stats = transfer_to_nas(layout, db, nas_dest)
    assert t_stats["transferred"] == 1
    assert not stale.exists()

    v_stats = verify_nas(layout, db)
    assert v_stats["verified"] == 1
    assert v_stats["failed"] == 0

    html_path, csv_path = write_reports(layout, db)
    assert "100% VERIFIED" in html_path.read_text(encoding="utf-8")
    assert csv_path.exists()


def test_verify_detects_corruption(tmp_path: Path):
    layout = WorkLayout(tmp_path / "G2S")
    layout.ensure_dirs()
    nas_dest = tmp_path / "NAS_SMB" / "Photos"
    db = ManifestDB(layout.manifest_db)
    db.init_schema()

    staged = layout.staging_dir / "2024" / "01" / "pic.jpg"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"realbytes")
    rid = db.upsert_scanned("pic.jpg", "raw", 9, None, "2024", "01")
    db.update_stage(rid, "2024/01/pic.jpg", sha256_file(staged), 9)

    transfer_to_nas(layout, db, nas_dest)
    (nas_dest / "2024" / "01" / "pic.jpg").write_bytes(b"corrupted")

    v_stats = verify_nas(layout, db)
    assert v_stats["failed"] == 1
    html_path, _ = write_reports(layout, db)
    assert "VERIFICATION FAILED" in html_path.read_text(encoding="utf-8")


def test_transfer_skips_identical_file_already_on_nas(tmp_path: Path):
    layout = WorkLayout(tmp_path / "G2S")
    layout.ensure_dirs()
    nas_dest = tmp_path / "NAS_SMB" / "Photos"
    db = ManifestDB(layout.manifest_db)
    db.init_schema()

    staged = layout.staging_dir / "2024" / "02" / "already.jpg"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"identical")
    h = sha256_file(staged)

    rid = db.upsert_scanned("already.jpg", "raw", 9, None, "2024", "02")
    db.update_stage(rid, "2024/02/already.jpg", h, 9)

    existing = nas_dest / "2024" / "02" / "already.jpg"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"identical")

    t_stats = transfer_to_nas(layout, db, nas_dest)
    assert t_stats["transferred"] == 1
    assert t_stats["skipped_existing"] == 1
