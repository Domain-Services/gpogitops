"""MCP Tools registration."""

from .search import register_search_tools
from .categories import register_category_tools
from .stats import register_stats_tools


def register_all_tools(mcp):
    """Register all MCP tools."""
    register_search_tools(mcp)
    register_category_tools(mcp)
    register_stats_tools(mcp)
