"""Command-line interface for G2S."""

from __future__ import annotations

import argparse
from pathlib import Path

from g2s.config import WorkLayout
from g2s.db import ManifestDB
from g2s.exif import ExifToolRunner, find_exiftool
from g2s.stage import stage_media
from g2s.takeout import scan_takeout
from g2s.transfer import transfer_to_nas
from g2s.ui import launch_ui
from g2s.verify import verify_nas, write_reports


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="g2s",
        description="100%-verified Google Photos Takeout to Synology NAS migrator",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_work_dir(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--work-dir",
            type=Path,
            default=Path("D:/G2S"),
            help="Working directory on a large drive (default: D:\\G2S)",
        )

    p_init = sub.add_parser("init", help="Create D:\\G2S directories and manifest DB")
    add_work_dir(p_init)

    p_scan = sub.add_parser("scan", help="Unpack Takeout zips and inventory media")
    add_work_dir(p_scan)

    p_stage = sub.add_parser("stage", help="Deduplicate, fix EXIF, and stage YYYY/MM")
    add_work_dir(p_stage)
    p_stage.add_argument(
        "--no-exiftool",
        action="store_true",
        help="Skip ExifTool metadata restoration (not recommended)",
    )

    p_transfer = sub.add_parser("transfer", help="Copy staged files to Synology SMB")
    add_work_dir(p_transfer)
    p_transfer.add_argument("--dest", type=Path, required=True, help="Synology SMB path")

    p_verify = sub.add_parser("verify", help="Verify SHA-256 on NAS and write report")
    add_work_dir(p_verify)

    p_run = sub.add_parser("run", help="Run full scan -> stage -> transfer -> verify")
    add_work_dir(p_run)
    p_run.add_argument("--dest", type=Path, required=True, help="Synology SMB path")
    p_run.add_argument("--no-exiftool", action="store_true", help="Skip ExifTool step")

    p_ui = sub.add_parser("ui", help="Launch local web dashboard in browser")
    add_work_dir(p_ui)
    p_ui.add_argument("--port", type=int, default=8765, help="Local port (default: 8765)")

    return parser


def _run_stage(layout: WorkLayout, db: ManifestDB, no_exiftool: bool) -> int:
    if no_exiftool:
        stats = stage_media(layout, db, exif_runner=None, on_progress=print)
        print(f"Stage complete: {stats}")
        return 0

    exif_path = find_exiftool(layout)
    if exif_path is None:
        print(
            f"ERROR: exiftool not found in {layout.tools_dir} or PATH. "
            "Place exiftool.exe in D:\\G2S\\tools\\ or pass --no-exiftool."
        )
        return 1

    with ExifToolRunner(exif_path, layout.tmp_dir) as runner:
        stats = stage_media(layout, db, exif_runner=runner, on_progress=print)
    print(f"Stage complete: {stats}")
    return 0


def _run_verify(layout: WorkLayout, db: ManifestDB) -> int:
    stats = verify_nas(layout, db, on_progress=print)
    html_path, csv_path = write_reports(layout, db)
    print(f"Verify complete: {stats}")
    print(f"Report: {html_path}")
    print(f"Issues CSV: {csv_path}")
    counts = db.summary_counts()
    unique_expected = counts["total"] - counts["duplicate_skipped"]
    passed = (
        counts["total"] > 0
        and counts["verified"] == unique_expected
        and counts["verify_failed"] == 0
    )
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    layout = WorkLayout(args.work_dir)
    layout.ensure_dirs()
    db = ManifestDB(layout.manifest_db)
    db.init_schema()

    if args.command == "init":
        print(f"Initialized G2S workspace at {layout.work_dir}")
        return 0

    if args.command == "scan":
        stats = scan_takeout(layout, db, on_progress=print)
        print(f"Scan complete: {stats}")
        return 0

    if args.command == "stage":
        return _run_stage(layout, db, args.no_exiftool)

    if args.command == "transfer":
        stats = transfer_to_nas(layout, db, args.dest, on_progress=print)
        print(f"Transfer complete: {stats}")
        return 0

    if args.command == "verify":
        return _run_verify(layout, db)

    if args.command == "run":
        scan_stats = scan_takeout(layout, db, on_progress=print)
        print(f"Scan complete: {scan_stats}")
        rc = _run_stage(layout, db, args.no_exiftool)
        if rc != 0:
            return rc
        t_stats = transfer_to_nas(layout, db, args.dest, on_progress=print)
        print(f"Transfer complete: {t_stats}")
        return _run_verify(layout, db)

    if args.command == "ui":
        launch_ui(work_dir=layout.work_dir, port=args.port)
        return 0

    return 1
