"""YAML-based GPO policy service — source-of-truth layer.

YAML files under ``repo_path/policies/`` are the single source of truth for GPO
settings.  XML is a *generated* deployment artifact produced by ``scripts/gpo_convert.py``
and never committed to the repository.

The public API mirrors ``xml_service.XMLService`` so that all MCP tools can swap
``xml_service`` for ``yaml_service`` with minimal changes.  The ``parse_file()`` return
value uses the same dict shape so ``format_gpo_setting()`` requires zero changes.

YAML policy file schema
-----------------------
::

    collection_name: "Workstations Security Baseline"
    ou: "Workstations"
    description: "Optional free-text description"

    settings:
      - uid: "{A1B2C3D4-0001-0001-0001-000000000001}"   # auto-generated on add
        name: DisableAutorun
        description: "Prevent autorun on all drive types"
        bypass_errors: false
        properties:
          action: U
          hive: HKEY_LOCAL_MACHINE
          key: "SOFTWARE\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Policies\\\\Explorer"
          value_name: NoDriveTypeAutoRun
          value_type: REG_DWORD
          value: "255"
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

import yaml

from app import config

logger = logging.getLogger(__name__)

# Mirrors xml_service.VALID_VALUE_TYPES — kept in sync manually.
VALID_VALUE_TYPES = frozenset({
    "REG_SZ",
    "REG_EXPAND_SZ",
    "REG_BINARY",
    "REG_DWORD",
    "REG_DWORD_BIG_ENDIAN",
    "REG_MULTI_SZ",
    "REG_QWORD",
})

VALID_HIVES = frozenset({
    "HKEY_LOCAL_MACHINE",
    "HKEY_CURRENT_USER",
    "HKEY_CLASSES_ROOT",
    "HKEY_USERS",
    "HKEY_CURRENT_CONFIG",
})


class YAMLParseError(Exception):
    """Raised when a YAML policy file cannot be parsed or fails schema validation."""


class YAMLService:
    """Service for YAML-based GPO policy file operations.

    All YAML files live under ``repo_path / "policies"`` and carry the ``.yaml``
    extension.  Each file represents one GPO collection (i.e. one Group Policy Object).
    """

    @property
    def repo_path(self) -> Path:
        """Read repo_path dynamically so config patches in tests are reflected."""
        return config.settings.repo_path

    @property
    def policies_path(self) -> Path:
        """Absolute path to the policies directory inside the repository."""
        return self.repo_path / "policies"

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def get_full_path(self, relative_path: str) -> Path:
        """Resolve *relative_path* under ``policies/``, reject path traversal.

        Accepts paths relative to the *policies* directory (not the repo root),
        e.g. ``"workstations-security-baseline.yaml"`` or
        ``"subdir/my-policy.yaml"``.
        """
        policies = self.policies_path
        full_path = (policies / relative_path).resolve()
        try:
            full_path.relative_to(policies.resolve())
        except ValueError:
            logger.error("Path traversal detected: %s", relative_path)
            raise ValueError(f"Path traversal detected: {relative_path}")
        return full_path

    # ------------------------------------------------------------------
    # Internal I/O helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_yaml(file_path: Path) -> dict:
        """Load a YAML file and return its contents as a dict.

        Raises ``YAMLParseError`` on malformed YAML so callers can distinguish
        a parse failure from an empty file.
        """
        try:
            with file_path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise YAMLParseError(f"Malformed YAML in {file_path.name}: {exc}") from exc

        if data is None:
            return {}
        if not isinstance(data, dict):
            raise YAMLParseError(f"YAML file {file_path.name} must be a mapping at the top level")
        return data

    @staticmethod
    def _write_yaml_atomic(data: dict, file_path: Path) -> None:
        """Write a dict as YAML atomically using a temp file + rename.

        Uses the same temp-then-replace pattern as ``xml_service._write_xml_atomic()``
        to prevent partial writes from corrupting the target file.
        """
        tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                yaml.dump(
                    data,
                    fh,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )
            os.replace(tmp_path, file_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------
    # Public API — mirrors XMLService
    # ------------------------------------------------------------------

    def parse_file(self, file_path: Path) -> dict:
        """Parse a YAML policy file and return a structured dict.

        The returned dict has the same shape as ``xml_service.parse_file()``
        so that ``format_gpo_setting()`` and search tools work unchanged::

            {
              "file": "workstations-security-baseline.yaml",
              "collection_name": "Workstations Security Baseline",
              "ou": "Workstations",
              "settings": [
                {
                  "uid": "{...}",
                  "name": "DisableAutorun",
                  "description": "...",
                  "bypass_errors": "0",
                  "properties": {
                    "action": "U",
                    "hive": "HKEY_LOCAL_MACHINE",
                    "key": "SOFTWARE\\\\...",
                    "name": "NoDriveTypeAutoRun",
                    "type": "REG_DWORD",
                    "value": "255",
                    "displayDecimal": "1",
                    "default": "0",
                  }
                },
                ...
              ]
            }

        Raises ``YAMLParseError`` on malformed YAML.
        """
        raw = self._load_yaml(file_path)

        result: dict[str, Any] = {
            "file": file_path.name,
            "collection_name": str(raw.get("collection_name", "")),
            "ou": str(raw.get("ou", "")),
            "settings": [],
        }

        for s in raw.get("settings", []) or []:
            if not isinstance(s, dict):
                continue

            props_raw = s.get("properties", {}) or {}
            # Normalise: YAML uses `value_name` as a human-friendly alias; the internal
            # dict and format_gpo_setting() expect the XML attribute name `name`.
            props: dict[str, str] = {
                "action": str(props_raw.get("action", "U")),
                "hive": str(props_raw.get("hive", "")),
                "key": str(props_raw.get("key", "")),
                "name": str(props_raw.get("value_name", props_raw.get("name", ""))),
                "type": str(props_raw.get("value_type", props_raw.get("type", ""))),
                "value": str(props_raw.get("value", "")),
                "displayDecimal": str(props_raw.get("displayDecimal", "1")),
                "default": str(props_raw.get("default", "0")),
            }

            setting: dict[str, Any] = {
                "uid": str(s.get("uid", "")),
                "name": str(s.get("name", "")),
                "status": str(props.get("name", "")),  # mirrors xml_service behaviour
                "description": str(s.get("description", "")),
                "changed": str(s.get("changed", "")),
                "clsid": "",   # not stored in YAML; injected by gpo_convert.py
                "image": "12",
                "bypassErrors": "1" if s.get("bypass_errors") else "0",
                "properties": props,
            }
            result["settings"].append(setting)

        return result

    def create_file(
        self,
        file_path: Path,
        collection_name: str,
        ou: str = "",
        description: str = "",
    ) -> tuple[bool, str]:
        """Create a new empty YAML policy file."""
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)

            data: dict = {
                "collection_name": collection_name,
                "ou": ou,
                "description": description,
                "settings": [],
            }
            self._write_yaml_atomic(data, file_path)
            logger.info("Created new YAML policy file: %s", file_path)
            return True, f"Created new policy file: {file_path}"
        except Exception as exc:
            logger.error("Error creating YAML file %s: %s", file_path, exc)
            return False, f"Error creating policy file: {exc}"

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
        bypass_errors: bool = False,
    ) -> tuple[bool, str]:
        """Append a new setting to a YAML policy file.

        A fresh UUID is generated automatically so callers never need to supply
        a ``uid``.
        """
        if value_type not in VALID_VALUE_TYPES:
            return False, (
                f"Invalid value_type '{value_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_VALUE_TYPES))}"
            )

        try:
            raw = self._load_yaml(file_path)
            if "settings" not in raw or raw["settings"] is None:
                raw["settings"] = []

            new_uid = "{" + str(uuid.uuid4()).upper() + "}"
            new_setting: dict = {
                "uid": new_uid,
                "name": name,
                "description": description,
                "bypass_errors": bypass_errors,
                "properties": {
                    "action": "U",
                    "hive": hive,
                    "key": key,
                    "value_name": value_name,
                    "value_type": value_type,
                    "value": str(value),
                },
            }
            raw["settings"].append(new_setting)
            self._write_yaml_atomic(raw, file_path)
            logger.info("Added new setting '%s' to %s with UID %s", name, file_path, new_uid)
            return True, f"New setting added with UID: {new_uid}"
        except Exception as exc:
            logger.error("Error adding setting to %s: %s", file_path, exc)
            return False, f"Error adding setting: {exc}"

    def update_setting(
        self,
        file_path: Path,
        setting_uid: str,
        new_value: str | None = None,
        new_name: str | None = None,
        new_description: str | None = None,
    ) -> tuple[bool, str]:
        """Update fields on an existing setting identified by *setting_uid*."""
        try:
            raw = self._load_yaml(file_path)
            settings = raw.get("settings") or []

            for s in settings:
                if not isinstance(s, dict):
                    continue
                if str(s.get("uid", "")) == setting_uid:
                    if new_name is not None:
                        s["name"] = new_name
                    if new_description is not None:
                        s["description"] = new_description
                    if new_value is not None:
                        props = s.setdefault("properties", {})
                        props["value"] = new_value

                    self._write_yaml_atomic(raw, file_path)
                    logger.info("Setting %s updated in %s", setting_uid, file_path)
                    return True, f"Setting {setting_uid} updated successfully"

            logger.warning("Setting UID %s not found in %s", setting_uid, file_path)
            return False, f"Setting with UID {setting_uid} not found"
        except Exception as exc:
            logger.error("Error updating setting in %s: %s", file_path, exc)
            return False, f"Error updating setting: {exc}"

    def delete_setting(self, file_path: Path, setting_uid: str) -> tuple[bool, str]:
        """Delete a setting from a YAML policy file by *setting_uid*."""
        try:
            raw = self._load_yaml(file_path)
            settings = raw.get("settings") or []

            original_len = len(settings)
            raw["settings"] = [
                s for s in settings
                if not (isinstance(s, dict) and str(s.get("uid", "")) == setting_uid)
            ]

            if len(raw["settings"]) == original_len:
                logger.warning("Setting UID %s not found in %s", setting_uid, file_path)
                return False, f"Setting with UID {setting_uid} not found"

            self._write_yaml_atomic(raw, file_path)
            logger.info("Setting %s deleted from %s", setting_uid, file_path)
            return True, f"Setting {setting_uid} deleted"
        except Exception as exc:
            logger.error("Error deleting setting from %s: %s", file_path, exc)
            return False, f"Error: {exc}"


# Singleton — reused across tool calls for consistency with xml_service pattern.
yaml_service = YAMLService()
