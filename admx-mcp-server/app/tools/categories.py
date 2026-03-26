"""Category-related MCP tools."""

import logging

from app.services import database_service
from app.core import HEBREW_UI, format_policy_summary, validate_lang

logger = logging.getLogger(__name__)


def register_category_tools(mcp):
    """Register category-related MCP tools."""

    @mcp.tool()
    def list_categories(
        filter_text: str = "",
        lang: str = "en",
        max_results: int = 50
    ) -> str:
        """
        List all policy categories.

        Args:
            filter_text: Optional text to filter categories (leave empty for all)
            lang: Response language - 'en' for English, 'he' for Hebrew
            max_results: Maximum number of categories to return (default 50)

        Returns:
            List of categories with policy counts
        """
        try:
            lang = validate_lang(lang)
            max_results = max(1, min(max_results, 500))
            ui = HEBREW_UI if lang == "he" else {}
            categories = database_service.get_categories(filter_text)

            if not categories:
                return ui.get("no_results", "No results found")

            total = ui.get("total_categories", "Total categories")
            output = [f"# {total}: {len(categories)}", ""]

            policies_label = ui.get("policies_count", "{count} policies")
            for cat_name, count in categories[:max_results]:
                output.append(f"- **{cat_name}** ({policies_label.format(count=count)})")

            if len(categories) > max_results:
                more = len(categories) - max_results
                more_label = ui.get("more_categories", "... and {count} more categories")
                output.append(f"\n{more_label.format(count=more)}")

            return "\n".join(output)
        except Exception as e:
            logger.exception("Unhandled error in list_categories")
            return f"ERROR: {e}"

    @mcp.tool()
    def get_policies_by_category(
        category: str,
        lang: str = "en",
        max_results: int = 30
    ) -> str:
        """
        Get all policies in a specific category.

        Args:
            category: Category name (use list_categories to see available categories)
            lang: Response language - 'en' for English, 'he' for Hebrew
            max_results: Maximum number of policies to return (default 30)

        Returns:
            All policies in the category
        """
        try:
            lang = validate_lang(lang)
            max_results = max(1, min(max_results, 200))
            ui = HEBREW_UI if lang == "he" else {}
            actual_category, policies = database_service.get_by_category(category)

            if not policies:
                return ui.get("no_results", "No results found")

            policies_label = ui.get("policies_count", "{count} policies")
            header = f"# {actual_category} ({policies_label.format(count=len(policies))})"
            output = [header, ""]

            for policy in policies[:max_results]:
                output.append(format_policy_summary(policy, lang))
                output.append("")

            if len(policies) > max_results:
                more = len(policies) - max_results
                more_label = ui.get("more_policies", "... and {count} more policies")
                output.append(f"\n{more_label.format(count=more)}")

            return "\n".join(output)
        except Exception as e:
            logger.exception("Unhandled error in get_policies_by_category")
            return f"ERROR: {e}"
