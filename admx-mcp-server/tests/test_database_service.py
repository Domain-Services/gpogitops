"""Tests for database service."""

import pytest

from app.services import database_service


class TestDatabaseService:
    """Test cases for DatabaseService."""

    def test_load_database(self, mock_db_file):
        """Test loading the policy database."""
        db = database_service.load()

        assert db["metadata"]["totalPolicies"] == 2
        assert len(db["policies"]) == 2

    def test_search_policies(self, mock_db_file):
        """Test searching policies."""
        results = database_service.search("test policy one")

        assert len(results) == 1
        assert results[0]["name"] == "TestPolicy1"

    def test_search_no_results(self, mock_db_file):
        """Test search with no matching results."""
        results = database_service.search("nonexistent")

        assert len(results) == 0

    def test_get_by_key(self, mock_db_file):
        """Test getting policies by registry key."""
        results = database_service.get_by_key("SOFTWARE\\Policies\\Test")

        assert len(results) == 1
        assert results[0]["name"] == "TestPolicy1"

    def test_get_by_name(self, mock_db_file):
        """Test getting policies by name."""
        results = database_service.get_by_name("TestPolicy1")

        assert len(results) == 1
        assert results[0]["displayName"] == "Test Policy One"

    def test_get_categories(self, mock_db_file):
        """Test getting categories."""
        categories = database_service.get_categories()

        assert len(categories) == 2
        assert ("Other/Category", 1) in categories
        assert ("Test/Category", 1) in categories

    def test_get_stats(self, mock_db_file):
        """Test getting database statistics."""
        stats = database_service.get_stats()

        assert stats["total_policies"] == 2
        assert stats["total_categories"] == 2
        assert stats["version"] == "1.0.0"
