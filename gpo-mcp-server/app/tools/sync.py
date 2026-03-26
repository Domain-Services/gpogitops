"""Repository sync tools."""

from app.services import GitService


def register_sync_tools(mcp):
    """Register sync-related MCP tools."""

    @mcp.tool()
    def gpo_sync_repo() -> str:
        """
        Sync the GPO repository from GitHub.
        Clone if not exists, pull latest changes if exists.

        Returns:
            Status message about the sync operation
        """
        git = GitService()
        success, message = git.clone_or_pull()
        return f"OK: {message}" if success else f"ERROR: {message}"
