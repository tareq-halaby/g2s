"""Smart Synology NAS discovery and destination input normalization."""

from __future__ import annotations

import re
import socket
import subprocess
from typing import Any
from urllib.parse import urlparse

_SYNOLOGY_OUIS = ("00-11-32", "90-09-d0", "00:11:32", "90:09:d0")
_ARP_LINE_RE = re.compile(
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+(?P<mac>(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2})"
)
_NET_USE_RE = re.compile(r"(?P<drive>[A-Z]:)\s+(?P<unc>\\\\[^\s]+)")
_QC_RE = re.compile(r"^(?:https?://)?(?P<id>[a-zA-Z0-9-]+)(?:\.[a-zA-Z0-9-]+)?\.quickconnect\.to", re.IGNORECASE)


def normalize_nas_input(raw: str, space: str = "personal") -> dict[str, Any]:
    """Normalize user-entered NAS target (IP, hostname, UNC, drive, or QuickConnect URL)."""
    text = raw.strip()
    if not text:
        return {"kind": "empty", "path": "", "message": "Enter a NAS IP, hostname, or shared folder path."}

    m_qc = _QC_RE.match(text)
    if m_qc:
        qc_id = m_qc.group("id")
        return {
            "kind": "quickconnect",
            "quickconnect_id": qc_id,
            "path": "",
            "message": (
                f"'{qc_id}.quickconnect.to' is a QuickConnect web URL (HTTPS), not a local SMB file share. "
                "Click 'Auto-Detect NAS' on your LAN to connect at full speed."
            ),
        }

    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        host = parsed.hostname or text
        share = "photo" if space == "shared" else r"home\Photos"
        return {
            "kind": "smb",
            "path": rf"\\{host}\{share}\GooglePhotos",
            "message": f"Converted web URL to SMB path: \\\\{host}\\{share}\\GooglePhotos",
        }

    if text.startswith("\\\\") or text.startswith("//"):
        unc = text.replace("/", "\\")
        return {"kind": "smb", "path": unc, "message": ""}

    if re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith("/"):
        return {"kind": "local_or_mapped", "path": text, "message": ""}

    # Bare IP or hostname (e.g. 192.168.1.100 or DiskStation)
    host = text.strip("\\/")
    share = "photo" if space == "shared" else r"home\Photos"
    return {
        "kind": "smb",
        "path": rf"\\{host}\{share}\GooglePhotos",
        "message": f"Expanded '{host}' to Synology Photos SMB path.",
    }


def parse_arp_synology_ips(arp_output: str) -> list[str]:
    """Extract IPv4 addresses from `arp -a` matching Synology MAC prefixes."""
    ips: list[str] = []
    for match in _ARP_LINE_RE.finditer(arp_output):
        mac = match.group("mac").lower()
        if any(mac.startswith(oui) for oui in _SYNOLOGY_OUIS):
            ip = match.group("ip")
            if ip not in ips:
                ips.append(ip)
    return ips


def _is_smb_open(host: str, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, 445), timeout=timeout):
            return True
    except OSError:
        return False


def discover_synology_targets() -> list[dict[str, str]]:
    """Find reachable Synology SMB targets and mapped Windows drives on the LAN."""
    targets: list[dict[str, str]] = []
    seen_hosts: set[str] = set()

    # 1. Check ARP table for Synology MAC addresses
    try:
        arp_out = subprocess.check_output(
            ["arp", "-a"], text=True, stderr=subprocess.DEVNULL, timeout=3
        )
        for ip in parse_arp_synology_ips(arp_out):
            if _is_smb_open(ip):
                seen_hosts.add(ip)
                targets.append(
                    {
                        "label": f"Synology NAS ({ip}) — Personal Photos",
                        "path": rf"\\{ip}\home\Photos\GooglePhotos",
                    }
                )
                targets.append(
                    {
                        "label": f"Synology NAS ({ip}) — Shared /photo",
                        "path": rf"\\{ip}\photo\GooglePhotos",
                    }
                )
    except Exception:
        pass

    # 2. Check common Synology hostnames
    for name in ("DiskStation", "Synology"):
        try:
            ip = socket.gethostbyname(name)
            if ip not in seen_hosts and _is_smb_open(ip):
                seen_hosts.add(ip)
                targets.append(
                    {
                        "label": f"{name} ({ip}) — Personal Photos",
                        "path": rf"\\{name}\home\Photos\GooglePhotos",
                    }
                )
                targets.append(
                    {
                        "label": f"{name} ({ip}) — Shared /photo",
                        "path": rf"\\{name}\photo\GooglePhotos",
                    }
                )
        except OSError:
            continue

    # 3. Check already-mapped network drives (`net use`)
    try:
        net_out = subprocess.check_output(
            ["net", "use"], text=True, stderr=subprocess.DEVNULL, timeout=3
        )
        for m in _NET_USE_RE.finditer(net_out):
            drive = m.group("drive")
            unc = m.group("unc")
            targets.append(
                {
                    "label": f"Mapped Drive {drive} ({unc})",
                    "path": rf"{drive}\GooglePhotos",
                }
            )
    except Exception:
        pass

    return targets
