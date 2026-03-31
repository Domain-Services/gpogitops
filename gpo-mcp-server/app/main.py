"""Main application entry point."""

import logging
import sys

from mcp.server.fastmcp import FastMCP

from app import config
from app.core import audit_event
from app.tools import register_all_tools

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)

logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP(config.settings.server_name)

# Register all tools
register_all_tools(mcp)


def run():
    """Run the MCP server."""
    # Log configuration summary and validation warnings
    config.settings.log_summary()

    if config.settings.repo_url:
        logger.info(f"GPO Repository configured: {config.settings.repo_url}")
    else:
        logger.warning("GPO Repository not configured (set GPO_REPO_URL to enable)")

    # Emit startup audit event with governance state
    audit_event(
        action="server_startup",
        status="success",
        details={
            "server": config.settings.server_name,
            "environment": config.settings.environment,
            "enforce_backend_boundary": config.settings.enforce_backend_boundary,
            "allow_direct_git_writes": config.settings.allow_direct_git_writes,
            "protected_branches": list(config.settings.protected_branches),
            "config_warnings": config.settings._warnings,
        },
    )

    logger.info(f"Starting {config.settings.server_name}")
    mcp.run()
