"""Pytest fixtures for GPO MCP Server tests."""

import pytest
from pathlib import Path
import tempfile
import os


@pytest.fixture
def temp_repo():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_settings(temp_repo, monkeypatch):
    """Mock settings with temporary paths."""
    monkeypatch.setenv("GPO_REPO_PATH", str(temp_repo))
    monkeypatch.setenv("GPO_REPO_URL", "https://github.com/test/repo")

    # Build a fresh Settings object that reflects the new env vars.
    from app import config
    new_settings = config.Settings.from_env()

    # Patch settings everywhere it was imported directly (modules hold their
    # own reference to the object created at import time).  monkeypatch.setattr
    # ensures all patches are undone automatically after each test.
    monkeypatch.setattr(config, "settings", new_settings)

    # xml_service.repo_path is now a @property that reads config.settings.repo_path
    # dynamically, so no separate patch is required — patching config.settings above
    # is sufficient.

    yield new_settings
