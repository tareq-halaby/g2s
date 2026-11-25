# G2S: 100%-Verified Google Photos → Synology DS216play Migrator

**Date:** 2026-11-25  
**Target NAS:** Synology DS216play (`DSM 7.3.2-86009 Update 6`, ARMv7 `STiH412`, 1 GB RAM, LAN `192.168.1.100`)  
**Host PC:** Windows (Python 3.13), `C:` (~42 GB free — code only), `D:` (~416 GB free — all data, staging, temp, and logs)

---

## 1. Goal & Non-Goals

### Goal
Provide a resumable, local Windows CLI tool (`g2s`) that migrates a one-time **Google Takeout** photo/video export to **Synology Photos** over LAN SMB and produces **cryptographic proof (SHA-256 + file count + EXIF date audit)** that 100% of media files arrived intact on the NAS before anything is deleted from Google Photos.

### Non-Goals
- Ongoing two-way or scheduled cloud sync (this is a one-time migration).
- Running Docker or heavy scripts on the DS216play itself (1 GB RAM / ARMv7).
- Recreating Google Photos virtual albums via undocumented Synology APIs (Approach 1: clean `YYYY/MM` chronological folders for Synology Photos).

---

## 2. Approaches Considered

1. **Approach 1: Local Manifest + ExifTool Metadata Fix + SMB Copy + SHA-256 Audit *(Selected)***  
   Fastest LAN transfer, zero undocumented API fragility, and true byte-for-byte SHA-256 verification on the NAS disk.
2. **Approach 2: Synology Photos DSM 7 HTTP API Uploader**  
   Slower over HTTP, relies on undocumented `SYNO.Foto.*` endpoints, and cannot directly SHA-256-verify files on disk.
3. **Approach 3: Hybrid (SMB + Optional API Album Pass)**  
   Adds DSM auth/2FA complexity for virtual albums; not needed here.

---

## 3. Storage Layout (Zero Heavy Writes on `C:`)

All source archives, temporary extraction, staged files, SQLite state, and reports live under `D:\G2S\` (configurable via `--work-dir`, defaulting to `D:\G2S`):

```text
D:\G2S\
├── takeout\          # User places Google Takeout .zip files (or extracted folders) here
├── extracted\        # Unpacked Takeout contents (cleaned/optional after staging)
├── staging\          # EXIF-restored media organized as YYYY\MM\<filename>
├── state\
│   └── manifest.db   # SQLite ledger tracking every file's lifecycle & hashes
├── tmp\              # Subprocess TEMP/TMP dir so ExifTool/Python never fill C:
├── tools\            # Local exiftool.exe if not installed globally
└── reports\          # audit_report.html and audit_failures.csv
```

The Python package itself lives in `c:\Users\me\Desktop\G2S\`.

---

## 4. Pipeline Architecture (`python -m g2s <command>`)

Each stage is idempotent and resumable via `D:\G2S\state\manifest.db`:

### Stage 1: `g2s scan`
- Unpacks any `.zip` files in `D:\G2S\takeout\` into `D:\G2S\extracted\` (streaming with `TMP=D:\G2S\tmp`, skipping already-extracted archives).
- Walks `D:\G2S\extracted\` and inventories every **media file** (`.jpg`, `.jpeg`, `.png`, `.heic`, `.webp`, `.gif`, `.raw`, `.dng`, `.mp4`, `.mov`, `.m4v`, `.avi`, `.3gp`, etc.), ignoring `.json` sidecars and non-media junk.
- Computes `raw_sha256` and `raw_size` for each media file.
- Resolves the matching Google Takeout `.json` sidecar using Google's known naming rules:
  1. `<filename>.json` / `<filename>.supplemental-metadata.json`
  2. Truncated filename variants (Google truncates long names at ~46–51 chars before appending `.json`)
  3. `-edited` / localized edited suffix fallback (e.g. `IMG_1234-edited.jpg` → `IMG_1234.jpg.json`)
  4. Numbered duplicate variants (e.g. `IMG_1234(1).jpg` → `IMG_1234.jpg(1).json`)
- Stores each item in `manifest.db` (`status = 'scanned'`).

### Stage 2: `g2s stage`
- Reads `scanned` items from `manifest.db`.
- Copies each media file to `D:\G2S\staging\YYYY\MM\<filename>` (using capture date from JSON `photoTakenTime`, falling back to existing EXIF `DateTimeOriginal`, then file mtime, or `UnknownDate` if none).
- Handles filename collisions deterministically (e.g., if `photo.jpg` already exists with a different hash, appends `_2`, `_3`; if same `raw_sha256`, marks as `duplicate_skipped` and links to the canonical file so it's accounted for in the 100% audit).
- Runs **ExifTool in `-stay_open` batch mode** on staged files to embed:
  - `DateTimeOriginal`, `CreateDate`, `ModifyDate` (and QuickTime `CreateDate` for videos)
  - GPS coordinates (`GPSLatitude`, `GPSLongitude`, `GPSAltitude`) when non-zero
  - `ImageDescription` / `Caption-Abstract` from JSON `description`
- Computes **`staged_sha256`** and **`staged_size`** after ExifTool finishes, and sets `status = 'staged'`.

### Stage 3: `g2s transfer --dest "\\192.168.1.100\home\Photos\GooglePhotos"`
- Copies each `staged` file to the Synology SMB destination preserving `YYYY\MM\<filename>`.
- Writes to `<filename>.g2s_tmp` first, then atomically renames to `<filename>` so interrupted transfers never leave partial files.
- Updates `dest_path` and `status = 'transferred'`.

### Stage 4: `g2s verify`
- Re-reads every `transferred` (or `staged`) file at `dest_path` on the Synology NAS over SMB.
- Checks: file exists, `dest_size == staged_size`, and **`dest_sha256 == staged_sha256`**.
- Marks matching files `status = 'verified'` (or `verify_failed` with error reason).
- Generates `D:\G2S\reports\audit_report.html` and `D:\G2S\reports\audit_issues.csv`:
  - **100% Pass Criteria:** `scanned_unique_media == verified_on_nas` AND `failed_count == 0`.
  - Lists every `duplicate_skipped`, `unmatched_json`, `missing_date`, or `verify_failed` item explicitly.

---

## 5. Tech Stack & Dependencies
- **Python 3.13** (already installed) — standard library (`sqlite3`, `zipfile`, `hashlib`, `pathlib`, `json`, `shutil`, `subprocess`) + minimal packages (`pytest` for tests).
- **ExifTool** (placed in `D:\G2S\tools\exiftool.exe` if not on PATH).
- **Git** (already installed) for version control in `c:\Users\me\Desktop\G2S`.
