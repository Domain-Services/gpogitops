"""Tests for XML service."""

import pytest
from pathlib import Path

from app import config
from app.services.xml_service import XMLParseError, XMLService
from app.services.xml_service import xml_service as singleton_xml_service


class TestXMLService:
    """Test cases for XMLService."""

    def test_create_file(self, temp_repo, mock_settings):
        """Test creating a new GPO XML file."""
        xml = XMLService()
        file_path = temp_repo / "test.xml"

        success, message = xml.create_file(file_path, "Test Collection")

        assert success
        assert file_path.exists()
        assert "Created" in message

    def test_parse_file(self, temp_repo, mock_settings):
        """Test parsing a GPO XML file."""
        xml = XMLService()
        file_path = temp_repo / "test.xml"

        # Create a file first
        xml.create_file(file_path, "Test Collection")

        # Parse it
        data = xml.parse_file(file_path)

        assert data["collection_name"] == "Test Collection"
        assert data["settings"] == []

    def test_parse_file_raises_on_malformed_xml(self, temp_repo, mock_settings):
        """parse_file should raise XMLParseError on malformed XML."""
        xml = XMLService()
        file_path = temp_repo / "broken.xml"
        file_path.write_text("<not-closed>", encoding="utf-8")

        with pytest.raises(XMLParseError, match="Malformed XML"):
            xml.parse_file(file_path)

    def test_add_setting(self, temp_repo, mock_settings):
        """Test adding a setting to a GPO XML file."""
        xml = XMLService()
        file_path = temp_repo / "test.xml"

        # Create file
        xml.create_file(file_path, "Test Collection")

        # Add setting
        success, message = xml.add_setting(
            file_path,
            name="Test Setting",
            hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\Test",
            value_name="TestValue",
            value_type="REG_DWORD",
            value="1",
            description="Test description"
        )

        assert success
        assert "UID" in message

        # Verify it was added
        data = xml.parse_file(file_path)
        assert len(data["settings"]) == 1
        assert data["settings"][0]["name"] == "Test Setting"

    def test_add_setting_rejects_invalid_type(self, temp_repo, mock_settings):
        """add_setting should reject invalid registry value types."""
        xml = XMLService()
        file_path = temp_repo / "test.xml"
        xml.create_file(file_path, "Test Collection")

        success, message = xml.add_setting(
            file_path,
            name="Bad Type",
            hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\Test",
            value_name="TestValue",
            value_type="REG_INVALID",
            value="1",
        )
        assert not success
        assert "Invalid value_type" in message

    def test_update_setting(self, temp_repo, mock_settings):
        """Test updating an existing setting."""
        xml = XMLService()
        file_path = temp_repo / "test.xml"
        xml.create_file(file_path, "Test Collection")

        # Add a setting first
        xml.add_setting(
            file_path,
            name="Setting",
            hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\Test",
            value_name="Val",
            value_type="REG_DWORD",
            value="1",
        )

        data = xml.parse_file(file_path)
        uid = data["settings"][0]["uid"]

        # Update it
        success, msg = xml.update_setting(file_path, uid, new_value="42", new_name="Updated")
        assert success

        # Verify
        data = xml.parse_file(file_path)
        assert data["settings"][0]["properties"]["value"] == "42"
        assert data["settings"][0]["name"] == "Updated"

    def test_update_setting_not_found(self, temp_repo, mock_settings):
        """update_setting should return False for a nonexistent UID."""
        xml = XMLService()
        file_path = temp_repo / "test.xml"
        xml.create_file(file_path, "Test Collection")

        success, msg = xml.update_setting(file_path, "{NONEXISTENT-UID}", new_value="1")
        assert not success
        assert "not found" in msg.lower()

    def test_delete_setting(self, temp_repo, mock_settings):
        """Test deleting a setting."""
        xml = XMLService()
        file_path = temp_repo / "test.xml"
        xml.create_file(file_path, "Test Collection")

        xml.add_setting(
            file_path,
            name="ToDelete",
            hive="HKEY_LOCAL_MACHINE",
            key="SOFTWARE\\Test",
            value_name="Val",
            value_type="REG_SZ",
            value="hello",
        )

        data = xml.parse_file(file_path)
        uid = data["settings"][0]["uid"]

        success, msg = xml.delete_setting(file_path, uid)
        assert success

        data = xml.parse_file(file_path)
        assert len(data["settings"]) == 0

    def test_delete_setting_not_found(self, temp_repo, mock_settings):
        """delete_setting should return False for a nonexistent UID."""
        xml = XMLService()
        file_path = temp_repo / "test.xml"
        xml.create_file(file_path, "Test Collection")

        success, msg = xml.delete_setting(file_path, "{NONEXISTENT}")
        assert not success
        assert "not found" in msg.lower()

    def test_path_traversal_blocked(self, temp_repo, mock_settings):
        """get_full_path should block traversal outside repo."""
        xml = XMLService()

        with pytest.raises(ValueError, match="Path traversal"):
            xml.get_full_path("../../etc/passwd")

    def test_singleton_uses_dynamic_repo_path(self, temp_repo, monkeypatch):
        """xml_service singleton should reflect config changes without re-instantiation.

        The repo_path property reads config.settings at access time, so patching
        the setting after module load is immediately visible on the singleton.
        """
        monkeypatch.setattr(config.settings, "repo_path", temp_repo)
        assert singleton_xml_service.repo_path == temp_repo

        import tempfile
        with tempfile.TemporaryDirectory() as other_dir:
            other_path = Path(other_dir)
            monkeypatch.setattr(config.settings, "repo_path", other_path)
            assert singleton_xml_service.repo_path == other_path
