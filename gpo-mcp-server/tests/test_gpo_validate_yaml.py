"""Tests for scripts/gpo_validate_yaml.py."""

from __future__ import annotations

import pytest
from pathlib import Path

from scripts.gpo_validate_yaml import validate_file, validate_all


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _minimal_valid_yaml(name: str = "DisableAutorun") -> str:
    return f"""\
collection_name: "Test Collection"
ou: "Workstations"
settings:
  - uid: "{{A1B2C3D4-0001-0001-0001-000000000001}}"
    name: {name}
    description: "Test setting"
    bypass_errors: false
    properties:
      action: U
      hive: HKEY_LOCAL_MACHINE
      key: "SOFTWARE\\\\Microsoft\\\\Windows"
      value_name: TestValue
      value_type: REG_DWORD
      value: "1"
"""


# ---------------------------------------------------------------------------
# validate_file — valid input
# ---------------------------------------------------------------------------

def test_validate_file_valid(tmp_path):
    """A fully valid YAML file should produce no errors."""
    f = tmp_path / "policy.yaml"
    _write_yaml(f, _minimal_valid_yaml())
    errors = validate_file(f)
    assert errors == []


def test_validate_file_all_value_types(tmp_path):
    """Every valid registry type should pass validation."""
    valid_types = [
        "REG_SZ", "REG_EXPAND_SZ", "REG_BINARY",
        "REG_DWORD", "REG_DWORD_BIG_ENDIAN", "REG_MULTI_SZ", "REG_QWORD",
    ]
    for vtype in valid_types:
        f = tmp_path / f"policy_{vtype}.yaml"
        _write_yaml(f, f"""\
collection_name: "Col"
ou: "OU"
settings:
  - name: S
    properties:
      hive: HKEY_LOCAL_MACHINE
      key: SOFTWARE\\\\Test
      value_name: V
      value_type: {vtype}
      value: "0"
""")
        errors = validate_file(f)
        assert errors == [], f"Type {vtype!r} should be valid but got: {errors}"


def test_validate_file_all_valid_hives(tmp_path):
    """Every valid registry hive should pass validation."""
    valid_hives = [
        "HKEY_LOCAL_MACHINE", "HKEY_CURRENT_USER", "HKEY_CLASSES_ROOT",
        "HKEY_USERS", "HKEY_CURRENT_CONFIG",
    ]
    for hive in valid_hives:
        f = tmp_path / f"policy_{hive}.yaml"
        _write_yaml(f, f"""\
collection_name: "Col"
ou: "OU"
settings:
  - name: S
    properties:
      hive: {hive}
      key: SOFTWARE\\\\Test
      value_name: V
      value_type: REG_DWORD
      value: "0"
""")
        errors = validate_file(f)
        assert errors == [], f"Hive {hive!r} should be valid but got: {errors}"


def test_validate_file_empty_settings_list(tmp_path):
    """An empty settings list is valid."""
    f = tmp_path / "policy.yaml"
    _write_yaml(f, """\
collection_name: "Empty Policy"
ou: "Workstations"
settings: []
""")
    errors = validate_file(f)
    assert errors == []


# ---------------------------------------------------------------------------
# validate_file — missing top-level keys
# ---------------------------------------------------------------------------

def test_validate_file_missing_collection_name(tmp_path):
    """Missing collection_name should be flagged."""
    f = tmp_path / "policy.yaml"
    _write_yaml(f, """\
ou: "Workstations"
settings: []
""")
    errors = validate_file(f)
    assert any("collection_name" in e for e in errors)


def test_validate_file_missing_ou(tmp_path):
    """Missing ou should be flagged."""
    f = tmp_path / "policy.yaml"
    _write_yaml(f, """\
collection_name: "Col"
settings: []
""")
    errors = validate_file(f)
    assert any("ou" in e for e in errors)


