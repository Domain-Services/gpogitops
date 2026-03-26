"""Core utilities and helpers."""

from .formatters import format_policy, format_policy_summary
from .translations import HEBREW_UI

VALID_LANGS = {"en", "he"}


def validate_lang(lang: str) -> str:
    """Validate and normalise a language code. Falls back to 'en' for unknown codes."""
    lang = lang.strip().lower() if lang else "en"
    if lang not in VALID_LANGS:
        return "en"
    return lang


__all__ = ["format_policy", "format_policy_summary", "HEBREW_UI", "VALID_LANGS", "validate_lang"]
