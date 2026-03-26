"""Search-related MCP tools."""

import logging

from app.services import database_service
from app.core import HEBREW_UI, format_policy, format_policy_summary, validate_lang

logger = logging.getLogger(__name__)


def register_search_tools(mcp):
    """Register search-related MCP tools."""

    @mcp.tool()
    def search_policies(
        query: str,
        lang: str = "en",
        max_results: int = 10
    ) -> str:
        """
        Search for Group Policies by name, description, or any text.

        Args:
            query: Search text (case-insensitive)
            lang: Response language - 'en' for English, 'he' for Hebrew
            max_results: Maximum number of results to return (default 10)

        Returns:
            Matching policies with details
        """
        try:
            lang = validate_lang(lang)
            max_results = max(1, min(max_results, 100))
            ui = HEBREW_UI if lang == "he" else {}
            results = database_service.search(query, max_results)

            if not results:
                return ui.get("no_results", "No results found")

            header = ui.get("found_results", "Found {count} results").format(count=len(results))
            output = [f"# {header}", ""]

            for policy in results:
                output.append(format_policy_summary(policy, lang))
                output.append("")

            return "\n".join(output)
        except Exception as e:
            logger.exception("Unhandled error in search tool")
            return f"ERROR: {e}"

    @mcp.tool()
    def get_policy_by_key(
        registry_key: str,
        lang: str = "en",
        max_results: int = 20
    ) -> str:
        """
        Find policies by registry key path.

        Args:
            registry_key: Registry key path (e.g., "SOFTWARE\\Policies\\Microsoft\\Windows")
            lang: Response language - 'en' for English, 'he' for Hebrew
            max_results: Maximum number of results to return (default 20)

        Returns:
            Policies that use this registry key
        """
        try:
            lang = validate_lang(lang)
            max_results = max(1, min(max_results, 100))
            ui = HEBREW_UI if lang == "he" else {}
            results = database_service.get_by_key(registry_key)

            if not results:
                return ui.get("no_results", "No results found")

            header = ui.get("found_results", "Found {count} results").format(count=len(results))
            output = [f"# {header}", ""]

            for policy in results[:max_results]:
                output.append(format_policy(policy, lang))
                output.append("---")

            if len(results) > max_results:
                more = len(results) - max_results
                more_label = ui.get("more_results", "... and {count} more results")
                output.append(f"\n{more_label.format(count=more)}")

            return "\n".join(output)
        except Exception as e:
            logger.exception("Unhandled error in search tool")
            return f"ERROR: {e}"

    @mcp.tool()
    def get_policy_by_name(
        policy_name: str,
        lang: str = "en"
    ) -> str:
        """
        Get detailed information about a specific policy by its name.

        Args:
            policy_name: The policy name or display name
            lang: Response language - 'en' for English, 'he' for Hebrew

        Returns:
            Detailed policy information
        """
        try:
            lang = validate_lang(lang)
            ui = HEBREW_UI if lang == "he" else {}
            results = database_service.get_by_name(policy_name)

            if not results:
                return ui.get("no_results", "No results found")

            if len(results) == 1:
                return format_policy(results[0], lang)

            header = ui.get("found_results", "Found {count} results").format(count=len(results))
            output = [f"# {header}", ""]

            for policy in results[:10]:
                output.append(format_policy_summary(policy, lang))
                output.append("")

            return "\n".join(output)
        except Exception as e:
            logger.exception("Unhandled error in search tool")
            return f"ERROR: {e}"

    @mcp.tool()
    def search_by_registry_value(
        value_name: str,
        lang: str = "en",
        max_results: int = 20
    ) -> str:
        """
        Search for policies by registry value name.

        Args:
            value_name: Registry value name to search for
            lang: Response language - 'en' for English, 'he' for Hebrew
            max_results: Maximum number of results to return (default 20)

        Returns:
            Policies that use this registry value
        """
        try:
            lang = validate_lang(lang)
            max_results = max(1, min(max_results, 100))
            ui = HEBREW_UI if lang == "he" else {}
            results = database_service.get_by_registry_value(value_name)

            if not results:
                return ui.get("no_results", "No results found")

            header = ui.get("found_results", "Found {count} results").format(count=len(results))
            output = [f"# {header}", ""]

            for policy in results[:max_results]:
                output.append(format_policy_summary(policy, lang))
                output.append("")

            if len(results) > max_results:
                more = len(results) - max_results
                more_label = ui.get("more_results", "... and {count} more results")
                output.append(f"\n{more_label.format(count=more)}")

            return "\n".join(output)
        except Exception as e:
            logger.exception("Unhandled error in search tool")
            return f"ERROR: {e}"

    @mcp.tool()
    def get_policy_full_details(
        namespace: str,
        policy_name: str,
        lang: str = "en"
    ) -> str:
        """
        Get full details of a policy by namespace and name.

        Args:
            namespace: Policy namespace (e.g., "Microsoft.Policies.WindowsDefender")
            policy_name: Policy name (e.g., "DisableAntiSpyware")
            lang: Response language - 'en' for English, 'he' for Hebrew

        Returns:
            Complete policy details
        """
        try:
            lang = validate_lang(lang)
            ui = HEBREW_UI if lang == "he" else {}
            policy_id = f"{namespace}::{policy_name}"
            policies_by_id = database_service.policies_by_id

            policy = policies_by_id.get(policy_id)

            if not policy:
                # Try case-insensitive
                for pid, p in policies_by_id.items():
                    if pid.lower() == policy_id.lower():
                        policy = p
                        break

            if not policy:
                return ui.get("no_results", "No results found")

            return format_policy(policy, lang)
        except Exception as e:
            logger.exception("Unhandled error in search tool")
            return f"ERROR: {e}"
