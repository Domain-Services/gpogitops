#!/usr/bin/env python3
"""Validate XML well-formedness for all repository XML files."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def validate_xml_files(root: Path) -> int:
    xml_files = sorted(root.rglob("*.xml"))
    if not xml_files:
        print("No XML files found")
        return 0

    failed = 0
    for path in xml_files:
        try:
            ET.parse(path)
        except Exception as exc:
            failed += 1
            print(f"ERROR: {path}: {exc}")

    print(f"Checked {len(xml_files)} XML files")
    if failed:
        print(f"Validation failed: {failed} invalid XML files")
        return 1

    print("Validation passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Root directory to scan")
    args = parser.parse_args()
    return validate_xml_files(Path(args.root).resolve())


if __name__ == "__main__":
    sys.exit(main())
