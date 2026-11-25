# G2S: 100%-Verified Google Photos → Synology DS216play Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable Windows CLI (`g2s`) that unpacks Google Takeout archives on `D:\G2S\`, restores EXIF metadata from `.json` sidecars via ExifTool, transfers files atomically over SMB to Synology Photos, and produces a SHA-256-verified 100% audit report.

**Architecture:** Five focused modules under `src/g2s/` (`config`, `db`, `takeout`, `exif`/`stage`, `transfer`/`verify`, `cli`) backed by a SQLite ledger (`D:\G2S\state\manifest.db`). Every stage is idempotent and resumable, and all data/temp/log directories default to `D:\G2S\` so `C:` is never used for media storage.

**Tech Stack:** Python 3.13 (stdlib `sqlite3`, `zipfile`, `hashlib`, `pathlib`, `json`, `shutil`, `subprocess`, `argparse`, `csv`, `html`), `pytest` 9.0.3, ExifTool (`D:\G2S\tools\exiftool.exe` or PATH).

**Spec:** [2026-11-25-g2s-migrator-design.md](file:///c:/Users/me/Desktop/G2S/docs/superpowers/specs/2026-11-25-g2s-migrator-design.md)

## Global Constraints

- Code lives in `c:\Users\me\Desktop\G2S`; all working data (`takeout`, `extracted`, `staging`, `state`, `tmp`, `tools`, `reports`) defaults to `D:\G2S\`.
- Python 3.13+; zero third-party runtime dependencies required (stdlib only, plus `ExifTool` binary).
- All subprocesses (including ExifTool) must have `TMP` and `TEMP` pinned to `<work_dir>/tmp` so `C:` is never filled.
- Every media file in Takeout must end in a terminal accounted state (`verified` or `duplicate_skipped`) for a 100% PASS audit.

## Review Focus

1. **Corrupted/partial `.zip` in `takeout/`:** `extract_archives` raises a clear error naming the archive and does not record it as extracted, allowing clean retry.
2. **Google Takeout sidecar quirks:** `find_sidecar_json` matches `.supplemental-metadata.json`, `.json`, ~46-char truncated stems, `-edited` stripped stems, and `name(1).ext` → `name.ext(1).json`.
3. **Filename collisions with different content:** `stage_media` appends `_2`, `_3` when `raw_sha256` differs, and marks identical `raw_sha256` files as `duplicate_skipped` with `duplicate_of`.
4. **Interrupted SMB transfers:** `transfer_to_nas` writes to `<dest>.g2s_tmp` and atomically replaces `<dest>`, safely overwriting stale `.g2s_tmp` on resume.
5. **Zero `C:` temp leakage:** `ExifToolRunner` explicitly overrides `TMP` and `TEMP` in `subprocess.Popen` env to `layout.tmp_dir`.

---

### Task 1: Project Scaffolding, `WorkLayout`, and `ManifestDB`

**Files:**
- Create: `pyproject.toml`
- Create: `src/g2s/__init__.py`
- Create: `src/g2s/config.py`
- Create: `src/g2s/db.py`
- Test: `tests/test_config_db.py`

**Interfaces:**
- Produces:
  - `WorkLayout(work_dir: Path = Path("D:/G2S"))` with properties `takeout_dir`, `extracted_dir`, `staging_dir`, `state_dir`, `manifest_db`, `tmp_dir`, `tools_dir`, `reports_dir`, and `ensure_dirs() -> None`
  - `MEDIA_EXTENSIONS: frozenset[str]`
  - `ManifestDB(db_path: Path)` with methods `init_schema()`, `is_archive_extracted(name: str) -> bool`, `mark_archive_extracted(name: str, size: int)`, `upsert_scanned(...) -> int`, `get_by_status(status: str) -> list[dict]`, `find_canonical_by_raw_hash(raw_sha256: str) -> dict | None`, `update_stage(...)`, `update_transfer(...)`, `update_verify(...)`, `summary_counts() -> dict[str, int]`, `list_issues() -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from g2s.config import WorkLayout, MEDIA_EXTENSIONS
from g2s.db import ManifestDB

