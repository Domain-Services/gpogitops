"""Tests for YAMLService — mirrors test_xml_service.py in structure."""

from __future__ import annotations

import pytest
from pathlib import Path

from app import config
from app.services.yaml_service import YAMLParseError, YAMLService
from app.services.yaml_service import yaml_service as singleton_yaml_service


class TestYAMLService:
    """Test cases for YAMLService."""

    # ------------------------------------------------------------------
    # create_file
    # ------------------------------------------------------------------

    def test_create_file(self, temp_repo, mock_settings):
        """Creating a new YAML policy file should succeed and produce a valid file."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"

        success, message = svc.create_file(file_path, "Test Collection", ou="Workstations")

        assert success
        assert file_path.exists()
        assert "Created" in message

    def test_create_file_creates_parent_dirs(self, temp_repo, mock_settings):
        """create_file should create the policies/ directory if it doesn't exist."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        file_path = policies_dir / "sub" / "test.yaml"

        success, _ = svc.create_file(file_path, "Col")
        assert success
        assert file_path.exists()

    def test_create_file_content(self, temp_repo, mock_settings):
        """Created YAML file should have correct top-level fields."""
        import yaml
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"

        svc.create_file(file_path, "My Collection", ou="Servers", description="desc here")

        with file_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        assert data["collection_name"] == "My Collection"
        assert data["ou"] == "Servers"
        assert data["description"] == "desc here"
        assert data["settings"] == []

    # ------------------------------------------------------------------
    # parse_file
    # ------------------------------------------------------------------

    def test_parse_file_empty(self, temp_repo, mock_settings):
        """Parsing an empty collection returns correct shape with no settings."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"

        svc.create_file(file_path, "Test Collection", ou="WS")
        data = svc.parse_file(file_path)

        assert data["collection_name"] == "Test Collection"
        assert data["ou"] == "WS"
        assert data["settings"] == []
        assert data["file"] == "test.yaml"

    def test_parse_file_raises_on_malformed_yaml(self, temp_repo, mock_settings):
        """parse_file should raise YAMLParseError on malformed YAML."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "broken.yaml"
        # Write syntactically invalid YAML (unbalanced braces)
        file_path.write_text("key: {unclosed", encoding="utf-8")

        with pytest.raises(YAMLParseError, match="Malformed YAML"):
            svc.parse_file(file_path)

    def test_parse_file_dict_shape_compatibility(self, temp_repo, mock_settings):
        """parse_file output must use the same dict keys as xml_service.parse_file."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"

        svc.create_file(file_path, "Col", ou="OU")
        svc.add_setting(
            file_path,
            name="DisableAutorun",
            hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\Policies\\Explorer",
            value_name="NoDriveTypeAutoRun",
            value_type="REG_DWORD",
            value="255",
            description="Prevent autorun",
        )

        data = svc.parse_file(file_path)
        setting = data["settings"][0]

        # Must have all expected keys
        for key in ("uid", "name", "description", "bypassErrors", "properties"):
            assert key in setting, f"Missing key: {key}"

        props = setting["properties"]
        for key in ("action", "hive", "key", "name", "type", "value", "displayDecimal", "default"):
            assert key in props, f"Missing property key: {key}"

        # Internal mapping: value_name → name, value_type → type
        assert props["name"] == "NoDriveTypeAutoRun"
        assert props["type"] == "REG_DWORD"

    # ------------------------------------------------------------------
    # add_setting
    # ------------------------------------------------------------------

    def test_add_setting(self, temp_repo, mock_settings):
        """add_setting should append a new entry with an auto-generated UID."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Test Collection")

        success, message = svc.add_setting(
            file_path,
            name="Test Setting",
            hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\Test",
            value_name="TestValue",
            value_type="REG_DWORD",
            value="1",
            description="Test description",
        )

        assert success
        assert "UID" in message

        data = svc.parse_file(file_path)
        assert len(data["settings"]) == 1
        assert data["settings"][0]["name"] == "Test Setting"

    def test_add_setting_uid_is_unique(self, temp_repo, mock_settings):
        """Each add_setting call generates a distinct UID."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")

        for i in range(3):
            svc.add_setting(
                file_path, name=f"S{i}", hive="HKEY_LOCAL_MACHINE",
                key="SOFTWARE\\Test", value_name="Val", value_type="REG_DWORD", value=str(i),
            )

        data = svc.parse_file(file_path)
        uids = [s["uid"] for s in data["settings"]]
        assert len(set(uids)) == 3, "UIDs must be unique"

    def test_add_setting_uid_format(self, temp_repo, mock_settings):
        """Generated UIDs must follow the {XXXXXXXX-...} format."""
        import re
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")

        _, message = svc.add_setting(
            file_path, name="S", hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\X", value_name="V", value_type="REG_SZ", value="x",
        )
        uid_match = re.search(r"\{[0-9A-F\-]+\}", message)
        assert uid_match, f"UID not found in message: {message}"

    def test_add_setting_rejects_invalid_type(self, temp_repo, mock_settings):
        """add_setting must reject invalid registry value types."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")

        success, message = svc.add_setting(
            file_path, name="Bad Type", hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\Test", value_name="TestValue",
            value_type="REG_INVALID", value="1",
        )
        assert not success
        assert "Invalid value_type" in message

    def test_add_setting_all_valid_types(self, temp_repo, mock_settings):
        """add_setting should accept every valid registry type."""
        from app.services.yaml_service import VALID_VALUE_TYPES

        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")

        for vtype in sorted(VALID_VALUE_TYPES):
            ok, msg = svc.add_setting(
                file_path, name=f"S_{vtype}", hive="HKEY_LOCAL_MACHINE",
                key="SOFTWARE\\Test", value_name="V", value_type=vtype, value="0",
            )
            assert ok, f"Type {vtype!r} should be valid but got: {msg}"

    # ------------------------------------------------------------------
    # update_setting
    # ------------------------------------------------------------------

    def test_update_setting_value(self, temp_repo, mock_settings):
        """update_setting should change the value field."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")
        svc.add_setting(
            file_path, name="S", hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\Test", value_name="Val", value_type="REG_DWORD", value="1",
        )

        uid = svc.parse_file(file_path)["settings"][0]["uid"]
        success, msg = svc.update_setting(file_path, uid, new_value="42")
        assert success

        data = svc.parse_file(file_path)
        assert data["settings"][0]["properties"]["value"] == "42"

    def test_update_setting_name_and_description(self, temp_repo, mock_settings):
        """update_setting should update name and description independently."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")
        svc.add_setting(
            file_path, name="Old Name", hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\Test", value_name="Val", value_type="REG_SZ", value="x",
            description="Old desc",
        )

        uid = svc.parse_file(file_path)["settings"][0]["uid"]
        svc.update_setting(file_path, uid, new_name="New Name", new_description="New desc")

        data = svc.parse_file(file_path)
        s = data["settings"][0]
        assert s["name"] == "New Name"
        assert s["description"] == "New desc"

    def test_update_setting_not_found(self, temp_repo, mock_settings):
        """update_setting should return False for a nonexistent UID."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")

        success, msg = svc.update_setting(file_path, "{NONEXISTENT-UID}", new_value="1")
        assert not success
        assert "not found" in msg.lower()

    # ------------------------------------------------------------------
    # delete_setting
    # ------------------------------------------------------------------

    def test_delete_setting(self, temp_repo, mock_settings):
        """delete_setting should remove the entry by UID."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")
        svc.add_setting(
            file_path, name="ToDelete", hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\Test", value_name="Val", value_type="REG_SZ", value="hello",
        )

        uid = svc.parse_file(file_path)["settings"][0]["uid"]
        success, _ = svc.delete_setting(file_path, uid)
        assert success
        assert svc.parse_file(file_path)["settings"] == []

    def test_delete_setting_preserves_others(self, temp_repo, mock_settings):
        """Deleting one setting must not affect others."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")
        svc.add_setting(
            file_path, name="Keep", hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\A", value_name="VA", value_type="REG_DWORD", value="1",
        )
        svc.add_setting(
            file_path, name="Delete", hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\B", value_name="VB", value_type="REG_DWORD", value="2",
        )

        data = svc.parse_file(file_path)
        uid_to_delete = next(s["uid"] for s in data["settings"] if s["name"] == "Delete")
        svc.delete_setting(file_path, uid_to_delete)

        remaining = svc.parse_file(file_path)["settings"]
        assert len(remaining) == 1
        assert remaining[0]["name"] == "Keep"

    def test_delete_setting_not_found(self, temp_repo, mock_settings):
        """delete_setting should return False for a nonexistent UID."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")

        success, msg = svc.delete_setting(file_path, "{NONEXISTENT}")
        assert not success
        assert "not found" in msg.lower()

    # ------------------------------------------------------------------
    # get_full_path / path traversal
    # ------------------------------------------------------------------

    def test_get_full_path_resolves_under_policies(self, temp_repo, mock_settings):
        """get_full_path should resolve relative paths under policies/."""
        svc = YAMLService()
        result = svc.get_full_path("test.yaml")
        assert result == (temp_repo / "policies" / "test.yaml").resolve()

    def test_path_traversal_blocked(self, temp_repo, mock_settings):
        """get_full_path must reject paths that escape the policies/ directory."""
        svc = YAMLService()
        with pytest.raises(ValueError, match="Path traversal"):
            svc.get_full_path("../../etc/passwd")

    def test_path_traversal_absolute_blocked(self, temp_repo, mock_settings):
        """get_full_path must reject absolute paths escaping policies/."""
        svc = YAMLService()
        with pytest.raises(ValueError, match="Path traversal"):
            svc.get_full_path("/etc/passwd")

    # ------------------------------------------------------------------
    # Singleton behaviour
    # ------------------------------------------------------------------

    def test_singleton_uses_dynamic_repo_path(self, temp_repo, monkeypatch):
        """yaml_service singleton should reflect config changes at access time."""
        monkeypatch.setattr(config.settings, "repo_path", temp_repo)
        assert singleton_yaml_service.repo_path == temp_repo
        assert singleton_yaml_service.policies_path == temp_repo / "policies"

        import tempfile
        with tempfile.TemporaryDirectory() as other_dir:
            other_path = Path(other_dir)
            monkeypatch.setattr(config.settings, "repo_path", other_path)
            assert singleton_yaml_service.repo_path == other_path

    # ------------------------------------------------------------------
    # bypass_errors
    # ------------------------------------------------------------------

    def test_bypass_errors_true(self, temp_repo, mock_settings):
        """bypass_errors=True should set bypassErrors to '1'."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")
        svc.add_setting(
            file_path, name="S", hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\X", value_name="V", value_type="REG_DWORD", value="0",
            bypass_errors=True,
        )

        data = svc.parse_file(file_path)
        assert data["settings"][0]["bypassErrors"] == "1"

    def test_bypass_errors_false(self, temp_repo, mock_settings):
        """bypass_errors=False (default) should set bypassErrors to '0'."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")
        svc.add_setting(
            file_path, name="S", hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\X", value_name="V", value_type="REG_DWORD", value="0",
        )

        data = svc.parse_file(file_path)
        assert data["settings"][0]["bypassErrors"] == "0"

    # ------------------------------------------------------------------
    # Atomic write — partial failure recovery
    # ------------------------------------------------------------------

    def test_atomic_write_no_tmp_left_on_success(self, temp_repo, mock_settings):
        """No .tmp file should remain after a successful write."""
        svc = YAMLService()
        policies_dir = temp_repo / "policies"
        policies_dir.mkdir()
        file_path = policies_dir / "test.yaml"
        svc.create_file(file_path, "Col")

        tmp_path = file_path.with_suffix(".yaml.tmp")
        assert not tmp_path.exists()
