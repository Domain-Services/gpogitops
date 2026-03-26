#!/usr/bin/env python3
"""GPO what-if analysis: validate policy files and report what would change.

This script is intended to run in CI (Woodpecker) on pull requests to give
reviewers a clear summary of which GPO settings are being added, modified
or removed — without actually applying anything.

Supports both YAML (source-of-truth) and legacy XML formats via ``--format``.
The default auto-detects: if ``policies/`` directory exists, YAML mode is used;
otherwise XML mode is used for backwards compatibility.

Exit codes:
    0 — all files valid, report printed
    1 — one or more validation errors detected
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Default base branch for diff: can be overridden via --base-branch CLI arg or
# the GPO_DEFAULT_TARGET_BRANCH environment variable (same var used by the server).
_DEFAULT_BASE_BRANCH = os.environ.get("GPO_DEFAULT_TARGET_BRANCH", "origin/main")


# ---------------------------------------------------------------------------
# Registry value type whitelist (must match xml_service.VALID_VALUE_TYPES)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# XML mode helpers (legacy / backwards-compatible)
# ---------------------------------------------------------------------------

def _changed_xml_files(root: Path, base_branch: str = _DEFAULT_BASE_BRANCH) -> list[Path]:
    """Return XML files changed in the current branch vs *base_branch*.

    Falls back to scanning all XML files if git diff is unavailable.

    Args:
        root: Repository root directory.
        base_branch: Git ref to diff against (e.g. ``origin/main``).  Defaults to
            the value of the ``GPO_DEFAULT_TARGET_BRANCH`` environment variable, or
            ``origin/main`` when that variable is not set.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_branch}...HEAD", "--", "*.xml"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [root / f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    except Exception:
        pass

    # Fallback: all XML files
    return sorted(root.rglob("*.xml"))


def _extract_settings_xml(file_path: Path) -> list[dict]:
    """Parse a GPO XML file and return a list of setting summaries."""
    try:
        tree = ET.parse(file_path)
    except ET.ParseError:
        return []

    settings = []
    for reg in tree.getroot().findall(".//Registry"):
        props = reg.find("Properties")
        settings.append({
            "uid": reg.get("uid", ""),
            "name": reg.get("name", ""),
            "hive": props.get("hive", "") if props is not None else "",
            "key": props.get("key", "") if props is not None else "",
            "value_name": props.get("name", "") if props is not None else "",
            "value_type": props.get("type", "") if props is not None else "",
            "value": props.get("value", "") if props is not None else "",
        })
    return settings


def validate_file_xml(file_path: Path) -> list[str]:
    """Run structural and semantic checks on a single GPO XML file.

    Returns a list of human-readable error strings (empty = valid).
    """
    errors: list[str] = []
    rel = file_path.name

    # 1. Well-formedness
    try:
        tree = ET.parse(file_path)
    except ET.ParseError as exc:
        errors.append(f"{rel}: malformed XML — {exc}")
        return errors

    root = tree.getroot()

    # 2. Root element check
    if root.tag != "Collection":
        errors.append(f"{rel}: unexpected root element <{root.tag}> (expected <Collection>)")

    # 3. Per-setting checks
    for reg in root.findall(".//Registry"):
        uid = reg.get("uid", "<no-uid>")
        name = reg.get("name", "<no-name>")
        label = f"{rel}::{name} ({uid})"

        if not reg.get("uid"):
            errors.append(f"{label}: missing uid attribute")

        props = reg.find("Properties")
        if props is None:
            errors.append(f"{label}: missing <Properties> element")
            continue

        # Value type check
        vtype = props.get("type", "")
        if vtype and vtype not in VALID_VALUE_TYPES:
            errors.append(f"{label}: invalid value type '{vtype}'")

        # Hive check
        hive = props.get("hive", "")
        if hive and hive not in VALID_HIVES:
            errors.append(f"{label}: invalid registry hive '{hive}'")

        # Key must not be empty
        if not props.get("key", "").strip():
            errors.append(f"{label}: empty registry key")

    return errors


# ---------------------------------------------------------------------------
# YAML mode helpers
# ---------------------------------------------------------------------------

