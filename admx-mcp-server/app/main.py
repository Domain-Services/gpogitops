"""Main application entry point."""

import sys

from mcp.server.fastmcp import FastMCP

from app.config import settings
from app.services import database_service
from app.tools import register_all_tools

# Initialize FastMCP server
mcp = FastMCP(settings.server_name)

# Register all tools
register_all_tools(mcp)


def run():
    """Run the MCP server."""
    # Pre-load database on startup; exit immediately if it cannot be found so
    # the process supervisor can report a clear failure rather than silently
    # serving a broken server.
    try:
        db = database_service.load()
        print(f"Loaded {db.get('metadata', {}).get('totalPolicies', 0)} policies", file=sys.stderr)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Set ADMX_DB_PATH to the location of ms-admx-dictionary.json", file=sys.stderr)
        sys.exit(1)

    mcp.run()
