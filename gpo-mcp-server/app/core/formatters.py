"""Formatting utilities for GPO settings display."""

import html
import re


def format_gpo_setting(setting: dict) -> str:
    """Format a GPO setting for display."""
    lines = []
    lines.append(f"## {setting['name']}")
    lines.append("")

    if setting.get("description"):
        # Clean up HTML in description
        desc = setting["description"]
        desc = re.sub(r'<[^>]+>', ' ', desc)
        desc = html.unescape(desc)
        lines.append(f"**Description:** {desc.strip()}")
        lines.append("")

    props = setting.get("properties", {})
    if props:
        lines.append(f"**Registry Path:** `{props.get('hive', '')}\\{props.get('key', '')}`")
        lines.append(f"**Value Name:** `{props.get('name', '')}`")
        lines.append(f"**Type:** `{props.get('type', '')}`")
        lines.append(f"**Value:** `{props.get('value', '')}`")
        lines.append(f"**Action:** {props.get('action', '')}")

    if setting.get("filters"):
        lines.append("")
        lines.append("**Filters:**")
        for f in setting["filters"]:
            lines.append(f"  - OS: {f.get('class', '')} {f.get('version', '')}")

    lines.append(f"**UID:** `{setting.get('uid', '')}`")
    lines.append(f"**Last Changed:** {setting.get('changed', '')}")

    return "\n".join(lines)
