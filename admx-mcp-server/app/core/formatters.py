"""Formatting utilities for ADMX policy display."""

from .translations import HEBREW_UI


def format_policy(policy: dict, lang: str = "en") -> str:
    """Format a policy for display."""
    ui = HEBREW_UI if lang == "he" else {}

    lines = []

    # Display name
    display_name = policy.get("displayName", policy.get("name", "Unknown"))
    lines.append(f"## {display_name}")
    lines.append("")

    # Basic info
    if policy.get("explainText"):
        lines.append(f"**{ui.get('description', 'Description')}:**")
        lines.append(policy["explainText"].strip())
        lines.append("")

    # Registry info
    lines.append(f"**{ui.get('registry_key', 'Registry Key')}:** `{policy.get('key', 'N/A')}`")
    if policy.get("valueName"):
        lines.append(f"**{ui.get('registry_value', 'Value Name')}:** `{policy['valueName']}`")

    # Class (Machine/User)
    policy_class = policy.get("class", "")
    if lang == "he":
        if policy_class == "Machine":
            class_display = ui.get("class_machine", policy_class)
        elif policy_class == "User":
            class_display = ui.get("class_user", policy_class)
        else:
            class_display = policy_class
    else:
        class_display = policy_class
    lines.append(f"**{ui.get('class', 'Class')}:** {class_display}")

    # Category
    if policy.get("categoryPathDisplay"):
        lines.append(f"**{ui.get('category', 'Category')}:** {policy['categoryPathDisplay']}")

    # Supported on
    if policy.get("supportedOn"):
        lines.append(f"**{ui.get('supported_on', 'Supported On')}:** {policy['supportedOn']}")

    # Enabled/Disabled values
    if policy.get("enabledValue"):
        ev = policy["enabledValue"]
        lines.append(f"**{ui.get('enabled_value', 'Enabled Value')}:** {ev.get('type', '')} = {ev.get('value', '')}")

    if policy.get("disabledValue"):
        dv = policy["disabledValue"]
        lines.append(f"**{ui.get('disabled_value', 'Disabled Value')}:** {dv.get('type', '')} = {dv.get('value', '')}")

    # Elements
    elements = policy.get("elements")
    if elements:
        lines.append("")
        lines.append(f"### {ui.get('elements', 'Elements')}")

        if isinstance(elements, dict):
            elements = [elements]

        for elem in elements:
            elem_type = elem.get("type", "unknown")
            elem_id = elem.get("id", "")
            elem_value_name = elem.get("valueName", "")

            type_display = ui.get(f"element_{elem_type}", elem_type) if lang == "he" else elem_type
            lines.append(f"- **{elem_id}** ({type_display}): `{elem_value_name}`")

            if elem_type == "enum" and elem.get("options"):
                for opt in elem["options"]:
                    opt_name = opt.get("displayName", "")
                    opt_val = opt.get("value", "")
                    lines.append(f"  - {opt_name} = {opt_val}")

            if elem_type in ("decimal", "longDecimal"):
                if elem.get("minValue") is not None:
                    lines.append(f"  - {ui.get('min_value', 'Min')}: {elem['minValue']}")
                if elem.get("maxValue") is not None:
                    lines.append(f"  - {ui.get('max_value', 'Max')}: {elem['maxValue']}")

    lines.append("")
    lines.append(f"**Namespace:** `{policy.get('namespace', 'N/A')}`")
    lines.append(f"**Policy Name:** `{policy.get('name', 'N/A')}`")

    return "\n".join(lines)


def format_policy_summary(policy: dict, lang: str = "en") -> str:
    """Format a brief policy summary."""
    ui = HEBREW_UI if lang == "he" else {}
    display_name = policy.get("displayName", policy.get("name", "Unknown"))
    key = policy.get("key", "")
    category = policy.get("categoryPathDisplay", "")
    policy_class = policy.get("class", "")

    if lang == "he":
        if policy_class == "Machine":
            class_display = ui.get("class_machine", policy_class)
        elif policy_class == "User":
            class_display = ui.get("class_user", policy_class)
        else:
            class_display = policy_class
    else:
        class_display = policy_class

    cat_label = ui.get("category", "Category")
    class_label = ui.get("class", "Class")
    key_label = ui.get("registry_key", "Key")
    return f"- **{display_name}**\n  {key_label}: `{key}`\n  {cat_label}: {category} | {class_label}: {class_display}"
