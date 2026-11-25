"""Local web UI for G2S (zero external dependencies, stdlib http.server)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from g2s.config import WorkLayout
from g2s.db import ManifestDB
from g2s.discover import discover_synology_targets, normalize_nas_input
from g2s.exif import ExifToolRunner, find_exiftool
from g2s.stage import stage_media
from g2s.takeout import scan_takeout
from g2s.transfer import transfer_to_nas
from g2s.verify import verify_nas, write_reports

_HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>G2S — Google Photos to Synology</title>
<style>
  :root {
    --bg: #0b1120; --card: #131c31; --panel: #0f172a; --border: #23304c;
    --text: #f1f5f9; --muted: #94a3b8; --accent: #38bdf8;
    --ok: #22c55e; --warn: #f59e0b; --err: #ef4444;
  }
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 2rem 1rem; line-height: 1.45; }
  .wrap { max-width: 860px; margin: 0 auto; }
  h1 { margin: 0 0 0.25rem; font-size: 1.7rem; letter-spacing: -0.02em; }
  .sub { color: var(--muted); margin-bottom: 1.5rem; font-size: 0.95rem; }
  .card { background: var(--card); border-radius: 14px; padding: 1.25rem 1.4rem; margin-bottom: 1rem; border: 1px solid var(--border); }
  .card h2 { margin: 0 0 0.85rem; font-size: 1.05rem; font-weight: 600; }
  .step { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 0.8rem 0.9rem; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 0.65rem; flex-wrap: wrap; }
  .step:last-child { margin-bottom: 0; }
  .step-info { flex: 1; min-width: 240px; }
  .step-title { font-weight: 600; font-size: 0.95rem; display: flex; align-items: center; gap: 0.5rem; }
  .step-desc { color: var(--muted); font-size: 0.83rem; margin-top: 0.2rem; }
  .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; background: var(--warn); flex-shrink: 0; }
  .dot.ok { background: var(--ok); }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.9rem; margin-top: 0.75rem; }
  @media (max-width: 680px) { .row { grid-template-columns: 1fr; } }
  label { display: block; font-size: 0.82rem; color: var(--muted); margin-bottom: 0.3rem; }
  input[type="text"], input:not([type]) { width: 100%; padding: 0.55rem 0.75rem; border-radius: 8px; border: 1px solid #334155; background: var(--panel); color: var(--text); font-family: ui-monospace, monospace; font-size: 0.85rem; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 0.65rem; }
  .stat { background: var(--panel); padding: 0.7rem 0.8rem; border-radius: 10px; border: 1px solid var(--border); }
  .stat span { font-size: 0.75rem; color: var(--muted); display: block; }
  .stat strong { font-size: 1.35rem; }
  .bar-bg { height: 8px; background: var(--panel); border-radius: 999px; overflow: hidden; margin: 1rem 0 0.75rem; border: 1px solid var(--border); }
  .bar-fill { height: 100%; width: 0%; background: linear-gradient(90deg, var(--accent), var(--ok)); transition: width 0.3s ease; }
  .actions { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center; }
  button, a.btn { padding: 0.6rem 1rem; border-radius: 8px; border: none; font-weight: 600; cursor: pointer; text-decoration: none; font-size: 0.88rem; display: inline-flex; align-items: center; gap: 0.4rem; }
  button.primary { background: var(--accent); color: #082f49; padding: 0.75rem 1.35rem; font-size: 0.95rem; }
  button.secondary { background: #26344f; color: var(--text); }
  button:disabled { opacity: 0.45; cursor: not-allowed; }
  a.btn-ok { background: var(--ok); color: #052e16; display: none; }
  a.btn-link { background: #26344f; color: var(--text); }
  .banner-ok { display: none; background: rgba(34,197,94,0.14); border: 1px solid rgba(34,197,94,0.45); color: #bbf7d0; padding: 0.85rem 1rem; border-radius: 10px; margin-bottom: 0.9rem; font-size: 0.92rem; }
  .nas-msg { font-size: 0.82rem; margin-top: 0.35rem; min-height: 1.1em; }
  details { margin-top: 0.85rem; }
  summary { cursor: pointer; color: var(--muted); font-size: 0.83rem; user-select: none; }
  pre { background: #020617; padding: 0.8rem; border-radius: 8px; height: 180px; overflow: auto; font-size: 0.8rem; color: #cbd5e1; margin: 0.5rem 0 0; border: 1px solid var(--border); }
</style>
</head>
<body>
<div class="wrap">
  <h1>G2S: Google Photos &rarr; Synology NAS</h1>
  <div class="sub">Simple, 100% SHA-256 verified one-time migration &middot; All working files stay on <code>D:\\G2S</code></div>

  <div class="card">
    <h2>Before You Start (3 Quick Checks)</h2>

    <div class="step">
      <div class="step-info">
        <div class="step-title"><span id="dotExif" class="dot"></span> 1. ExifTool (restores original photo dates &amp; GPS)</div>
        <div id="descExif" class="step-desc">Checking...</div>
      </div>
      <div class="actions">
        <a class="btn btn-link" href="https://exiftool.org/" target="_blank">Download ExifTool</a>
        <button class="secondary" onclick="openFolder('tools')">Open tools folder</button>
      </div>
    </div>

    <div class="step">
      <div class="step-info">
        <div class="step-title"><span id="dotTakeout" class="dot"></span> 2. Google Takeout .zip Files</div>
        <div id="descTakeout" class="step-desc">Checking...</div>
      </div>
      <div class="actions">
        <a class="btn btn-link" href="https://takeout.google.com/" target="_blank">Open Google Takeout</a>
        <button class="secondary" onclick="openFolder('takeout')">Open takeout folder</button>
      </div>
    </div>

    <div class="step">
      <div class="step-info">
        <div class="step-title"><span id="dotNas" class="dot"></span> 3. Synology NAS Folder</div>
        <div class="step-desc">Enter an IP (<code>192.168.1.100</code>), hostname (<code>DiskStation</code>), mapped drive (<code>Z:\\Photos</code>), or click Auto-Detect.</div>
      </div>
      <div class="actions">
        <button class="secondary" onclick="discoverNas()">Auto-Detect NAS</button>
        <button class="secondary" onclick="testNas()">Test NAS Connection</button>
      </div>
    </div>

    <div id="nasChoices" class="actions" style="margin-bottom:0.5rem;"></div>

    <div class="row">
      <div>
        <label>Work Folder (on D: drive)</label>
        <input id="workDir" value="__WORK_DIR__">
      </div>
      <div>
        <label>Synology NAS Destination (IP, Hostname, Drive, or SMB Path)</label>
        <input id="destDir" placeholder="\\\\192.168.1.100\\home\\Photos\\GooglePhotos">
        <div id="nasMsg" class="nas-msg"></div>
      </div>
    </div>
  </div>

  <div class="card">
    <div id="verifiedBanner" class="banner-ok">
      <strong>100% VERIFIED:</strong> Every unique photo &amp; video from Google Takeout is confirmed byte-for-byte on your Synology NAS.
    </div>

    <div class="stats">
      <div class="stat"><span>Total in Takeout</span><strong id="cTotal">0</strong></div>
      <div class="stat"><span>Scanned</span><strong id="cScanned">0</strong></div>
      <div class="stat"><span>Staged</span><strong id="cStaged">0</strong></div>
      <div class="stat"><span>Duplicates Skipped</span><strong id="cDup">0</strong></div>
      <div class="stat"><span>Transferred</span><strong id="cTrans">0</strong></div>
      <div class="stat"><span>Verified 100%</span><strong id="cVer" style="color:var(--ok)">0</strong></div>
      <div class="stat"><span>Failed</span><strong id="cFail" style="color:var(--err)">0</strong></div>
    </div>

    <div class="bar-bg"><div id="barFill" class="bar-fill"></div></div>

    <div class="actions">
      <button class="primary" onclick="runAction('run')">Start Migration &amp; Verify 100%</button>
      <a id="reportLink" class="btn btn-ok" href="/report" target="_blank">Open Audit Report</a>
      <button id="cleanupBtn" class="secondary" style="display:none;" onclick="cleanupTemp()">Reclaim Local Temp Space</button>
      <label style="display:flex; align-items:center; gap:0.4rem; margin:0 0 0 auto; cursor:pointer;">
        <input type="checkbox" id="noExif"> Skip ExifTool
      </label>
    </div>
    <div id="spaceInfo" class="step-desc" style="margin-top:0.5rem;"></div>

    <details>
      <summary>Advanced: Run individual steps</summary>
      <div class="actions" style="margin-top:0.6rem;">
        <button class="secondary" onclick="runAction('scan')">1. Scan Takeout</button>
        <button class="secondary" onclick="runAction('stage')">2. Fix EXIF &amp; Stage</button>
        <button class="secondary" onclick="runAction('transfer')">3. Transfer to NAS</button>
        <button class="secondary" onclick="runAction('verify')">4. Verify 100%</button>
      </div>
    </details>
  </div>

  <div class="card">
    <label>Activity Log <span id="runState"></span></label>
    <pre id="logs"></pre>
  </div>
</div>

<script>
async function refresh() {
  const workDir = encodeURIComponent(document.getElementById('workDir').value);
  const res = await fetch('/api/status?work_dir=' + workDir);
  const d = await res.json();

  document.getElementById('cTotal').textContent = d.counts.total;
  document.getElementById('cScanned').textContent = d.counts.scanned;
  document.getElementById('cStaged').textContent = d.counts.staged;
  document.getElementById('cDup').textContent = d.counts.duplicate_skipped;
  document.getElementById('cTrans').textContent = d.counts.transferred;
  document.getElementById('cVer').textContent = d.counts.verified;
  document.getElementById('cFail').textContent = d.counts.verify_failed;

  const dotExif = document.getElementById('dotExif');
  const descExif = document.getElementById('descExif');
  if (d.exiftool_found) {
    dotExif.className = 'dot ok';
    descExif.textContent = 'Ready! ExifTool is installed and will restore dates & GPS.';
  } else {
    dotExif.className = 'dot';
    descExif.textContent = 'Place exiftool.exe inside ' + d.work_dir + '\\\\tools\\\\ (or check "Skip ExifTool").';
  }

  const dotTakeout = document.getElementById('dotTakeout');
  const descTakeout = document.getElementById('descTakeout');
  if (d.takeout_zip_count > 0) {
    dotTakeout.className = 'dot ok';
    const gb = (d.takeout_zip_bytes / (1024 * 1024 * 1024)).toFixed(2);
    descTakeout.textContent = 'Ready! Found ' + d.takeout_zip_count + ' .zip file(s) (' + gb + ' GB).';
  } else {
    dotTakeout.className = 'dot';
    descTakeout.textContent = 'Export Google Photos (50 GB zips) and put them in ' + d.work_dir + '\\\\takeout\\\\.';
  }

  const uniqueExpected = Math.max(0, d.counts.total - d.counts.duplicate_skipped);
  const pct = uniqueExpected > 0 ? Math.round((d.counts.verified / uniqueExpected) * 100) : 0;
  document.getElementById('barFill').style.width = pct + '%';

  const allPassed = d.counts.total > 0 && d.counts.verified === uniqueExpected && d.counts.verify_failed === 0 && !d.running;
  document.getElementById('verifiedBanner').style.display = allPassed ? 'block' : 'none';
  document.getElementById('cleanupBtn').style.display = allPassed ? 'inline-flex' : 'none';
  const freeGb = (d.work_free_bytes / (1024 * 1024 * 1024)).toFixed(1);
  document.getElementById('spaceInfo').textContent = 'Free space on work drive: ' + freeGb + ' GB';

  document.getElementById('runState').textContent = d.running ? '(Working...)' : '(Idle)';
  document.querySelectorAll('button').forEach(b => b.disabled = d.running);
  document.getElementById('reportLink').style.display = d.report_exists ? 'inline-flex' : 'none';

  const pre = document.getElementById('logs');
  pre.textContent = d.logs.join('\\n');
  pre.scrollTop = pre.scrollHeight;
}

async function discoverNas() {
  const box = document.getElementById('nasChoices');
  box.innerHTML = '<span class="step-desc">Scanning local network for Synology NAS...</span>';
  const res = await fetch('/api/discover-nas', { method: 'POST', body: '{}' });
  const d = await res.json();
  if (!d.targets.length) {
    box.innerHTML = '<span class="step-desc">No Synology SMB shares auto-detected. Enter your NAS IP (e.g. 192.168.1.100) below.</span>';
    return;
  }
  box.innerHTML = '';
  d.targets.forEach(t => {
    const btn = document.createElement('button');
    btn.className = 'secondary';
    btn.textContent = t.label;
    btn.onclick = () => { document.getElementById('destDir').value = t.path; testNas(); };
    box.appendChild(btn);
  });
}

async function testNas() {
  const dest = document.getElementById('destDir').value;
  const msgEl = document.getElementById('nasMsg');
  msgEl.textContent = 'Testing connection...';
  msgEl.style.color = '#94a3b8';
  const res = await fetch('/api/test-nas', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({dest})
  });
  const d = await res.json();
  if (d.normalized_path) {
    document.getElementById('destDir').value = d.normalized_path;
  }
  document.getElementById('dotNas').className = d.ok ? 'dot ok' : 'dot';
  msgEl.textContent = d.message;
  msgEl.style.color = d.ok ? '#22c55e' : '#f59e0b';
}

async function openFolder(kind) {
  await fetch('/api/open-folder', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({kind, work_dir: document.getElementById('workDir').value})
  });
}

async function cleanupTemp() {
  if (!confirm('Remove extracted/ and staging/ folders on D:? Your verified files on the Synology NAS and the audit report are kept.')) return;
  await fetch('/api/cleanup', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({work_dir: document.getElementById('workDir').value})
  });
  refresh();
}

async function runAction(action) {
  const payload = {
    action,
    work_dir: document.getElementById('workDir').value,
    dest: document.getElementById('destDir').value,
    no_exiftool: document.getElementById('noExif').checked
  };
  await fetch('/api/action', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  refresh();
}

refresh();
setInterval(refresh, 1500);
</script>
</body>
</html>
"""