def test_validate_file_missing_settings_key(tmp_path):
    """Missing settings key should be flagged."""
    f = tmp_path / "policy.yaml"
    _write_yaml(f, """\
collection_name: "Col"
ou: "Workstations"
""")
    errors = validate_file(f)
    assert any("settings" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_file — bad value type / hive
# ---------------------------------------------------------------------------

def test_validate_file_invalid_value_type(tmp_path):
    """An invalid value_type should be flagged."""
    f = tmp_path / "policy.yaml"
    _write_yaml(f, """\
collection_name: "Col"
ou: "OU"
settings:
  - name: S
    properties:
      hive: HKEY_LOCAL_MACHINE
      key: SOFTWARE\\\\Test
      value_name: V
      value_type: REG_INVALID
      value: "0"
""")
    errors = validate_file(f)
    assert any("REG_INVALID" in e for e in errors)


def test_validate_file_invalid_hive(tmp_path):
    """An invalid hive name should be flagged."""
    f = tmp_path / "policy.yaml"
    _write_yaml(f, """\
collection_name: "Col"
ou: "OU"
settings:
  - name: S
    properties:
      hive: HKEY_BOGUS
      key: SOFTWARE\\\\Test
      value_name: V
      value_type: REG_DWORD
      value: "0"
""")
    errors = validate_file(f)
    assert any("HKEY_BOGUS" in e for e in errors)


def test_validate_file_empty_key(tmp_path):
    """An empty registry key should be flagged."""
    f = tmp_path / "policy.yaml"
    _write_yaml(f, """\
collection_name: "Col"
ou: "OU"
settings:
  - name: S
    properties:
      hive: HKEY_LOCAL_MACHINE
      key: ""
      value_name: V
      value_type: REG_DWORD
      value: "0"
""")
    errors = validate_file(f)
    assert any("key" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# validate_file — malformed YAML
# ---------------------------------------------------------------------------

def test_validate_file_malformed_yaml(tmp_path):
    """Syntactically invalid YAML should produce a malformed error."""
    f = tmp_path / "policy.yaml"
    f.write_text("key: {unclosed_brace", encoding="utf-8")
    errors = validate_file(f)
    assert any("malformed" in e.lower() for e in errors)


def test_validate_file_empty_file(tmp_path):
    """An empty file should be flagged."""
    f = tmp_path / "policy.yaml"
    f.write_text("", encoding="utf-8")
    errors = validate_file(f)
    assert len(errors) > 0


def test_validate_file_non_mapping_root(tmp_path):
    """A YAML file whose root is a list should be flagged."""
    f = tmp_path / "policy.yaml"
    f.write_text("- item1\n- item2\n", encoding="utf-8")
    errors = validate_file(f)
    assert any("mapping" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# validate_all — integration
# ---------------------------------------------------------------------------

def test_validate_all_passes_with_valid_files(tmp_path):
    """validate_all should return 0 when all files are valid."""
    policies = tmp_path / "policies"
    _write_yaml(policies / "a.yaml", _minimal_valid_yaml("SettingA"))
    _write_yaml(policies / "b.yaml", _minimal_valid_yaml("SettingB"))

    result = validate_all(tmp_path)
    assert result == 0


def test_validate_all_fails_with_invalid_file(tmp_path):
    """validate_all should return 1 when any file is invalid."""
    policies = tmp_path / "policies"
    _write_yaml(policies / "good.yaml", _minimal_valid_yaml())
    _write_yaml(policies / "bad.yaml", """\
collection_name: "Bad"
ou: "OU"
settings:
  - name: S
    properties:
      hive: HKEY_BOGUS
      key: SOFTWARE\\\\Test
      value_name: V
      value_type: REG_DWORD
      value: "0"
""")

    result = validate_all(tmp_path)
    assert result == 1


def test_validate_all_no_files(tmp_path):
    """validate_all should return 0 (no errors) when the policies/ dir is empty."""
    (tmp_path / "policies").mkdir()
    result = validate_all(tmp_path)
    assert result == 0


def test_validate_all_missing_policies_dir(tmp_path):
    """validate_all should return 1 when policies/ directory doesn't exist."""
    result = validate_all(tmp_path)
    assert result == 1
