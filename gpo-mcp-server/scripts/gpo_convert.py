#!/usr/bin/env python3
"""Convert YAML GPO policy files to XML deployment artifacts.

YAML files under ``policies/`` are the single source of truth.  This script
reads every ``policies/*.yaml`` file and writes a corresponding XML file to
``--out`` directory.  The generated XML files are *never* committed to the
repository — they exist only as transient CI artefacts used by the GPO apply
step in Woodpecker.

Usage::

    python scripts/gpo_convert.py --root . --out generated/

Exit codes:
    0 — all files converted successfully
    1 — one or more conversion errors
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml is not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# GPO XML CLSID constants — same values as XMLService
# ---------------------------------------------------------------------------
REGISTRY_CLSID = "{9CD4B2F4-923D-47f5-A062-E897DD1DAD50}"
COLLECTION_CLSID = "{53B533F5-224C-47e3-B01B-CA3B3F3FF4BF}"


def _safe_filename(name: str) -> str:
    """Convert *name* to a safe filename by replacing non-alphanumeric chars."""
    return re.sub(r"[^\w\-]", "_", name).strip("_") or "policy"


def _changed_timestamp() -> str:
    """Return a GPO-style timestamp string for the ``changed`` attribute."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def convert_file(yaml_path: Path, out_dir: Path) -> tuple[bool, str]:
    """Convert a single YAML policy file to XML.

    Returns ``(True, output_path_str)`` on success, ``(False, error_message)``
    on failure.
    """
    # ------------------------------------------------------------------ #
    # Load YAML
    # ------------------------------------------------------------------ #
    try:
        with yaml_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        return False, f"Malformed YAML in {yaml_path.name}: {exc}"

    if not isinstance(data, dict):
        return False, f"{yaml_path.name}: top-level structure must be a mapping"

    collection_name = str(data.get("collection_name", yaml_path.stem))
    ou = str(data.get("ou", "")).strip()
    settings = data.get("settings") or []

    # ------------------------------------------------------------------ #
    # Build XML tree
    # ------------------------------------------------------------------ #
    ts = _changed_timestamp()

    root_elem = ET.Element("Collection")
    root_elem.set("clsid", COLLECTION_CLSID)
    root_elem.set("name", collection_name)

    for s in settings:
        if not isinstance(s, dict):
            continue

        uid = str(s.get("uid", ""))
        name = str(s.get("name", ""))
        description = str(s.get("description", ""))
        bypass_errors_raw = s.get("bypass_errors", False)
        bypass_errors = "1" if bypass_errors_raw else "0"
        changed = str(s.get("changed", ts))

        props_raw = s.get("properties", {}) or {}
        action = str(props_raw.get("action", "U"))
        hive = str(props_raw.get("hive", ""))
        key = str(props_raw.get("key", ""))
        # Support both 'value_name' (YAML convention) and 'name' (internal dict)
        value_name = str(props_raw.get("value_name", props_raw.get("name", "")))
        # Support both 'value_type' (YAML convention) and 'type' (internal dict)
        value_type = str(props_raw.get("value_type", props_raw.get("type", "")))
        value = str(props_raw.get("value", ""))
        display_decimal = str(props_raw.get("displayDecimal", "1"))
        default = str(props_raw.get("default", "0"))

        reg_elem = ET.SubElement(root_elem, "Registry")
        reg_elem.set("clsid", REGISTRY_CLSID)
        reg_elem.set("name", name)
        reg_elem.set("uid", uid)
        reg_elem.set("changed", changed)
        reg_elem.set("image", "12")
        reg_elem.set("bypassErrors", bypass_errors)
        if description:
            reg_elem.set("desc", description)

        props_elem = ET.SubElement(reg_elem, "Properties")
        props_elem.set("action", action)
        props_elem.set("displayDecimal", display_decimal)
        props_elem.set("default", default)
        props_elem.set("hive", hive)
        props_elem.set("key", key)
        props_elem.set("name", value_name)
        props_elem.set("type", value_type)
        props_elem.set("value", value)

    # ------------------------------------------------------------------ #
    # Determine output path
    # ------------------------------------------------------------------ #
    # Use OU as a sub-directory when present, otherwise write flat
    if ou:
        dest_dir = out_dir / _safe_filename(ou)
    else:
        dest_dir = out_dir

    dest_dir.mkdir(parents=True, exist_ok=True)

    # Use collection_name as the output filename
    out_file = dest_dir / (_safe_filename(collection_name) + ".xml")

    # ------------------------------------------------------------------ #
    # Write XML (atomic temp-then-replace)
    # ------------------------------------------------------------------ #
    tree = ET.ElementTree(root_elem)
    ET.indent(tree, space="  ")  # Python 3.9+

    tmp_path = out_file.with_suffix(".xml.tmp")
    try:
        tree.write(str(tmp_path), encoding="utf-8", xml_declaration=True)
        os.replace(tmp_path, out_file)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        return False, f"Failed to write {out_file}: {exc}"

    return True, str(out_file)


def convert_all(root: Path, out_dir: Path) -> int:
    """Convert all YAML files under root/policies/ to XML in out_dir.

    Prints a summary and returns 0 (success) or 1 (errors).
    """
    policies_dir = root / "policies"

    if not policies_dir.exists():
        print(f"ERROR: policies/ directory not found under {root}", file=sys.stderr)
        return 1

    yaml_files = sorted(policies_dir.rglob("*.yaml"))

    if not yaml_files:
        print(f"No YAML policy files found under {policies_dir}")
        return 0

    errors = 0
    converted = 0

    print("=" * 70)
    print("GPO YAML → XML CONVERSION")
    print("=" * 70)

    for yaml_path in yaml_files:
        ok, result = convert_file(yaml_path, out_dir)
        try:
            rel = yaml_path.relative_to(root)
        except ValueError:
            rel = yaml_path

        if ok:
            converted += 1
            print(f"  [OK]   {rel} → {result}")
        else:
            errors += 1
            print(f"  [FAIL] {rel}: {result}", file=sys.stderr)

    print("\n" + "=" * 70)
    print(f"Summary: {len(yaml_files)} files, {converted} converted, {errors} errors")
    print("=" * 70)

    if errors:
        print("\nConversion FAILED — fix the errors above.", file=sys.stderr)
        return 1

    print(f"\nConversion PASSED — XML artefacts written to {out_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert YAML GPO policy files to XML deployment artefacts"
    )
    parser.add_argument("--root", default=".", help="Repository root directory")
    parser.add_argument(
        "--out",
        default="generated",
        help="Output directory for generated XML files (default: generated/)",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = root / out_dir

    return convert_all(root, out_dir)


if __name__ == "__main__":
    sys.exit(main())
