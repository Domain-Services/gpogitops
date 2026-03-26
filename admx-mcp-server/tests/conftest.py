"""Pytest fixtures for ADMX Policy MCP Server tests."""

import pytest
import json
import tempfile
from pathlib import Path


@pytest.fixture
def sample_policy_db():
    """Create a sample policy database for testing."""
    return {
        "metadata": {
            "totalPolicies": 2,
            "totalFiles": 1,
            "exportDate": "2024-01-01",
            "version": "1.0.0"
        },
        "policies": [
            {
                "namespace": "Microsoft.Policies.Test",
                "name": "TestPolicy1",
                "displayName": "Test Policy One",
                "key": "SOFTWARE\\Policies\\Test",
                "valueName": "TestValue",
                "class": "Machine",
                "categoryPathDisplay": "Test/Category",
                "searchText": "test policy one software policies",
                "explainText": "This is a test policy"
            },
            {
                "namespace": "Microsoft.Policies.Test",
                "name": "TestPolicy2",
                "displayName": "Test Policy Two",
                "key": "SOFTWARE\\Policies\\Other",
                "valueName": "OtherValue",
                "class": "User",
                "categoryPathDisplay": "Other/Category",
                "searchText": "test policy two other category",
                "explainText": "Another test policy"
            }
        ],
        "index": {
            "byKey": {
                "software\\policies\\test": ["Microsoft.Policies.Test::TestPolicy1"],
                "software\\policies\\other": ["Microsoft.Policies.Test::TestPolicy2"]
            },
            "byCategory": {
                "Test/Category": ["Microsoft.Policies.Test::TestPolicy1"],
                "Other/Category": ["Microsoft.Policies.Test::TestPolicy2"]
            },
            "byCategoryLower": {
                "test/category": ["Microsoft.Policies.Test::TestPolicy1"],
                "other/category": ["Microsoft.Policies.Test::TestPolicy2"]
            },
            "byFileName": {
                "test.admx": ["Microsoft.Policies.Test::TestPolicy1", "Microsoft.Policies.Test::TestPolicy2"]
            }
        }
    }


@pytest.fixture
def mock_db_file(sample_policy_db, monkeypatch):
    """Create a temporary database file and mock settings."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(sample_policy_db, f)
        db_path = Path(f.name)

    monkeypatch.setenv("ADMX_DB_PATH", str(db_path))

    # Build a fresh Settings object that reflects the new env var.
    from app import config
    new_settings = config.Settings.from_env()

    # Patch the settings in the config module AND in database_service (which
    # imported `settings` directly at module load time and holds its own
    # reference).  Using monkeypatch.setattr ensures both are restored after
    # each test automatically.
    monkeypatch.setattr(config, "settings", new_settings)

    # Reset database service cache so it reloads from the new path
    from app.services.database_service import database_service as _svc
    _svc._db = None
    _svc._policies_by_id = {}

    yield db_path

    db_path.unlink()