def test_work_layout_defaults_to_d_drive(tmp_path: Path):
    default = WorkLayout()
    assert default.work_dir == Path("D:/G2S")
    custom = WorkLayout(tmp_path / "G2S")
    custom.ensure_dirs()
    for d in (
        custom.takeout_dir, custom.extracted_dir, custom.staging_dir,
        custom.state_dir, custom.tmp_dir, custom.tools_dir, custom.reports_dir,
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
        source_path="a/IMG_1.jpg", raw_sha256="abc", raw_size=100,
        json_path="a/IMG_1.jpg.json", capture_year="2024", capture_month="05",
    )
    assert db.find_canonical_by_raw_hash("abc") is None
    db.update_stage(row_id, staged_path="2024/05/IMG_1.jpg", staged_sha256="def", staged_size=110)
    assert db.find_canonical_by_raw_hash("abc")["id"] == row_id
    db.update_transfer(row_id, dest_path="\\\\nas\\photo\\2024\\05\\IMG_1.jpg")
    db.update_verify(row_id, verified=True, error=None)
    assert db.summary_counts()["verified"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'g2s'`

- [ ] **Step 3: Initialize git, create `pyproject.toml`, `src/g2s/__init__.py`, `src/g2s/config.py`, and `src/g2s/db.py`**

Create `pyproject.toml` with `src` layout and `g2s` console script; implement `WorkLayout` and `ManifestDB` with `sqlite3` (`row_factory = sqlite3.Row`, `archives` and `media_files` tables).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config_db.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git init
git add pyproject.toml src/g2s/__init__.py src/g2s/config.py src/g2s/db.py tests/test_config_db.py docs/
git commit -m "feat: add project scaffold, WorkLayout (D:\\G2S), and ManifestDB"
```

---

### Task 2: Takeout Extraction, Sidecar JSON Matching, and `scan_takeout`

**Files:**
- Create: `src/g2s/takeout.py`
- Test: `tests/test_takeout.py`

**Interfaces:**
- Consumes: `WorkLayout`, `MEDIA_EXTENSIONS`, `ManifestDB`
- Produces:
  - `sha256_file(path: Path) -> str`
  - `extract_archives(layout: WorkLayout, db: ManifestDB) -> list[str]`
  - `find_sidecar_json(media_path: Path) -> Path | None`
  - `parse_sidecar_metadata(json_path: Path) -> dict` (keys: `timestamp: int | None`, `latitude: float | None`, `longitude: float | None`, `altitude: float | None`, `description: str | None`)
  - `scan_takeout(layout: WorkLayout, db: ManifestDB) -> dict[str, int]`

- [ ] **Step 1: Write the failing test**

```python
import json, zipfile
from pathlib import Path
import pytest
from g2s.config import WorkLayout
from g2s.db import ManifestDB
from g2s.takeout import extract_archives, find_sidecar_json, parse_sidecar_metadata, scan_takeout

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
    meta = {"photoTakenTime": {"timestamp": "1700000000"}, "geoData": {"latitude": 52.5, "longitude": 13.4, "altitude": 0.0}, "description": "Berlin"}
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_takeout.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'g2s.takeout'`

- [ ] **Step 3: Implement `src/g2s/takeout.py`**

Implement `sha256_file`, `extract_archives` (validating zip and extracting into `layout.extracted_dir`), `find_sidecar_json` (covering `.supplemental-metadata.json`, `.json`, `-edited` stripping, `stem(N).ext` → `stem.ext(N).json`, and 46–51 char truncation), `parse_sidecar_metadata`, and `scan_takeout`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_takeout.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/g2s/takeout.py tests/test_takeout.py
git commit -m "feat: add Takeout archive extraction, sidecar matching, and media scanner"
```

---

### Task 3: ExifTool Batch Runner and `stage_media`

**Files:**
- Create: `src/g2s/exif.py`
- Create: `src/g2s/stage.py`
- Test: `tests/test_stage.py`

**Interfaces:**
- Consumes: `WorkLayout`, `ManifestDB`, `parse_sidecar_metadata`, `sha256_file`
- Produces:
  - `find_exiftool(layout: WorkLayout) -> Path | None`
  - `ExifToolRunner(exiftool_path: Path, tmp_dir: Path)` (context manager with `apply_metadata(file_path: Path, meta: dict) -> None` using `-stay_open True` and `TMP`/`TEMP` pinned to `tmp_dir`)
  - `stage_media(layout: WorkLayout, db: ManifestDB, exif_runner: ExifToolRunner | None = None) -> dict[str, int]`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path
from g2s.config import WorkLayout
from g2s.db import ManifestDB
from g2s.exif import ExifToolRunner
from g2s.stage import stage_media

class FakeExifRunner:
    def __init__(self):
        self.calls = []
    def apply_metadata(self, file_path: Path, meta: dict) -> None:
        self.calls.append((file_path, meta))
        file_path.write_bytes(file_path.read_bytes() + b"_EXIF")

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

    db.upsert_scanned(str(f1.relative_to(layout.extracted_dir)), "h_same", 4, str(j1.relative_to(layout.extracted_dir)), "2023", "11")
    db.upsert_scanned(str(f2.relative_to(layout.extracted_dir)), "h_same", 4, None, "2023", "11")
    db.upsert_scanned(str(f3.relative_to(layout.extracted_dir)), "h_diff", 9, None, "2023", "11")

    fake = FakeExifRunner()
    stats = stage_media(layout, db, exif_runner=fake)
    assert stats["staged"] == 2
    assert stats["duplicate_skipped"] == 1
    assert (layout.staging_dir / "2023" / "11" / "IMG.jpg").exists()
    assert (layout.staging_dir / "2023" / "11" / "IMG_2.jpg").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_stage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'g2s.exif'`

- [ ] **Step 3: Implement `src/g2s/exif.py` and `src/g2s/stage.py`**

Implement `find_exiftool` (checks `layout.tools_dir / "exiftool.exe"` then `shutil.which("exiftool")`), `ExifToolRunner` (`-stay_open True -@ -`, `_build_env` pinning `TMP`/`TEMP` to `tmp_dir`), and `stage_media` (deduplication by `raw_sha256`, collision-safe `YYYY/MM` naming, ExifTool application, and `staged_sha256` computation).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_stage.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/g2s/exif.py src/g2s/stage.py tests/test_stage.py
git commit -m "feat: add ExifTool batch runner (D: tmp) and deduplicating stager"
```

---

### Task 4: Atomic SMB Transfer, SHA-256 NAS Verification, and Audit Reports

**Files:**
- Create: `src/g2s/transfer.py`
- Create: `src/g2s/verify.py`
- Test: `tests/test_transfer_verify.py`

**Interfaces:**
- Consumes: `WorkLayout`, `ManifestDB`, `sha256_file`
- Produces:
  - `transfer_to_nas(layout: WorkLayout, db: ManifestDB, dest_root: Path) -> dict[str, int]`
  - `verify_nas(layout: WorkLayout, db: ManifestDB) -> dict[str, int]`
  - `write_reports(layout: WorkLayout, db: ManifestDB) -> tuple[Path, Path]` (returns `(html_path, csv_path)`)

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_transfer_verify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'g2s.transfer'`

- [ ] **Step 3: Implement `src/g2s/transfer.py` and `src/g2s/verify.py`**

Implement atomic `.g2s_tmp` → `os.replace` copy in `transfer_to_nas`, SHA-256/size verification in `verify_nas`, and HTML + CSV report generation in `write_reports`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_transfer_verify.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/g2s/transfer.py src/g2s/verify.py tests/test_transfer_verify.py
git commit -m "feat: add atomic SMB transfer, SHA-256 NAS verification, and audit reports"
```

---

### Task 5: CLI Entry Point (`python -m g2s`) & End-to-End Test

**Files:**
- Create: `src/g2s/cli.py`
- Create: `src/g2s/__main__.py`
- Create: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `WorkLayout`, `ManifestDB`, `scan_takeout`, `stage_media`, `find_exiftool`, `ExifToolRunner`, `transfer_to_nas`, `verify_nas`, `write_reports`
- Produces:
  - `main(argv: list[str] | None = None) -> int` supporting `init`, `scan`, `stage`, `transfer --dest <path>`, `verify`, `run --dest <path>` (all accepting `--work-dir`, defaulting to `D:\G2S`)

- [ ] **Step 1: Write the failing test**

```python
import json, zipfile
from pathlib import Path
from g2s.cli import main

def test_cli_full_pipeline_no_exiftool_fallback(tmp_path: Path):
    work = tmp_path / "G2S"
    dest = tmp_path / "NAS_Photos"
    assert main(["init", "--work-dir", str(work)]) == 0

    with zipfile.ZipFile(work / "takeout" / "t1.zip", "w") as zf:
        zf.writestr("Takeout/Google Photos/p1.jpg", b"img1")
        zf.writestr("Takeout/Google Photos/p1.jpg.json", json.dumps({"photoTakenTime": {"timestamp": "1700000000"}}))

    rc = main(["run", "--work-dir", str(work), "--dest", str(dest), "--no-exiftool"])
    assert rc == 0
    assert (dest / "2023" / "11" / "p1.jpg").read_bytes() == b"img1"
    assert "100% VERIFIED" in (work / "reports" / "audit_report.html").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'g2s.cli'`

- [ ] **Step 3: Implement `src/g2s/cli.py`, `src/g2s/__main__.py`, and `README.md`**

Implement `argparse` CLI with `init`, `scan`, `stage`, `transfer`, `verify`, `run` (returning exit code `0` on 100% pass, `1` on verification failure or missing ExifTool unless `--no-exiftool` is passed), and document usage in `README.md`.

- [ ] **Step 4: Run full test suite to verify all tests pass**

Run: `python -m pytest -v`
Expected: PASS (all tests across all 5 test files)

- [ ] **Step 5: Commit**

```bash
git add src/g2s/cli.py src/g2s/__main__.py README.md tests/test_cli.py
git commit -m "feat: add g2s CLI and README for D:\\G2S -> Synology verified migration"
```