def _load_yaml_module():
    """Import yaml, printing a helpful error if pyyaml is missing."""
    try:
        import yaml as _yaml
        return _yaml
    except ImportError:
        print("ERROR: pyyaml is not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)


def _changed_yaml_files(root: Path, base_branch: str = _DEFAULT_BASE_BRANCH) -> list[Path]:
    """Return YAML policy files changed in the current branch vs *base_branch*.

    Falls back to scanning all YAML files under policies/ if git diff is
    unavailable.
    """
    policies_dir = root / "policies"

    try:
        result = subprocess.run(
            [
                "git", "diff", "--name-only", "--diff-filter=ACMR",
                f"{base_branch}...HEAD", "--", "policies/*.yaml",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [root / f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
    except Exception:
        pass

    # Fallback: all YAML files under policies/
    if policies_dir.exists():
        return sorted(policies_dir.rglob("*.yaml"))
    return []


def _extract_settings_yaml(file_path: Path) -> list[dict]:
    """Parse a YAML policy file and return a list of setting summaries."""
    yaml = _load_yaml_module()
    try:
        with file_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception:
        return []

    if not isinstance(data, dict):
        return []

    settings = []
    for s in data.get("settings") or []:
        if not isinstance(s, dict):
            continue
        props = s.get("properties", {}) or {}
        settings.append({
            "uid": str(s.get("uid", "")),
            "name": str(s.get("name", "")),
            "hive": str(props.get("hive", "")),
            "key": str(props.get("key", "")),
            "value_name": str(props.get("value_name", props.get("name", ""))),
            "value_type": str(props.get("value_type", props.get("type", ""))),
            "value": str(props.get("value", "")),
        })
    return settings


def validate_file_yaml(file_path: Path) -> list[str]:
    """Validate a single YAML policy file for the what-if report.

    Returns a list of human-readable error strings (empty = valid).
    """
    yaml = _load_yaml_module()
    errors: list[str] = []
    rel = file_path.name

    try:
        with file_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:
        errors.append(f"{rel}: malformed YAML — {exc}")
        return errors

    if not isinstance(data, dict):
        errors.append(f"{rel}: top-level structure must be a mapping")
        return errors

    for required in ("collection_name", "ou", "settings"):
        if required not in data:
            errors.append(f"{rel}: missing required key '{required}'")

    for idx, s in enumerate(data.get("settings") or []):
        if not isinstance(s, dict):
            errors.append(f"{rel}: settings[{idx}] is not a mapping")
            continue

        label = f"{rel}::{s.get('name', f'<index {idx}>')}"
        props = s.get("properties", {}) or {}

        vtype = str(props.get("value_type", props.get("type", ""))).strip()
        if vtype and vtype not in VALID_VALUE_TYPES:
            errors.append(f"{label}: invalid value_type '{vtype}'")

        hive = str(props.get("hive", "")).strip()
        if hive and hive not in VALID_HIVES:
            errors.append(f"{label}: invalid hive '{hive}'")

        if not str(props.get("key", "")).strip():
            errors.append(f"{label}: empty registry key")

    return errors


# ---------------------------------------------------------------------------
# Shared report printer
# ---------------------------------------------------------------------------

def print_whatif_report(
    files: list[Path],
    root: Path,
    *,
    fmt: str,
) -> int:
    """Print a what-if report and return 0 (ok) or 1 (errors found).

    Args:
        files: Policy files to analyse.
        root:  Repository root (used for relative path display).
        fmt:   ``"xml"`` or ``"yaml"`` — selects the appropriate extractor/validator.
    """
    label = "YAML" if fmt == "yaml" else "XML"

    if not files:
        print(f"What-If: no {label} files to analyse")
        return 0

    extract_fn = _extract_settings_yaml if fmt == "yaml" else _extract_settings_xml
    validate_fn = validate_file_yaml if fmt == "yaml" else validate_file_xml

    total_settings = 0
    total_errors = 0
    all_errors: list[str] = []

    print("=" * 70)
    print(f"GPO WHAT-IF ANALYSIS ({label})")
    print("=" * 70)

    for fpath in files:
        if not fpath.exists():
            continue
        try:
            rel = fpath.relative_to(root)
        except ValueError:
            rel = fpath

        settings = extract_fn(fpath)
        errors = validate_fn(fpath)
        total_settings += len(settings)
        total_errors += len(errors)
        all_errors.extend(errors)

        status = "FAIL" if errors else "OK"
        print(f"\n[{status}] {rel}  ({len(settings)} settings)")

        for s in settings:
            print(f"  - {s['name']}: {s['hive']}\\{s['key']}\\{s['value_name']} "
                  f"= {s['value']} ({s['value_type']})")

        for err in errors:
            print(f"  ERROR: {err}")

    print("\n" + "=" * 70)
    print(f"Summary: {len(files)} files, {total_settings} settings, {total_errors} errors")
    print("=" * 70)

    if all_errors:
        print("\nWhat-If FAILED — fix the errors above before merging.")
        return 1

    print("\nWhat-If PASSED — changes look safe to merge.")
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="GPO what-if analysis")
    parser.add_argument("--root", default=".", help="Repository root directory")
    parser.add_argument(
        "--all", action="store_true", dest="scan_all",
        help="Scan all policy files (default: only files changed vs base branch)",
    )
    parser.add_argument(
        "--base-branch",
        default=_DEFAULT_BASE_BRANCH,
        help=(
            "Git ref to diff against when detecting changed files "
            f"(default: {_DEFAULT_BASE_BRANCH!r}, overrideable via "
            "GPO_DEFAULT_TARGET_BRANCH env var)"
        ),
    )
    parser.add_argument(
        "--format",
        choices=["xml", "yaml", "auto"],
        default="auto",
        dest="fmt",
        help=(
            "Policy file format to analyse. "
            "'auto' (default) uses YAML if policies/ directory exists, else XML."
        ),
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()

    # Resolve auto-detect
    fmt = args.fmt
    if fmt == "auto":
        fmt = "yaml" if (root / "policies").exists() else "xml"

    if args.scan_all:
        if fmt == "yaml":
            policies_dir = root / "policies"
            files = sorted(policies_dir.rglob("*.yaml")) if policies_dir.exists() else []
        else:
            files = sorted(root.rglob("*.xml"))
    else:
        if fmt == "yaml":
            files = _changed_yaml_files(root, base_branch=args.base_branch)
        else:
            files = _changed_xml_files(root, base_branch=args.base_branch)

    return print_whatif_report(files, root, fmt=fmt)


if __name__ == "__main__":
    sys.exit(main())
