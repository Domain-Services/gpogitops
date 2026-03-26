"""File management tools."""

from app.services.yaml_service import yaml_service
from app.core import format_gpo_setting


def register_file_tools(mcp):
    """Register file-related MCP tools."""

    @mcp.tool()
    def gpo_list_files(
        filter_pattern: str = "",
        offset: int = 0,
        limit: int = 50
    ) -> str:
        """
        List all GPO policy files in the repository.

        Args:
            filter_pattern: Optional pattern to filter file names
            offset: Number of files to skip (for pagination)
            limit: Maximum number of files to return (default 50, max 200)

        Returns:
            List of GPO YAML policy files
        """
        policies_path = yaml_service.policies_path

        if not policies_path.exists():
            return "ERROR: Policies directory not found. Use gpo_sync_repo() first."

        # Validate pagination parameters
        offset = max(0, offset)
        limit = max(1, min(limit, 200))

        yaml_files = list(policies_path.rglob("*.yaml"))

        if filter_pattern:
            filter_lower = filter_pattern.lower()
            yaml_files = [f for f in yaml_files if filter_lower in f.name.lower()]

        if not yaml_files:
            return "No GPO policy files found"

        total_files = len(yaml_files)
        sorted_files = sorted(yaml_files)
        paginated_files = sorted_files[offset:offset + limit]

        output = [
            f"# GPO Policy Files ({len(paginated_files)} shown, {total_files} total)",
            f"**Page:** Showing {offset + 1}-{offset + len(paginated_files)} of {total_files}",
            ""
        ]

        for f in paginated_files:
            rel_path = f.relative_to(policies_path)
            output.append(f"- `{rel_path}`")

        if offset + limit < total_files:
            output.append("")
            output.append(f"Use `gpo_list_files(offset={offset + limit}, limit={limit})` to see more")

        return "\n".join(output)

    @mcp.tool()
    def gpo_get_file(file_path: str) -> str:
        """
        Get detailed contents of a GPO policy file.

        Args:
            file_path: Path to the GPO YAML policy file (relative to the policies/ directory)

        Returns:
            Parsed GPO settings from the file
        """
        svc = yaml_service
        full_path = svc.get_full_path(file_path)

        if not full_path.exists():
            return f"ERROR: File not found: {file_path}"

        try:
            data = svc.parse_file(full_path)

            output = [
                f"# {data['collection_name']}",
                f"**File:** `{data['file']}`",
            ]
            if data.get("ou"):
                output.append(f"**OU:** `{data['ou']}`")
            output.append(f"**Settings:** {len(data['settings'])}")
            output.append("")

            for setting in data["settings"]:
                output.append(format_gpo_setting(setting))
                output.append("")
                output.append("---")
                output.append("")

            return "\n".join(output)

        except Exception as e:
            return f"ERROR: Error parsing file: {str(e)}"

    @mcp.tool()
    def gpo_create_file(
        file_path: str,
        collection_name: str,
        ou: str = "",
        description: str = "",
    ) -> str:
        """
        Create a new GPO policy file with an empty collection.

        Args:
            file_path: Path for the new YAML policy file (relative to the policies/ directory,
                       e.g. "workstations-security-baseline.yaml")
            collection_name: Name for the GPO collection
            ou: Organisational Unit this policy targets (e.g. "Workstations")
            description: Optional free-text description of this policy

        Returns:
            Status of the creation
        """
        svc = yaml_service
        full_path = svc.get_full_path(file_path)

        if full_path.exists():
            return f"ERROR: File already exists: {file_path}"

        success, message = svc.create_file(full_path, collection_name, ou=ou, description=description)
        return f"OK: {message}" if success else f"ERROR: {message}"
