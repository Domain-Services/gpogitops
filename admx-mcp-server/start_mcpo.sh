#!/bin/bash
# Start mcpo proxy for ADMX MCP Server
# This exposes the MCP server as an OpenAPI REST endpoint for Open WebUI

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment if present; otherwise assume mcpo is on PATH
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
elif ! command -v mcpo &>/dev/null; then
    echo "ERROR: venv not found and mcpo not on PATH. Run: pip install mcpo" >&2
    exit 1
fi

# Set environment variables
export ADMX_DB_PATH="${ADMX_DB_PATH:-$SCRIPT_DIR/../ms-admx-dictionary.json}"

# Start mcpo with the ADMX MCP server
# Port 8000 by default, accessible at http://localhost:8000
# API docs at http://localhost:8000/docs
echo "Starting ADMX Policy MCP Server via mcpo..."
echo "ADMX Database: $ADMX_DB_PATH"
echo "API will be available at: http://localhost:8000"
echo "API docs at: http://localhost:8000/docs"
echo ""

mcpo --port 8000 --config mcpo_config.json
