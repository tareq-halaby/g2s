import json
import zipfile
from pathlib import Path
from g2s.cli import main


def test_cli_full_pipeline_no_exiftool_fallback(tmp_path: Path):
    work = tmp_path / "G2S"
    dest = tmp_path / "NAS_Photos"
    assert main(["init", "--work-dir", str(work)]) == 0

    with zipfile.ZipFile(work / "takeout" / "t1.zip", "w") as zf:
        zf.writestr("Takeout/Google Photos/p1.jpg", b"img1")
        zf.writestr(
            "Takeout/Google Photos/p1.jpg.json",
            json.dumps({"photoTakenTime": {"timestamp": "1700000000"}}),
        )

    rc = main(["run", "--work-dir", str(work), "--dest", str(dest), "--no-exiftool"])
    assert rc == 0
    assert (dest / "2023" / "11" / "p1.jpg").read_bytes() == b"img1"
    assert "100% VERIFIED" in (work / "reports" / "audit_report.html").read_text(
        encoding="utf-8"
    )
