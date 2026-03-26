"""Statistics-related MCP tools."""

import logging

from app.services import database_service
from app.core import HEBREW_UI, validate_lang

logger = logging.getLogger(__name__)


def register_stats_tools(mcp):
    """Register statistics-related MCP tools."""

    @mcp.tool()
    def get_database_stats(lang: str = "en") -> str:
        """
        Get statistics about the policy database.

        Args:
            lang: Response language - 'en' for English, 'he' for Hebrew

        Returns:
            Database statistics
        """
        try:
            lang = validate_lang(lang)
            ui = HEBREW_UI if lang == "he" else {}
            stats = database_service.get_stats()

            if lang == "he":
                output = [
                    "# סטטיסטיקות מסד נתונים",
                    "",
                    f"**{ui.get('total_policies', 'Total Policies')}:** {stats['total_policies']}",
                    f"**{ui.get('total_categories', 'Total Categories')}:** {stats['total_categories']}",
                    f"**קבצי ADMX:** {stats['total_files']}",
                    f"**תאריך ייצוא:** {stats['export_date']}",
                    f"**גרסה:** {stats['version']}",
                ]
            else:
                output = [
                    "# Database Statistics",
                    "",
                    f"**Total Policies:** {stats['total_policies']}",
                    f"**Total Categories:** {stats['total_categories']}",
                    f"**ADMX Files:** {stats['total_files']}",
                    f"**Export Date:** {stats['export_date']}",
                    f"**Version:** {stats['version']}",
                ]

            output.append("")
            output.append("## Top Categories" if lang == "en" else "## קטגוריות מובילות")

            for cat_name, policy_ids in stats["top_categories"]:
                output.append(f"- {cat_name}: {len(policy_ids)} policies")

            return "\n".join(output)
        except Exception as e:
            logger.exception("Unhandled error in get_database_stats")
            return f"ERROR: {e}"
