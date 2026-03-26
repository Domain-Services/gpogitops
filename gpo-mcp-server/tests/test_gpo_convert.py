"""Tests for scripts/gpo_convert.py — YAML→XML round-trip."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.gpo_convert import (
    COLLECTION_CLSID,
    REGISTRY_CLSID,
    convert_file,
    convert_all,
)


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# convert_file — success paths
# ---------------------------------------------------------------------------

def test_convert_file_produces_xml(tmp_path):
    """convert_file should write a well-formed XML file."""
    yaml_path = tmp_path / "policy.yaml"
    out_dir = tmp_path / "generated"
    _write_yaml(yaml_path, """\
collection_name: "Workstations Security Baseline"
ou: "Workstations"
settings:
  - uid: "{A1B2C3D4-0001-0001-0001-000000000001}"
    name: DisableAutorun
    description: "Prevent autorun"
    bypass_errors: false
    properties:
      action: U
      hive: HKEY_LOCAL_MACHINE
      key: "SOFTWARE\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Policies\\\\Explorer"
      value_name: NoDriveTypeAutoRun
      value_type: REG_DWORD
      value: "255"
""")

    ok, result = convert_file(yaml_path, out_dir)
    assert ok, f"convert_file failed: {result}"

    # XML file should be placed under out_dir/Workstations/
    xml_path = Path(result)
    assert xml_path.exists()
    assert xml_path.suffix == ".xml"


def test_convert_file_correct_clsids(tmp_path):
    """Generated XML must contain the correct GPO CLSIDs."""
    yaml_path = tmp_path / "policy.yaml"
    out_dir = tmp_path / "out"
    _write_yaml(yaml_path, """\
collection_name: "Test GPO"
ou: "Servers"
settings:
  - uid: "{BBBBBBBB-0001-0001-0001-000000000002}"
    name: TestSetting
    properties:
      hive: HKEY_LOCAL_MACHINE
      key: SOFTWARE\\\\Test
      value_name: TestVal
      value_type: REG_DWORD
      value: "1"
""")

    ok, result = convert_file(yaml_path, out_dir)
    assert ok

    tree = ET.parse(result)
    root_elem = tree.getroot()

    assert root_elem.get("clsid") == COLLECTION_CLSID

    reg_elem = root_elem.find(".//Registry")
    assert reg_elem is not None
    assert reg_elem.get("clsid") == REGISTRY_CLSID


def test_convert_file_registry_attributes(tmp_path):
    """All registry Properties attributes should be correctly mapped."""
    yaml_path = tmp_path / "policy.yaml"
    out_dir = tmp_path / "out"
    uid = "{CCCCCCCC-0001-0001-0001-000000000003}"
    _write_yaml(yaml_path, f"""\
collection_name: "My Policy"
ou: "Workstations"
settings:
  - uid: "{uid}"
    name: MyReg
    bypass_errors: true
    properties:
      action: U
      hive: HKEY_CURRENT_USER
      key: "Software\\\\My\\\\App"
      value_name: EnableFeature
      value_type: REG_SZ
      value: "enabled"
""")

    ok, result = convert_file(yaml_path, out_dir)
    assert ok

    tree = ET.parse(result)
    reg = tree.getroot().find(".//Registry")
    props = reg.find("Properties")

    assert reg.get("uid") == uid
    assert reg.get("name") == "MyReg"
    assert reg.get("bypassErrors") == "1"
    assert props.get("hive") == "HKEY_CURRENT_USER"
    assert props.get("key") == "Software\\My\\App"
    assert props.get("name") == "EnableFeature"
    assert props.get("type") == "REG_SZ"
    assert props.get("value") == "enabled"
    assert props.get("action") == "U"


def test_convert_file_collection_name_in_xml(tmp_path):
    """The Collection element should carry the collection_name."""
    yaml_path = tmp_path / "policy.yaml"
    out_dir = tmp_path / "out"
    _write_yaml(yaml_path, """\
collection_name: "My GPO Collection"
ou: "OU1"
settings: []
""")

    ok, result = convert_file(yaml_path, out_dir)
    assert ok

    tree = ET.parse(result)
    root_elem = tree.getroot()
    assert root_elem.get("name") == "My GPO Collection"


def test_convert_file_ou_creates_subdirectory(tmp_path):
    """When ou is set, XML should be placed in out_dir/<ou>/<name>.xml."""
    yaml_path = tmp_path / "policy.yaml"
    out_dir = tmp_path / "out"
    _write_yaml(yaml_path, """\
collection_name: "Baseline"
ou: "Servers"
settings: []
""")

    ok, result = convert_file(yaml_path, out_dir)
    assert ok

    xml_path = Path(result)
    # Parent directory should be named after the OU
    assert xml_path.parent.name == "Servers"


def test_convert_file_no_ou_flat_output(tmp_path):
    """When ou is absent, XML should be written directly to out_dir."""
    yaml_path = tmp_path / "policy.yaml"
    out_dir = tmp_path / "out"
    _write_yaml(yaml_path, """\