class _UIState:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.lock = threading.Lock()
        self.running = False
        self.logs: list[str] = [
            "Ready. Follow the 3 checks above, then click 'Start Migration & Verify 100%'."
        ]

    def log(self, msg: str) -> None:
        with self.lock:
            self.logs.append(msg)
            if len(self.logs) > 300:
                self.logs = self.logs[-300:]


def _test_nas_writable(dest: Path) -> tuple[bool, str]:
    """Verify the NAS SMB share is reachable and writable without leaving junk."""
    if not str(dest).strip():
        return False, "Please enter your Synology SMB destination path."
    try:
        anchor = Path(dest.anchor) if dest.anchor else dest
        if not anchor.exists() or not dest.parent.exists():
            return (
                False,
                f"Cannot reach {dest.parent}. Make sure you are on the same LAN, signed into the NAS in File Explorer, and the parent folder exists.",
            )
        dest.mkdir(exist_ok=True)
        probe = dest / ".g2s_write_test"
        probe.write_bytes(b"ok")
        probe.unlink()
        free_gb = shutil.disk_usage(dest).free / (1024 * 1024 * 1024)
        return True, f"Connected! {dest} is writable ({free_gb:.1f} GB free)."
    except OSError as exc:
        return False, f"Cannot write to {dest}: {exc}"


