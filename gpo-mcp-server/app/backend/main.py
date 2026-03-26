"""Backend API entrypoint."""

import logging
import sys

from app.backend.http_server import run_server


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)


def run() -> None:
    """Run backend API service."""
    run_server()