collection_name: "Flat Policy"
settings: []
""")

    ok, result = convert_file(yaml_path, out_dir)
    assert ok

    xml_path = Path(result)
    assert xml_path.parent == out_dir


def test_convert_file_multiple_settings(tmp_path):
    """All settings in the YAML should appear as Registry elements in the XML."""
    yaml_path = tmp_path / "policy.yaml"
    out_dir = tmp_path / "out"
    _write_yaml(yaml_path, """\
collection_name: "Multi"
ou: "OU"
settings:
  - uid: "{AA000001-0001-0001-0001-000000000001}"
    name: Setting1
    properties:
      hive: HKEY_LOCAL_MACHINE
      key: SOFTWARE\\\\A
      value_name: V1
      value_type: REG_DWORD
      value: "1"
  - uid: "{AA000002-0001-0001-0001-000000000002}"
    name: Setting2
    properties:
      hive: HKEY_LOCAL_MACHINE
      key: SOFTWARE\\\\B
      value_name: V2
      value_type: REG_SZ
      value: "hello"
""")

    ok, result = convert_file(yaml_path, out_dir)
    assert ok

    tree = ET.parse(result)
    registry_elements = tree.getroot().findall(".//Registry")
    assert len(registry_elements) == 2
    names = {r.get("name") for r in registry_elements}
    assert names == {"Setting1", "Setting2"}


# ---------------------------------------------------------------------------
# convert_file — error paths
# ---------------------------------------------------------------------------

def test_convert_file_malformed_yaml(tmp_path):
    """convert_file should return (False, error) on malformed YAML."""
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text("key: {unclosed", encoding="utf-8")
    out_dir = tmp_path / "out"

    ok, msg = convert_file(yaml_path, out_dir)
    assert not ok
    assert "malformed" in msg.lower() or "yaml" in msg.lower()


# ---------------------------------------------------------------------------
# convert_all — integration
# ---------------------------------------------------------------------------

def test_convert_all_returns_0_on_success(tmp_path):
    """convert_all should return 0 when all files convert successfully."""
    policies = tmp_path / "policies"
    _write_yaml(policies / "a.yaml", """\
collection_name: "A"
ou: "OU"
settings: []
""")
    _write_yaml(policies / "b.yaml", """\
collection_name: "B"
ou: "OU"
settings: []
""")

    out_dir = tmp_path / "generated"
    result = convert_all(tmp_path, out_dir)
    assert result == 0

    # Both XML artefacts should have been created
    xml_files = list(out_dir.rglob("*.xml"))
    assert len(xml_files) == 2


def test_convert_all_missing_policies_dir(tmp_path):
    """convert_all should return 1 when policies/ directory doesn't exist."""
    result = convert_all(tmp_path, tmp_path / "generated")
    assert result == 1


def test_convert_all_no_yaml_files(tmp_path):
    """convert_all should return 0 when policies/ is empty (nothing to do)."""
    (tmp_path / "policies").mkdir()
    result = convert_all(tmp_path, tmp_path / "generated")
    assert result == 0


def test_convert_all_creates_out_dir(tmp_path):
    """convert_all should create the output directory if it doesn't exist."""
    policies = tmp_path / "policies"
    _write_yaml(policies / "policy.yaml", """\
collection_name: "P"
ou: "OU"
settings: []
""")

    out_dir = tmp_path / "does" / "not" / "exist"
    assert not out_dir.exists()

    convert_all(tmp_path, out_dir)
    # The directory should now exist (created by convert_file)
    assert out_dir.exists() or (out_dir / "OU").exists()


def test_convert_all_roundtrip_values(tmp_path):
    """Values written to XML must be retrievable from the generated file."""
    policies = tmp_path / "policies"
    _write_yaml(policies / "policy.yaml", """\
collection_name: "RoundTrip"
ou: "OU"
settings:
  - uid: "{RT000001-0001-0001-0001-000000000001}"
    name: MyKey
    properties:
      hive: HKEY_LOCAL_MACHINE
      key: "SOFTWARE\\\\My\\\\Path"
      value_name: MyValue
      value_type: REG_QWORD
      value: "12345"
""")

    out_dir = tmp_path / "generated"
    result = convert_all(tmp_path, out_dir)
    assert result == 0

    xml_files = list(out_dir.rglob("*.xml"))
    assert len(xml_files) == 1

    tree = ET.parse(xml_files[0])
    reg = tree.getroot().find(".//Registry")
    props = reg.find("Properties")

    assert reg.get("name") == "MyKey"
    assert props.get("hive") == "HKEY_LOCAL_MACHINE"
    assert props.get("key") == "SOFTWARE\\My\\Path"
    assert props.get("name") == "MyValue"
    assert props.get("type") == "REG_QWORD"
    assert props.get("value") == "12345"
