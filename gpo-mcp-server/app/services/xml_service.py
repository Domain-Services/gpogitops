"""XML parsing and manipulation service for GPO files."""

import logging
import os
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from app import config

logger = logging.getLogger(__name__)

# Valid registry value types for GPO settings
VALID_VALUE_TYPES = frozenset({
    "REG_SZ",
    "REG_EXPAND_SZ",
    "REG_BINARY",
    "REG_DWORD",
    "REG_DWORD_BIG_ENDIAN",
    "REG_MULTI_SZ",
    "REG_QWORD",
})


class XMLParseError(Exception):
    """Raised when an XML file cannot be parsed."""


class XMLService:
    """Service for GPO XML file operations."""

    # GPO XML CLSID constants
    # Registry setting CLSID for Group Policy Preferences
    REGISTRY_CLSID = "{9CD4B2F4-923D-47f5-A062-E897DD1DAD50}"
    # Collection CLSID for Registry settings collection
    COLLECTION_CLSID = "{53B533F5-224C-47e3-B01B-CA3B3F3FF4BF}"

    @property
    def repo_path(self) -> Path:
        """Read repo_path dynamically so the singleton reflects config changes.

        All other services re-read ``config.settings`` on each instantiation;
        this property gives the singleton the same behaviour without forcing a
        new instance on every call.
        """
        return config.settings.repo_path

    @staticmethod
    def _write_xml_atomic(tree: ET.ElementTree, file_path: Path) -> None:
        """Write an XML tree atomically using a temp file + rename.

        This prevents partial writes from corrupting the target file if the
        process is interrupted mid-write.
        """
        tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        try:
            tree.write(str(tmp_path), encoding="utf-8", xml_declaration=True)
            os.replace(tmp_path, file_path)  # atomic on POSIX; best-effort on Windows
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def get_full_path(self, relative_path: str) -> Path:
        """Get full path from relative path, ensuring it's within repo."""
        full_path = (self.repo_path / relative_path).resolve()
        try:
            full_path.relative_to(self.repo_path.resolve())
        except ValueError:
            logger.error(f"Path traversal detected: {relative_path}")
            raise ValueError(f"Path traversal detected: {relative_path}")
        return full_path

    def parse_file(self, file_path: Path) -> dict:
        """Parse a GPO XML file and return structured data.

        Raises ``XMLParseError`` when the file is malformed so callers can
        distinguish a genuinely empty file from a parse failure.

        Note: We only parse files from our controlled repository to mitigate
        XXE attacks. Path traversal is prevented by get_full_path().
        """
        try:
            tree = ET.parse(file_path)
        except ET.ParseError as exc:
            raise XMLParseError(f"Malformed XML in {file_path.name}: {exc}") from exc

        root = tree.getroot()

        result = {
            "file": str(file_path.name),
            "collection_name": root.get("name", ""),
            "collection_clsid": root.get("clsid", ""),
            "settings": []
        }

        for registry in root.findall(".//Registry"):
            setting = {
                "uid": registry.get("uid", ""),
                "name": registry.get("name", ""),
                "status": registry.get("status", ""),
                "description": registry.get("desc", ""),
                "changed": registry.get("changed", ""),
                "clsid": registry.get("clsid", ""),
                "image": registry.get("image", ""),
                "bypassErrors": registry.get("bypassErrors", "0"),
            }

            # Parse Properties
            props = registry.find("Properties")
            if props is not None:
                setting["properties"] = {
                    "action": props.get("action", ""),
                    "hive": props.get("hive", ""),
                    "key": props.get("key", ""),
                    "name": props.get("name", ""),
                    "type": props.get("type", ""),
                    "value": props.get("value", ""),
                    "displayDecimal": props.get("displayDecimal", "0"),
                    "default": props.get("default", ""),
                }

            # Parse Filters
            filters = []
            for filter_elem in registry.findall(".//FilterOs"):
                filters.append({
                    "bool": filter_elem.get("bool", ""),
                    "not": filter_elem.get("not", ""),
                    "class": filter_elem.get("class", ""),
                    "version": filter_elem.get("version", ""),
                    "type": filter_elem.get("type", ""),
                    "edition": filter_elem.get("edition", ""),
                    "sp": filter_elem.get("sp", ""),
                })
            if filters:
                setting["filters"] = filters

            result["settings"].append(setting)

        return result

    def update_setting(
        self,
        file_path: Path,
        setting_uid: str,
        new_value: str | None = None,
        new_name: str | None = None,
        new_description: str | None = None
    ) -> tuple[bool, str]:
        """Update a setting in a GPO XML file."""
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            for registry in root.findall(".//Registry"):
                if registry.get("uid") == setting_uid:
                    # Update timestamp
                    registry.set("changed", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

                    if new_name:
                        registry.set("name", new_name)

                    if new_description:
                        registry.set("desc", new_description)

                    if new_value is not None:
                        props = registry.find("Properties")
                        if props is not None:
                            props.set("value", new_value)

                    self._write_xml_atomic(tree, file_path)
                    logger.info(f"Setting {setting_uid} updated successfully in {file_path}")
                    return True, f"Setting {setting_uid} updated successfully"

            logger.warning(f"Setting with UID {setting_uid} not found in {file_path}")
            return False, f"Setting with UID {setting_uid} not found"

        except Exception as e:
            logger.error(f"Error updating GPO XML {file_path}: {str(e)}")
            return False, f"Error updating GPO XML: {str(e)}"

    def add_setting(
        self,
        file_path: Path,
        name: str,
        hive: str,
        key: str,
        value_name: str,
        value_type: str,
        value: str,
        description: str = "",
        bypass_errors: bool = False
    ) -> tuple[bool, str]:
        """Add a new setting to a GPO XML file."""
        # Validate registry value type before touching the file
        if value_type not in VALID_VALUE_TYPES:
            return False, (
                f"Invalid value_type '{value_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_VALUE_TYPES))}"
            )

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            new_uid = "{" + str(uuid.uuid4()).upper() + "}"

            registry = ET.SubElement(root, "Registry")
            registry.set("clsid", self.REGISTRY_CLSID)
            registry.set("name", name)
            registry.set("status", value_name)
            registry.set("image", "12")
            registry.set("changed", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            registry.set("uid", new_uid)
            registry.set("desc", description)
            registry.set("bypassErrors", "1" if bypass_errors else "0")

            props = ET.SubElement(registry, "Properties")
            props.set("action", "U")
            props.set("displayDecimal", "1")
            props.set("default", "0")
            props.set("hive", hive)
            props.set("key", key)
            props.set("name", value_name)
            props.set("type", value_type)
            props.set("value", value)

            self._write_xml_atomic(tree, file_path)
            logger.info(f"New setting added to {file_path} with UID: {new_uid}")
            return True, f"New setting added with UID: {new_uid}"

        except Exception as e:
            logger.error(f"Error adding setting to {file_path}: {str(e)}")
            return False, f"Error adding setting: {str(e)}"

    def delete_setting(self, file_path: Path, setting_uid: str) -> tuple[bool, str]:
        """Delete a setting from a GPO XML file."""
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            # Build a child->parent map so we can remove elements at any depth,
            # not just direct children of root (root.remove() only works for
            # direct children and raises ValueError otherwise).
            parent_map = {child: parent for parent in tree.iter() for child in parent}

            for registry in root.findall(".//Registry"):
                if registry.get("uid") == setting_uid:
                    parent = parent_map.get(registry, root)
                    parent.remove(registry)
                    self._write_xml_atomic(tree, file_path)
                    logger.info(f"Setting {setting_uid} deleted from {file_path}")
                    return True, f"Setting {setting_uid} deleted"

            logger.warning(f"Setting with UID {setting_uid} not found in {file_path}")
            return False, f"Setting with UID {setting_uid} not found"

        except Exception as e:
            logger.error(f"Error deleting setting from {file_path}: {str(e)}")
            return False, f"Error: {str(e)}"

    def create_file(self, file_path: Path, collection_name: str) -> tuple[bool, str]:
        """Create a new GPO XML file with an empty collection."""
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)

            root = ET.Element("Collection")
            root.set("clsid", self.COLLECTION_CLSID)
            root.set("name", collection_name)

            tree = ET.ElementTree(root)
            self._write_xml_atomic(tree, file_path)

            logger.info(f"Created new GPO file: {file_path}")
            return True, f"Created new GPO file: {file_path}"

        except Exception as e:
            logger.error(f"Error creating file {file_path}: {str(e)}")
            return False, f"Error creating file: {str(e)}"


# Singleton instance - reuse across tool calls instead of constructing per-call
xml_service = XMLService()
