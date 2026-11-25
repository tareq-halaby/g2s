import json
import zipfile
from pathlib import Path
import pytest
from g2s.config import WorkLayout
from g2s.db import ManifestDB
from g2s.takeout import (
    extract_archives,
    find_sidecar_json,
    parse_sidecar_metadata,
    scan_takeout,
)


def test_find_sidecar_json_variants(tmp_path: Path):
    # 1. Exact & supplemental-metadata
    p1 = tmp_path / "IMG_001.jpg"
    p1.write_bytes(b"a")
    j1 = tmp_path / "IMG_001.jpg.supplemental-metadata.json"
    j1.write_text("{}")
    assert find_sidecar_json(p1) == j1

    # 2. -edited suffix fallback
    p2 = tmp_path / "IMG_002-edited.jpg"
    p2.write_bytes(b"b")
    j2 = tmp_path / "IMG_002.jpg.json"
    j2.write_text("{}")
    assert find_sidecar_json(p2) == j2

    # 3. Numbered duplicate IMG_003(1).jpg -> IMG_003.jpg(1).json
    p3 = tmp_path / "IMG_003(1).jpg"
    p3.write_bytes(b"c")
    j3 = tmp_path / "IMG_003.jpg(1).json"
    j3.write_text("{}")
    assert find_sidecar_json(p3) == j3

    # 4. Truncated long filename (46-char stem limit in Takeout)
    long_name = "A" * 60 + ".jpg"
    p4 = tmp_path / long_name
    p4.write_bytes(b"d")
    j4 = tmp_path / (long_name[:46] + ".json")
    j4.write_text("{}")
    assert find_sidecar_json(p4) == j4


def test_corrupt_zip_raises_without_marking_extracted(tmp_path: Path):
    layout = WorkLayout(tmp_path / "G2S")
    layout.ensure_dirs()
    bad_zip = layout.takeout_dir / "bad.zip"
    bad_zip.write_bytes(b"not a zip")
    db = ManifestDB(layout.manifest_db)
    db.init_schema()
    with pytest.raises(zipfile.BadZipFile):
        extract_archives(layout, db)
    assert not db.is_archive_extracted("bad.zip")


def test_scan_takeout_end_to_end(tmp_path: Path):
    layout = WorkLayout(tmp_path / "G2S")
    layout.ensure_dirs()
    zpath = layout.takeout_dir / "takeout-1.zip"
    meta = {
        "photoTakenTime": {"timestamp": "1700000000"},
        "geoData": {"latitude": 52.5, "longitude": 13.4, "altitude": 0.0},
        "description": "Berlin",
    }
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("Takeout/Google Photos/2023/p.jpg", b"jpegdata")
        zf.writestr("Takeout/Google Photos/2023/p.jpg.json", json.dumps(meta))
    db = ManifestDB(layout.manifest_db)
    db.init_schema()
    stats = scan_takeout(layout, db)
    assert stats["scanned"] == 1
    rows = db.get_by_status("scanned")
    assert rows[0]["capture_year"] == "2023"
    assert rows[0]["capture_month"] == "11"
    parsed = parse_sidecar_metadata(layout.extracted_dir / rows[0]["json_path"])
    assert parsed["latitude"] == 52.5
    assert parsed["description"] == "Berlin"


def test_smart_date_fallback_and_ignores_appledouble(tmp_path: Path):
    layout = WorkLayout(tmp_path / "G2S")
    layout.ensure_dirs()
    zpath = layout.takeout_dir / "t_smart.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("Takeout/Google Photos/Photos from 2021/._IMG_20210504_120000.jpg", b"junk")
        zf.writestr("Takeout/Google Photos/Photos from 2021/IMG_20210504_120000.jpg", b"px1")
        zf.writestr("Takeout/Google Photos/Photos from 2019/random_name.jpg", b"px2")
    db = ManifestDB(layout.manifest_db)
    db.init_schema()
    stats = scan_takeout(layout, db)
    assert stats["scanned"] == 2
    rows = {Path(r["source_path"]).name: r for r in db.get_by_status("scanned")}
    assert rows["IMG_20210504_120000.jpg"]["capture_year"] == "2021"
    assert rows["IMG_20210504_120000.jpg"]["capture_month"] == "05"
    assert rows["random_name.jpg"]["capture_year"] == "2019"
    assert rows["random_name.jpg"]["capture_month"] == "00"
