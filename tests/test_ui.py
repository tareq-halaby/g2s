import json
import time
import urllib.request
import zipfile
from pathlib import Path
from g2s.config import WorkLayout
from g2s.db import ManifestDB
from g2s.ui import create_ui_server


def test_ui_server_status_and_scan_action(tmp_path: Path):
    work = tmp_path / "G2S"
    layout = WorkLayout(work)
    layout.ensure_dirs()
    ManifestDB(layout.manifest_db).init_schema()

    with zipfile.ZipFile(layout.takeout_dir / "t1.zip", "w") as zf:
        zf.writestr("Takeout/Google Photos/a.jpg", b"img")
        zf.writestr(
            "Takeout/Google Photos/a.jpg.json",
            json.dumps({"photoTakenTime": {"timestamp": "1700000000"}}),
        )

    server = create_ui_server(work_dir=work, host="127.0.0.1", port=0)
    port = server.server_address[1]
    import threading

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
            assert "G2S" in body
            assert "Test NAS Connection" in body
            assert "Start Migration" in body

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["counts"]["total"] == 0
            assert data["running"] is False
            assert data["takeout_zip_count"] == 1
            assert data["work_free_bytes"] > 0

        # Cleanup must be blocked before 100% verification
        req_clean = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/cleanup",
            data=json.dumps({"work_dir": str(work)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req_clean)
            assert False, "Expected 400 before verification"
        except urllib.error.HTTPError as exc:
            assert exc.code == 400

        # Test NAS connection endpoint (valid writable dir vs missing dir)
        nas_ok_dir = tmp_path / "NAS_OK"
        nas_ok_dir.mkdir()
        req_nas = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/test-nas",
            data=json.dumps({"dest": str(nas_ok_dir)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_nas) as resp:
            nas_res = json.loads(resp.read().decode("utf-8"))
            assert nas_res["ok"] is True

        req_bad = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/test-nas",
            data=json.dumps({"dest": str(tmp_path / "NO_SUCH_SHARE" / "Photos")}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_bad) as resp:
            bad_res = json.loads(resp.read().decode("utf-8"))
            assert bad_res["ok"] is False

        # QuickConnect URL returns clear guidance instead of cryptic path error
        req_qc = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/test-nas",
            data=json.dumps({"dest": "https://mynas.de6.quickconnect.to/"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_qc) as resp:
            qc_res = json.loads(resp.read().decode("utf-8"))
            assert qc_res["ok"] is False
            assert "QuickConnect" in qc_res["message"]

        # Auto-detect endpoint returns JSON list
        req_disc = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/discover-nas",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_disc) as resp:
            disc_res = json.loads(resp.read().decode("utf-8"))
            assert isinstance(disc_res["targets"], list)

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/action",
            data=json.dumps({"action": "scan", "work_dir": str(work)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 202

        for _ in range(40):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if not data["running"] and data["counts"]["scanned"] == 1:
                    break
            time.sleep(0.05)
        assert data["counts"]["scanned"] == 1
    finally:
        server.shutdown()
        server.server_close()
