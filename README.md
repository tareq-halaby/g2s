# G2S — 100% Verified Google Photos → Synology NAS Migrator

A simple, open-source, **zero-dependency** Python tool (with a built-in local **Web UI**) to migrate your **Google Takeout** photo & video library to a **Synology NAS** (including ARM/low-RAM models like **DS216play**) and **prove 100% of your files arrived intact** via SHA-256 verification before you delete anything from Google Photos.

---

## Why G2S?
- **No Docker or NAS scripts required:** Runs on your Windows/Mac/Linux PC and copies over LAN SMB to Synology Photos (`/home/Photos` or `/photo`).
- **Protects small `C:` drives:** All Takeout zips, extracted files, staging, temp files (`TMP`/`TEMP`), SQLite state, and reports default to **`D:\G2S\`**.
- **Fixes Google Takeout metadata:** Uses `ExifTool` in fast batch mode to embed capture dates, GPS coordinates, and descriptions from `.json` sidecars (including `.supplemental-metadata.json`, truncated filenames, `-edited`, and `(1)` duplicates) into `YYYY/MM/` folders.
- **Resumable & atomic:** Tracks every file in SQLite (`D:\G2S\state\manifest.db`). Interrupted transfers use `.g2s_tmp` and never leave half-written files.
- **100% SHA-256 Audit Report:** Re-reads every file on the NAS after transfer and generates `audit_report.html` + `audit_issues.csv`.

---

## Quick Start (Easiest: Web UI)

1. **Requirements:** Python 3.11+ and [ExifTool](https://exiftool.org/) (`exiftool.exe` placed in `D:\G2S\tools\exiftool.exe` or on your `PATH`).
2. **Export from Google Photos:** Go to [takeout.google.com](https://takeout.google.com), select **Google Photos**, set archive size to **50 GB**, and save the `.zip` files into **`D:\G2S\takeout\`**.
3. **Launch the Web UI:**
   - Double-click **`launch_ui.bat`** (Windows), or run:
     ```bash
     PYTHONPATH=src python -m g2s ui --work-dir D:\G2S
     ```
4. Click **Auto-Detect NAS** (or enter your Synology IP/SMB path, e.g. `\\192.168.1.100\home\Photos\GooglePhotos`) and click **Start Migration & Verify 100%**.
5. When finished, click **Open Audit Report** and confirm the green **`100% VERIFIED`** badge.

---

## CLI Usage

```bash
# 1. Create D:\G2S folders and manifest.db
PYTHONPATH=src python -m g2s init --work-dir D:\G2S

# 2. Run the full pipeline (scan -> stage -> transfer -> verify)
PYTHONPATH=src python -m g2s run --work-dir D:\G2S --dest "\\192.168.1.100\home\Photos\GooglePhotos"

# Or run individual resumable steps:
PYTHONPATH=src python -m g2s scan --work-dir D:\G2S
PYTHONPATH=src python -m g2s stage --work-dir D:\G2S
PYTHONPATH=src python -m g2s transfer --work-dir D:\G2S --dest "\\192.168.1.100\home\Photos\GooglePhotos"
PYTHONPATH=src python -m g2s verify --work-dir D:\G2S
```

---

## Development & Tests

```bash
python -m pytest -v
```

Licensed under the [MIT License](LICENSE).
