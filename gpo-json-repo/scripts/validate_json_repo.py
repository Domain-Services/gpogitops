#!/usr/bin/env python3
"""Validate GPO JSON repository structure and references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate(root: Path) -> int:
    failures: list[str] = []

    schema_path = root / "schema" / "gpo-policy.schema.json"
    if not schema_path.exists():
        failures.append(f"Missing schema file: {schema_path}")

    policies_dir = root / "policies"
    policy_files = sorted(policies_dir.glob("*.json")) if policies_dir.exists() else []
    if not policy_files:
        failures.append("No policy JSON files found under policies/")

    # basic policy checks (shape-lite, schema validation can be added with jsonschema package)
    for file in policy_files:
        try:
            doc = _read_json(file)
        except Exception as exc:
            failures.append(f"Invalid JSON in {file}: {exc}")
            continue

        for key in ["id", "name", "path", "settings"]:
            if key not in doc:
                failures.append(f"{file}: missing '{key}'")

        if "settings" in doc and (not isinstance(doc["settings"], list) or len(doc["settings"]) == 0):
            failures.append(f"{file}: 'settings' must be a non-empty array")

    for env in ["dev", "prod"]:
        manifest_path = root / "environments" / env / "desired-state.json"
        if not manifest_path.exists():
            failures.append(f"Missing environment manifest: {manifest_path}")
            continue

        try:
            manifest = _read_json(manifest_path)
        except Exception as exc:
            failures.append(f"Invalid JSON in {manifest_path}: {exc}")
            continue

        for key in ["environment", "domain", "target_ou", "policies"]:
            if key not in manifest:
                failures.append(f"{manifest_path}: missing '{key}'")

        for rel in manifest.get("policies", []):
            ref = root / rel
            if not ref.exists():
                failures.append(f"{manifest_path}: policy reference not found: {rel}")

    if failures:
        print("Validation failed:")
        for item in failures:
            print(f"- {item}")
        return 1

    print("Validation passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Repository root")
    args = parser.parse_args()
    return validate(Path(args.root).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
