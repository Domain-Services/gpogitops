"""GPO settings management tools."""

import logging
from pathlib import Path

from app import config
from app.services.yaml_service import YAMLParseError, yaml_service
from app.core import format_gpo_setting

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory mtime-based parse cache for gpo_search_settings
# ---------------------------------------------------------------------------
# Maps absolute file Path → (mtime_float, parsed_data_dict).
# Process-lifetime; no eviction needed — the cache automatically invalidates
# stale entries by comparing stored mtime against the file's current mtime.
_search_cache: dict[Path, tuple[float, dict]] = {}

_VALID_HIVES = {
    "HKEY_LOCAL_MACHINE": "HKEY_LOCAL_MACHINE",
    "HKLM": "HKEY_LOCAL_MACHINE",
    "HKEY_CURRENT_USER": "HKEY_CURRENT_USER",
    "HKCU": "HKEY_CURRENT_USER",
    "HKEY_CLASSES_ROOT": "HKEY_CLASSES_ROOT",
    "HKCR": "HKEY_CLASSES_ROOT",
    "HKEY_USERS": "HKEY_USERS",
    "HKU": "HKEY_USERS",
    "HKEY_CURRENT_CONFIG": "HKEY_CURRENT_CONFIG",
    "HKCC": "HKEY_CURRENT_CONFIG",
}


def register_setting_tools(mcp):
    """Register setting-related MCP tools."""

    @mcp.tool()
    def gpo_search_settings(query: str, max_results: int = 20) -> str:
        """
        Search for GPO settings across all policy files.

        Args:
            query: Search text (searches name, description, registry key)
            max_results: Maximum number of results to return

        Returns:
            Matching GPO settings
        """
        max_results = max(1, min(max_results, 100))
        policies_path = yaml_service.policies_path

        if not policies_path.exists():
            return "ERROR: Policies directory not found. Use gpo_sync_repo() first."

        svc = yaml_service
        query_lower = query.lower()
        results = []
        found_enough = False

        for yaml_file in policies_path.rglob("*.yaml"):
            if found_enough:
                break

            try:
                # Use mtime cache to avoid re-parsing unchanged files on every call.
                try:
                    current_mtime = yaml_file.stat().st_mtime
                except OSError:
                    current_mtime = None

                cached_mtime, cached_data = _search_cache.get(yaml_file, (None, None))
                if current_mtime is not None and cached_mtime == current_mtime and cached_data is not None:
                    data = cached_data
                else:
                    data = svc.parse_file(yaml_file)
                    if current_mtime is not None:
                        _search_cache[yaml_file] = (current_mtime, data)

                for setting in data["settings"]:
                    search_text = (
                        setting.get("name", "") + " " +
                        setting.get("description", "") + " " +
                        setting.get("properties", {}).get("key", "") + " " +
                        setting.get("properties", {}).get("name", "")
                    ).lower()

                    if query_lower in search_text:
                        setting["_file"] = str(yaml_file.relative_to(policies_path))
                        results.append(setting)

                        if len(results) >= max_results:
                            found_enough = True
                            break
            except (YAMLParseError, ValueError, KeyError) as e:
                # Log malformed files instead of silently skipping them
                logger.warning("Skipping unparseable file %s: %s", yaml_file, e)
                continue

        if not results:
            return f"No settings found matching '{query}'"

        output = [f"# Found {len(results)} settings matching '{query}'", ""]

        for setting in results:
            output.append(f"**File:** `{setting['_file']}`")
            output.append(format_gpo_setting(setting))
            output.append("")
            output.append("---")
            output.append("")

        return "\n".join(output)

    @mcp.tool()
    def gpo_update_setting(
        file_path: str,
        setting_uid: str,
        new_value: str = "",
        new_name: str = "",
        new_description: str = ""
    ) -> str:
        """
        Update a GPO setting in a policy file.

        Args:
            file_path: Path to the GPO policy file (relative to the policies/ directory)
            setting_uid: The UID of the setting to update
            new_value: New registry value (leave empty to keep current)
            new_name: New setting name (leave empty to keep current)
            new_description: New description (leave empty to keep current)

        Returns:
            Status of the update operation
        """
        svc = yaml_service
        full_path = svc.get_full_path(file_path)

        if not full_path.exists():
            return f"ERROR: File not found: {file_path}"

        success, message = svc.update_setting(
            full_path,
            setting_uid,
            new_value=new_value if new_value else None,
            new_name=new_name if new_name else None,
            new_description=new_description if new_description else None
        )

        return f"OK: {message}" if success else f"ERROR: {message}"

    @mcp.tool()
    def gpo_add_setting(
        file_path: str,
        name: str,
        registry_key: str,
        value_name: str,
        value_type: str,
        value: str,
        description: str = "",
        bypass_errors: bool = False
    ) -> str:
        """
        Add a new GPO setting to a policy file.

        Args:
            file_path: Path to the GPO policy file (relative to the policies/ directory)
            name: Display name for the setting
            registry_key: Full registry key (e.g., "HKEY_LOCAL_MACHINE\\SOFTWARE\\...")
            value_name: Registry value name
            value_type: Registry type (REG_DWORD, REG_SZ, REG_EXPAND_SZ, REG_BINARY,
                        REG_MULTI_SZ, REG_QWORD, REG_DWORD_BIG_ENDIAN)
            value: The value to set
            description: Optional description
            bypass_errors: Whether GPO should continue applying on error (default False)

        Returns:
            Status of the add operation
        """
        svc = yaml_service
        full_path = svc.get_full_path(file_path)

        if not full_path.exists():
            return f"ERROR: File not found: {file_path}"

        # Parse registry key into hive and subkey
        hive = None
        key = registry_key

        for hive_name, full_hive in _VALID_HIVES.items():
            if registry_key.startswith(hive_name + "\\"):
                hive = full_hive
                key = registry_key[len(hive_name) + 1:]
                break
            elif registry_key.startswith(hive_name):
                hive = full_hive
                key = registry_key[len(hive_name):]
                if key.startswith("\\"):
                    key = key[1:]
                break

        if not hive:
            return f"ERROR: Invalid registry hive. Must start with one of: {', '.join(_VALID_HIVES.keys())}"

        success, message = svc.add_setting(
            full_path, name, hive, key, value_name, value_type, value, description,
            bypass_errors=bypass_errors
        )

        return f"OK: {message}" if success else f"ERROR: {message}"

    @mcp.tool()
    def gpo_delete_setting(file_path: str, setting_uid: str) -> str:
        """
        Delete a GPO setting from a policy file.

        Args:
            file_path: Path to the GPO policy file (relative to the policies/ directory)
            setting_uid: The UID of the setting to delete

        Returns:
            Status of the delete operation
        """
        svc = yaml_service
        full_path = svc.get_full_path(file_path)

        if not full_path.exists():
            return f"ERROR: File not found: {file_path}"

        success, message = svc.delete_setting(full_path, setting_uid)
        return f"OK: {message}" if success else f"ERROR: {message}"
