from g2s.discover import normalize_nas_input, parse_arp_synology_ips


def test_normalize_nas_input_variants():
    # 1. Bare IP -> expands to Synology Photos personal or shared SMB path
    r1 = normalize_nas_input("192.168.1.100", space="personal")
    assert r1["kind"] == "smb"
    assert r1["path"] == r"\\192.168.1.100\home\Photos\GooglePhotos"

    r2 = normalize_nas_input("192.168.1.100", space="shared")
    assert r2["path"] == r"\\192.168.1.100\photo\GooglePhotos"

    # 2. Bare hostname -> expands to UNC SMB path
    r3 = normalize_nas_input("DiskStation")
    assert r3["kind"] == "smb"
    assert r3["path"] == r"\\DiskStation\home\Photos\GooglePhotos"

    # 3. QuickConnect / HTTPS URL -> flagged clearly as quickconnect
    r4 = normalize_nas_input("https://mynas.de6.quickconnect.to/")
    assert r4["kind"] == "quickconnect"
    assert r4["quickconnect_id"] == "mynas"

    # 4. Full UNC or drive letter -> kept as-is
    r5 = normalize_nas_input(r"Z:\Photos\GooglePhotos")
    assert r5["kind"] == "local_or_mapped"
    assert r5["path"] == r"Z:\Photos\GooglePhotos"


def test_parse_arp_synology_ips():
    sample = """
Interface: 192.168.179.10 --- 0x5
  Internet Address      Physical Address      Type
  192.168.179.1         aa-bb-cc-dd-ee-ff     dynamic
  192.168.1.100         00-11-32-ab-cd-ef     dynamic
  192.168.1.55          90-09-d0-12-34-56     dynamic
"""
    assert parse_arp_synology_ips(sample) == ["192.168.1.100", "192.168.1.55"]
