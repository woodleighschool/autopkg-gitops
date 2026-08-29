#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import (
    ConfigError,
    OVERRIDE_DIR,
    STATE_DIR,
    load_manifest,
    load_overrides,
    load_selection,
    select_recipes,
)


def print_selection(state_dir: Path) -> None:
    for recipe in load_selection(state_dir)["recipes"]:
        print(recipe)


def print_available(override_dir: Path) -> None:
    for recipe in sorted(load_overrides(override_dir)):
        print(recipe)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check and select recipes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--override-dir", type=Path, default=OVERRIDE_DIR)
    select = subparsers.add_parser("select")
    select.add_argument("recipes", nargs="*")
    select.add_argument("--state-dir", type=Path, default=STATE_DIR)
    select.add_argument("--override-dir", type=Path, default=OVERRIDE_DIR)
    selected = subparsers.add_parser("selected")
    selected.add_argument("--state-dir", type=Path, default=STATE_DIR)
    available = subparsers.add_parser("list")
    available.add_argument("--override-dir", type=Path, default=OVERRIDE_DIR)
    arguments = parser.parse_args()
    try:
        if arguments.command == "validate":
            manifest = load_manifest()
            overrides = load_overrides(arguments.override_dir)
            repositories = manifest["repositories"]
            assert isinstance(repositories, list)
            print(
                f"Checked {len(overrides)} overrides and {len(repositories)} pins"
            )
        elif arguments.command == "select":
            overrides = load_overrides(arguments.override_dir)
            selected_recipes = select_recipes(arguments.recipes, sorted(overrides))
            arguments.state_dir.mkdir(parents=True, exist_ok=True)
            (arguments.state_dir / "selection.json").write_text(
                json.dumps({"recipes": selected_recipes}, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"Selected {len(selected_recipes)} recipes")
        elif arguments.command == "selected":
            print_selection(arguments.state_dir)
        else:
            print_available(arguments.override_dir)
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