def _open_local_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def create_ui_server(
    work_dir: Path = Path("D:/G2S"), host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    """Create the local HTTP server for the G2S web dashboard."""
    state = _UIState(Path(work_dir))

    def _run_worker(payload: dict[str, Any]) -> None:
        try:
            wd = Path(payload.get("work_dir") or state.work_dir)
            state.work_dir = wd
            layout = WorkLayout(wd)
            layout.ensure_dirs()
            db = ManifestDB(layout.manifest_db)
            db.init_schema()
            action = payload.get("action")
            dest = Path(payload.get("dest") or "")
            no_exif = bool(payload.get("no_exiftool", False))

            if action in ("scan", "run"):
                state.log("Step 1/4: Scanning Takeout archives...")
                res = scan_takeout(layout, db, on_progress=state.log)
                state.log(f"Scan finished: {res}")

            if action in ("stage", "run"):
                state.log("Step 2/4: Restoring EXIF metadata & staging...")
                exif_path = None if no_exif else find_exiftool(layout)
                if not no_exif and exif_path is None:
                    state.log(
                        f"ERROR: ExifTool not found in {layout.tools_dir} or PATH. "
                        "Place exiftool.exe there or check 'Skip ExifTool'."
                    )
                    return
                if exif_path is not None:
                    with ExifToolRunner(exif_path, layout.tmp_dir) as runner:
                        res = stage_media(layout, db, exif_runner=runner, on_progress=state.log)
                else:
                    res = stage_media(layout, db, exif_runner=None, on_progress=state.log)
                state.log(f"Stage finished: {res}")

            if action in ("transfer", "run"):
                norm = normalize_nas_input(str(dest))
                if norm["kind"] == "quickconnect":
                    state.log(f"ERROR: {norm['message']}")
                    return
                dest = Path(norm["path"])
                if not str(dest).strip():
                    state.log("ERROR: Synology NAS destination path is required.")
                    return
                state.log(f"Step 3/4: Transferring files to {dest}...")
                res = transfer_to_nas(layout, db, dest, on_progress=state.log)
                state.log(f"Transfer finished: {res}")

            if action in ("verify", "run"):
                state.log("Step 4/4: Verifying SHA-256 checksums on NAS...")
                res = verify_nas(layout, db, on_progress=state.log)
                html_path, _ = write_reports(layout, db)
                state.log(f"Verify finished: {res} | Report: {html_path}")
        except Exception as exc:
            state.log(f"ERROR: {exc}")
        finally:
            with state.lock:
                state.running = False

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, code: int, data: dict[str, Any]) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def do_GET(self) -> None:
            if self.path.startswith("/api/status"):
                layout = WorkLayout(state.work_dir)
                layout.ensure_dirs()
                db = ManifestDB(layout.manifest_db)
                db.init_schema()
                zips = list(layout.takeout_dir.glob("*.zip"))
                zip_bytes = sum(z.stat().st_size for z in zips)
                with state.lock:
                    logs = list(state.logs)
                    running = state.running
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "work_dir": str(layout.work_dir),
                        "work_free_bytes": shutil.disk_usage(layout.work_dir).free,
                        "counts": db.summary_counts(),
                        "exiftool_found": find_exiftool(layout) is not None,
                        "takeout_zip_count": len(zips),
                        "takeout_zip_bytes": zip_bytes,
                        "report_exists": (layout.reports_dir / "audit_report.html").is_file(),
                        "running": running,
                        "logs": logs,
                    },
                )
                return

            if self.path == "/report":
                report = WorkLayout(state.work_dir).reports_dir / "audit_report.html"
                if not report.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND, "Report not generated yet")
                    return
                body = report.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            page = _HTML_PAGE.replace(
                "__WORK_DIR__", str(state.work_dir).replace("\\", "\\\\")
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self) -> None:
            if self.path == "/api/discover-nas":
                self._send_json(HTTPStatus.OK, {"targets": discover_synology_targets()})
                return

            if self.path == "/api/test-nas":
                payload = self._read_json()
                norm = normalize_nas_input(payload.get("dest") or "")
                if norm["kind"] in ("empty", "quickconnect"):
                    self._send_json(HTTPStatus.OK, {"ok": False, "message": norm["message"]})
                    return
                ok, msg = _test_nas_writable(Path(norm["path"]))
                self._send_json(
                    HTTPStatus.OK,
                    {"ok": ok, "message": msg, "normalized_path": norm["path"]},
                )
                return

            if self.path == "/api/open-folder":
                payload = self._read_json()
                layout = WorkLayout(Path(payload.get("work_dir") or state.work_dir))
                kind = payload.get("kind")
                target = {
                    "takeout": layout.takeout_dir,
                    "tools": layout.tools_dir,
                    "reports": layout.reports_dir,
                }.get(kind, layout.work_dir)
                _open_local_folder(target)
                self._send_json(HTTPStatus.OK, {"opened": str(target)})
                return

            if self.path == "/api/cleanup":
                payload = self._read_json()
                layout = WorkLayout(Path(payload.get("work_dir") or state.work_dir))
                db = ManifestDB(layout.manifest_db)
                counts = db.summary_counts() if layout.manifest_db.is_file() else {"total": 0}
                unique_expected = counts.get("total", 0) - counts.get("duplicate_skipped", 0)
                all_passed = (
                    counts.get("total", 0) > 0
                    and counts.get("verified", 0) == unique_expected
                    and counts.get("verify_failed", 0) == 0
                )
                if not all_passed:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "Cleanup is locked until 100% verification passes."},
                    )
                    return
                for folder in (layout.extracted_dir, layout.staging_dir):
                    if folder.exists():
                        shutil.rmtree(folder)
                    folder.mkdir(parents=True, exist_ok=True)
                state.log("Cleaned up extracted/ and staging/ folders on D:.")
                self._send_json(HTTPStatus.OK, {"cleaned": True})
                return

            if self.path != "/api/action":
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            payload = self._read_json()
            with state.lock:
                if state.running:
                    self._send_json(HTTPStatus.CONFLICT, {"error": "Already running"})
                    return
                state.running = True
            threading.Thread(target=_run_worker, args=(payload,), daemon=True).start()
            self._send_json(HTTPStatus.ACCEPTED, {"started": True})

    return ThreadingHTTPServer((host, port), Handler)


def launch_ui(work_dir: Path = Path("D:/G2S"), port: int = 8765) -> None:
    """Start the local UI server and open it in the default browser."""
    server = create_ui_server(work_dir=work_dir, port=port)
    url = f"http://127.0.0.1:{port}/"
    print(f"G2S Web UI running at {url} (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
