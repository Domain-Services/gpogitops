"""ADMX Policy database service."""

import json
from typing import Any

from app import config


class DatabaseService:
    """Service for ADMX policy database operations."""

    def __init__(self):
        self._db: dict[str, Any] | None = None
        self._policies_by_id: dict[str, dict] = {}

    def load(self) -> dict[str, Any]:
        """Load the policy database from JSON file."""
        if self._db is not None:
            return self._db

        db_path = config.settings.get_db_path()

        if not db_path.exists():
            raise FileNotFoundError(f"Policy database not found at {db_path}")

        with open(db_path, "r", encoding="utf-8-sig") as f:
            self._db = json.load(f)

        # Build policy lookup by ID
        for policy in self._db.get("policies", []):
            policy_id = f"{policy.get('namespace', '')}::{policy.get('name', '')}"
            self._policies_by_id[policy_id] = policy

        return self._db

    @property
    def db(self) -> dict[str, Any]:
        """Get the loaded database."""
        return self.load()

    @property
    def policies_by_id(self) -> dict[str, dict]:
        """Get policies indexed by ID."""
        self.load()  # Ensure DB is loaded
        return self._policies_by_id

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        """Search policies by text."""
        query_lower = query.lower()
        results = []

        for policy in self.db.get("policies", []):
            search_text = policy.get("searchText", "")
            if query_lower in search_text:
                results.append(policy)
                if len(results) >= max_results:
                    break

        return results

    def get_by_key(self, registry_key: str) -> list[dict]:
        """Find policies by registry key."""
        key_lower = registry_key.lower().replace("/", "\\")
        by_key = self.db.get("index", {}).get("byKey", {})

        policy_ids = by_key.get(key_lower, [])

        if not policy_ids:
            for key, ids in by_key.items():
                if key_lower in key or key in key_lower:
                    policy_ids.extend(ids)

        # Remove duplicates
        seen = set()
        unique_ids = []
        for pid in policy_ids:
            if pid not in seen:
                seen.add(pid)
                unique_ids.append(pid)

        return [self._policies_by_id[pid] for pid in unique_ids if pid in self._policies_by_id]

    def get_by_name(self, name: str) -> list[dict]:
        """Find policies by name."""
        name_lower = name.lower()

        # Exact match first
        for policy in self.db.get("policies", []):
            if (policy.get("name", "").lower() == name_lower or
                policy.get("displayName", "").lower() == name_lower):
                return [policy]

        # Partial match
        matches = []
        for policy in self.db.get("policies", []):
            if (name_lower in policy.get("name", "").lower() or
                name_lower in policy.get("displayName", "").lower()):
                matches.append(policy)

        return matches

    def get_categories(self, filter_text: str = "") -> list[tuple[str, int]]:
        """Get categories with policy counts."""
        by_category = self.db.get("index", {}).get("byCategory", {})
        filter_lower = filter_text.lower()

        categories = []
        for cat_name, policy_ids in sorted(by_category.items()):
            if not filter_text or filter_lower in cat_name.lower():
                categories.append((cat_name, len(policy_ids)))

        return categories

    def get_by_category(self, category: str) -> tuple[str, list[dict]]:
        """Get policies in a category. Returns (actual_category_name, policies)."""
        by_category = self.db.get("index", {}).get("byCategory", {})
        by_category_lower = self.db.get("index", {}).get("byCategoryLower", {})

        # Use a separate variable for the resolved name to avoid mutating the parameter.
        resolved_category = category
        policy_ids = by_category.get(category, [])

        if not policy_ids:
            lower_key = category.lower()
            policy_ids = by_category_lower.get(lower_key, [])
            if policy_ids:
                # Resolve canonical name from byCategory using the lower key
                for cat_name in by_category:
                    if cat_name.lower() == lower_key:
                        resolved_category = cat_name
                        break

        if not policy_ids:
            for cat_name, ids in by_category.items():
                if category.lower() in cat_name.lower():
                    policy_ids = ids
                    resolved_category = cat_name
                    break

        policies = [self._policies_by_id[pid] for pid in policy_ids if pid in self._policies_by_id]
        return resolved_category, policies

    def get_by_registry_value(self, value_name: str) -> list[dict]:
        """Find policies by registry value name."""
        value_lower = value_name.lower()
        results = []

        for policy in self.db.get("policies", []):
            if value_lower in policy.get("valueName", "").lower():
                results.append(policy)
                continue

            elements = policy.get("elements")
            if elements:
                if isinstance(elements, dict):
                    elements = [elements]
                for elem in elements:
                    if value_lower in elem.get("valueName", "").lower():
                        results.append(policy)
                        break

        return results

    def get_stats(self) -> dict:
        """Get database statistics."""
        metadata = self.db.get("metadata", {})
        by_category = self.db.get("index", {}).get("byCategory", {})
        by_file = self.db.get("index", {}).get("byFileName", {})

        top_categories = sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True)[:10]

        return {
            "total_policies": metadata.get("totalPolicies", len(self.db.get("policies", []))),
            "total_files": metadata.get("totalFiles", len(by_file)),
            "total_categories": len(by_category),
            "export_date": metadata.get("exportDate", "Unknown"),
            "version": metadata.get("version", "Unknown"),
            "top_categories": top_categories,
        }


# Singleton instance
database_service = DatabaseService()
