#!/usr/bin/env python3
"""Validate all YAML GPO policy files under policies/.

Checks required top-level fields, per-setting required fields, registry value
types and hive names.  Mirrors the exit-code convention of validate_xml.py:

Exit codes:
    0 — all files valid
    1 — one or more validation errors found
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml is not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# Must match yaml_service.VALID_VALUE_TYPES and xml_service.VALID_VALUE_TYPES
VALID_VALUE_TYPES = frozenset({
    "REG_SZ",
    "REG_EXPAND_SZ",
    "REG_BINARY",
    "REG_DWORD",
    "REG_DWORD_BIG_ENDIAN",
    "REG_MULTI_SZ",
    "REG_QWORD",
})

VALID_HIVES = frozenset({
    "HKEY_LOCAL_MACHINE",
    "HKEY_CURRENT_USER",
    "HKEY_CLASSES_ROOT",
    "HKEY_USERS",
    "HKEY_CURRENT_CONFIG",
})

# Required top-level keys in every policy file
_REQUIRED_TOP_LEVEL = ("collection_name", "ou", "settings")

# Required fields inside each setting's properties block
_REQUIRED_PROPS = ("hive", "key", "value_type")

# Required fields inside each setting (top-level of the setting dict)
_REQUIRED_SETTING_FIELDS = ("name",)


def validate_file(file_path: Path) -> list[str]:
    """Validate a single YAML policy file.

    Returns a list of human-readable error strings.  An empty list means valid.
    """
    errors: list[str] = []
    rel = file_path.name

    # ------------------------------------------------------------------ #
    # 1. Load and parse YAML
    # ------------------------------------------------------------------ #
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        errors.append(f"{rel}: malformed YAML — {exc}")
        return errors

    if data is None:
        errors.append(f"{rel}: file is empty")
        return errors

    if not isinstance(data, dict):
        errors.append(f"{rel}: top-level structure must be a mapping, got {type(data).__name__}")
        return errors

    # ------------------------------------------------------------------ #
    # 2. Required top-level keys
    # ------------------------------------------------------------------ #
    for key in _REQUIRED_TOP_LEVEL:
        if key not in data:
            errors.append(f"{rel}: missing required top-level key '{key}'")

    if "collection_name" in data and not str(data["collection_name"]).strip():
        errors.append(f"{rel}: 'collection_name' must not be empty")

    if "ou" in data and not str(data.get("ou", "")).strip():
        errors.append(f"{rel}: 'ou' must not be empty")

    # ------------------------------------------------------------------ #
    # 3. Per-setting validation
    # ------------------------------------------------------------------ #
    settings = data.get("settings")
    if settings is None:
        # Already flagged above if missing; skip per-setting checks
        return errors

    if not isinstance(settings, list):
        errors.append(f"{rel}: 'settings' must be a list, got {type(settings).__name__}")
        return errors

    for idx, setting in enumerate(settings):
        if not isinstance(setting, dict):
            errors.append(f"{rel}: settings[{idx}] is not a mapping")
            continue

        label_name = setting.get("name", f"<index {idx}>")
        label = f"{rel}::{label_name}"

        # Required setting-level fields
        for field in _REQUIRED_SETTING_FIELDS:
            if not setting.get(field, ""):
                errors.append(f"{label}: missing required field '{field}'")

        props = setting.get("properties")
        if not isinstance(props, dict):
            errors.append(f"{label}: missing or invalid 'properties' block")
            continue

        # value_name accepted as alias for name in YAML; check at least one present
        has_value_name = bool(props.get("value_name") or props.get("name"))
        if not has_value_name:
            errors.append(f"{label}: properties missing 'value_name' (registry value name)")

        # value must be present (even if empty string is allowed, the key must exist)
        if "value" not in props:
            errors.append(f"{label}: properties missing 'value'")

        # Required property fields
        for field in _REQUIRED_PROPS:
            if not props.get(field, ""):
                errors.append(f"{label}: properties missing required field '{field}'")

        # value_type whitelist check (use value_type key; fall back to type)
        vtype = str(props.get("value_type", props.get("type", ""))).strip()
        if vtype and vtype not in VALID_VALUE_TYPES:
            errors.append(
                f"{label}: invalid value_type '{vtype}'. "
                f"Must be one of: {', '.join(sorted(VALID_VALUE_TYPES))}"
            )

        # hive whitelist check
        hive = str(props.get("hive", "")).strip()
        if hive and hive not in VALID_HIVES:
            errors.append(
                f"{label}: invalid hive '{hive}'. "
                f"Must be one of: {', '.join(sorted(VALID_HIVES))}"
            )

        # key must not be empty
        if not str(props.get("key", "")).strip():
            errors.append(f"{label}: properties 'key' (registry key path) must not be empty")

    return errors


def validate_all(root: Path) -> int:
    """Validate all .yaml files under root/policies/.

    Prints a report and returns 0 (all valid) or 1 (errors found).
    """
    policies_dir = root / "policies"

    if not policies_dir.exists():
        print(f"ERROR: policies/ directory not found under {root}", file=sys.stderr)
        return 1

    yaml_files = sorted(policies_dir.rglob("*.yaml"))

    if not yaml_files:
        print(f"No YAML policy files found under {policies_dir}")
        return 0

    total_errors = 0
    print("=" * 70)
    print("GPO YAML VALIDATION")
    print("=" * 70)

    for fpath in yaml_files:
        errors = validate_file(fpath)
        status = "FAIL" if errors else "OK"
        try:
            rel = fpath.relative_to(root)
        except ValueError:
            rel = fpath
        print(f"\n[{status}] {rel}")
        for err in errors:
            print(f"  ERROR: {err}")
        total_errors += len(errors)

    print("\n" + "=" * 70)
    print(f"Summary: {len(yaml_files)} files checked, {total_errors} errors found")
    print("=" * 70)

    if total_errors:
        print("\nValidation FAILED — fix the errors above before merging.", file=sys.stderr)
        return 1

    print("\nValidation PASSED — all policy files are valid.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate YAML GPO policy files")
    parser.add_argument("--root", default=".", help="Repository root directory")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    return validate_all(root)


if __name__ == "__main__":
    sys.exit(main())
