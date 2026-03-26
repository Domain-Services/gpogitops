"""Tests for the GPO what-if analysis script (XML mode)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from gpo_whatif import validate_file_xml, print_whatif_report


def _write_valid_xml(path: Path) -> None:
    """Write a minimal valid GPO XML file."""
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Collection clsid="{53B533F5-224C-47e3-B01B-CA3B3F3FF4BF}" name="Test">'
        '<Registry clsid="{9CD4B2F4-923D-47f5-A062-E897DD1DAD50}" '
        'name="Setting1" uid="{11111111-1111-1111-1111-111111111111}" '
        'status="TestValue" image="12" changed="2024-01-01 00:00:00" desc="">'
        '<Properties action="U" hive="HKEY_LOCAL_MACHINE" key="SOFTWARE\\Test" '
        'name="TestValue" type="REG_DWORD" value="1" displayDecimal="1" default="0" />'
        "</Registry>"
        "</Collection>",
        encoding="utf-8",
    )


def test_validate_file_valid(tmp_path):
    """Valid file should produce no errors."""
    fpath = tmp_path / "ok.xml"
    _write_valid_xml(fpath)
    errors = validate_file_xml(fpath)
    assert errors == []


def test_validate_file_malformed(tmp_path):
    """Malformed XML should produce an error."""
    fpath = tmp_path / "bad.xml"
    fpath.write_text("<not closed>", encoding="utf-8")
    errors = validate_file_xml(fpath)
    assert len(errors) == 1
    assert "malformed xml" in errors[0].lower()


def test_validate_file_invalid_type(tmp_path):
    """Setting with invalid value type should be flagged."""
    fpath = tmp_path / "bad_type.xml"
    fpath.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Collection clsid="" name="Test">'
        '<Registry clsid="" name="Bad" uid="{A}" status="" image="12" changed="" desc="">'
        '<Properties action="U" hive="HKEY_LOCAL_MACHINE" key="SOFTWARE\\X" '
        'name="Val" type="REG_INVALID" value="1" />'
        "</Registry>"
        "</Collection>",
        encoding="utf-8",
    )
    errors = validate_file_xml(fpath)
    assert any("invalid value type" in e.lower() for e in errors)


def test_validate_file_invalid_hive(tmp_path):
    """Setting with invalid hive should be flagged."""
    fpath = tmp_path / "bad_hive.xml"
    fpath.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Collection clsid="" name="Test">'
        '<Registry clsid="" name="Bad" uid="{B}" status="" image="12" changed="" desc="">'
        '<Properties action="U" hive="HKEY_FAKE" key="SOFTWARE\\X" '
        'name="Val" type="REG_DWORD" value="1" />'
        "</Registry>"
        "</Collection>",
        encoding="utf-8",
    )
    errors = validate_file_xml(fpath)
    assert any("invalid registry hive" in e.lower() for e in errors)


def test_validate_file_empty_key(tmp_path):
    """Setting with empty registry key should be flagged."""
    fpath = tmp_path / "empty_key.xml"
    fpath.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Collection clsid="" name="Test">'
        '<Registry clsid="" name="Bad" uid="{C}" status="" image="12" changed="" desc="">'
        '<Properties action="U" hive="HKEY_LOCAL_MACHINE" key="" '
        'name="Val" type="REG_DWORD" value="1" />'
        "</Registry>"
        "</Collection>",
        encoding="utf-8",
    )
    errors = validate_file_xml(fpath)
    assert any("empty registry key" in e.lower() for e in errors)


def test_validate_file_missing_uid(tmp_path):
    """Setting without uid attribute should be flagged."""
    fpath = tmp_path / "no_uid.xml"
    fpath.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<Collection clsid="" name="Test">'
        '<Registry clsid="" name="NoUID" status="" image="12" changed="" desc="">'
        '<Properties action="U" hive="HKEY_LOCAL_MACHINE" key="SOFTWARE\\X" '
        'name="Val" type="REG_DWORD" value="1" />'
        "</Registry>"
        "</Collection>",
        encoding="utf-8",
    )
    errors = validate_file_xml(fpath)
    assert any("missing uid" in e.lower() for e in errors)


def test_whatif_report_returns_zero_for_valid(tmp_path):
    """Report should return 0 when all files are valid."""
    fpath = tmp_path / "ok.xml"
    _write_valid_xml(fpath)
    result = print_whatif_report([fpath], tmp_path, fmt="xml")
    assert result == 0


def test_whatif_report_returns_one_for_invalid(tmp_path):
    """Report should return 1 when validation errors exist."""
    fpath = tmp_path / "bad.xml"
    fpath.write_text("<not closed>", encoding="utf-8")
    result = print_whatif_report([fpath], tmp_path, fmt="xml")
    assert result == 1


def test_whatif_report_empty_list(tmp_path):
    """Report with no files should return 0."""
    result = print_whatif_report([], tmp_path, fmt="xml")
    assert result == 0
