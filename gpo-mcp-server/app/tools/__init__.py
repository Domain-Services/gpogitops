"""MCP Tools registration."""

from .sync import register_sync_tools
from .files import register_file_tools
from .settings import register_setting_tools
from .git import register_git_tools
from .workflow import register_workflow_tools


def register_all_tools(mcp):
    """Register all MCP tools."""
    register_sync_tools(mcp)
    register_file_tools(mcp)
    register_setting_tools(mcp)
    register_git_tools(mcp)
    register_workflow_tools(mcp)
