"""SHA-256 verification of NAS destination files and audit report generation."""

from __future__ import annotations

import csv
import datetime
import html
from pathlib import Path
from typing import Callable

from g2s.config import WorkLayout
from g2s.db import ManifestDB
from g2s.takeout import sha256_file


def verify_nas(
    layout: WorkLayout,
    db: ManifestDB,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Re-read every transferred/verified file on the NAS and check size + SHA-256."""
    rows = (
        db.get_by_status("transferred")
        + db.get_by_status("verify_failed")
        + db.get_by_status("verified")
    )
    verified = 0
    failed = 0

    for idx, row in enumerate(rows, start=1):
        dest_str = row.get("dest_path")
        if not dest_str:
            db.update_verify(row["id"], False, "Missing destination path")
            failed += 1
            continue

        dest = Path(dest_str)
        if not dest.is_file():
            db.update_verify(row["id"], False, "File missing on NAS")
            failed += 1
            continue

        actual_size = dest.stat().st_size
        if actual_size != row["staged_size"]:
            db.update_verify(
                row["id"],
                False,
                f"Size mismatch: expected {row['staged_size']}, got {actual_size}",
            )
            failed += 1
            continue

        actual_hash = sha256_file(dest)
        if actual_hash != row["staged_sha256"]:
            db.update_verify(row["id"], False, "SHA-256 mismatch")
            failed += 1
            continue

        db.update_verify(row["id"], True, None)
        verified += 1
        if on_progress and idx % 50 == 0:
            on_progress(f"Verified {idx}/{len(rows)} files on NAS...")

    return {"verified": verified, "failed": failed}


def write_reports(layout: WorkLayout, db: ManifestDB) -> tuple[Path, Path]:
    """Write audit_report.html and audit_issues.csv into layout.reports_dir."""
    layout.reports_dir.mkdir(parents=True, exist_ok=True)
    counts = db.summary_counts()
    issues = db.list_issues()

    unique_expected = counts["total"] - counts["duplicate_skipped"]
    all_passed = (
        counts["total"] > 0
        and counts["verified"] == unique_expected
        and counts["verify_failed"] == 0
        and counts["scanned"] == 0
        and counts["staged"] == 0
        and counts["transferred"] == 0
    )
    verdict = "100% VERIFIED" if all_passed else "VERIFICATION FAILED"
    badge_color = "#16a34a" if all_passed else "#dc2626"
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    issue_rows_html = "\n".join(
        f"<tr><td>{html.escape(str(r['source_path']))}</td>"
        f"<td>{html.escape(str(r['status']))}</td>"
        f"<td>{html.escape(str(r.get('json_path') or 'NONE'))}</td>"
        f"<td>{html.escape(str(r.get('error') or ''))}</td></tr>"
        for r in issues
    )

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>G2S Migration Audit Report</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #111827; }}
  .badge {{ display: inline-block; padding: 0.4rem 0.9rem; border-radius: 999px; color: #fff; background: {badge_color}; font-weight: 700; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1rem; margin: 1.5rem 0; }}
  .card {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem; background: #f9fafb; }}
  .card strong {{ display: block; font-size: 1.6rem; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; font-size: 0.9rem; }}
  th, td {{ border: 1px solid #e5e7eb; padding: 0.5rem; text-align: left; }}
  th {{ background: #f3f4f6; }}
</style>
</head>
<body>
  <h1>G2S Google Photos → Synology Audit Report</h1>
  <p><span class="badge">{verdict}</span> &nbsp; Generated: {generated_at}</p>
  <div class="grid">
    <div class="card"><span>Total in Takeout</span><strong>{counts['total']}</strong></div>
    <div class="card"><span>Verified on NAS</span><strong>{counts['verified']}</strong></div>
    <div class="card"><span>Duplicates Skipped</span><strong>{counts['duplicate_skipped']}</strong></div>
    <div class="card"><span>Failed / Pending</span><strong>{counts['verify_failed'] + counts['scanned'] + counts['staged'] + counts['transferred']}</strong></div>
  </div>
  <h2>Notes &amp; Issues ({len(issues)})</h2>
  <table>
    <thead><tr><th>Source Path</th><th>Status</th><th>JSON Sidecar</th><th>Error</th></tr></thead>
    <tbody>{issue_rows_html or '<tr><td colspan="4">None — every file verified!</td></tr>'}</tbody>
  </table>
</body>
</html>
"""
    html_path = layout.reports_dir / "audit_report.html"
    html_path.write_text(html_content, encoding="utf-8")

    csv_path = layout.reports_dir / "audit_issues.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "source_path", "status", "json_path", "capture_year", "error"])
        for r in issues:
            writer.writerow(
                [
                    r["id"],
                    r["source_path"],
                    r["status"],
                    r.get("json_path") or "",
                    r["capture_year"],
                    r.get("error") or "",
                ]
            )

    return html_path, csv_path
