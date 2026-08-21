#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import (
    ConfigError,
    STATE_DIR,
    load_manifest,
    load_overrides,
    load_selection,
    select_recipes,
    trust_references,
    validate_override_headers,
)


def validate() -> None:
    manifest = load_manifest()
    overrides = load_overrides()
    validate_override_headers(overrides)
    references = trust_references(overrides, overrides, manifest["repositories"])
    print(
        f"Validated {len(overrides)} recipes and generated overrides across "
        f"{len(references)} referenced repositories"
    )


def write_selection(requested: list[str], state_dir: Path) -> None:
    manifest = load_manifest()
    overrides = load_overrides()
    validate_override_headers(overrides)
    selected = select_recipes(requested, sorted(overrides))
    references = trust_references(selected, overrides, manifest["repositories"])
    repository_names = [
        repository["name"]
        for repository in manifest["repositories"]
        if repository["name"] in references
    ]

    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "repositories.txt").write_text(
        "".join(f"{name}\n" for name in repository_names), encoding="utf-8"
    )
    (state_dir / "selection.json").write_text(
        json.dumps(
            {"recipes": selected, "repositories": repository_names},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Selected {len(selected)} recipes using {len(repository_names)} repositories")


def print_selection(state_dir: Path) -> None:
    for recipe in load_selection(state_dir)["recipes"]:
        print(recipe)


def print_parents(requested: list[str], new_parents_path: Path | None) -> None:
    overrides = load_overrides()
    requested = requested or sorted(overrides)
    new_parents: dict[str, str] = {}
    if new_parents_path is not None:
        try:
            value = json.loads(new_parents_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigError(f"Cannot read {new_parents_path}: {error}") from error
        if not isinstance(value, dict) or not all(
            isinstance(identifier, str) and isinstance(parent, str)
            for identifier, parent in value.items()
        ):
            raise ConfigError(f"{new_parents_path}: invalid parent recipe mapping")
        new_parents = value
    aliases = {
        alias: identifier
        for identifier in overrides
        for alias in (identifier, identifier.removeprefix("local.munki."))
    }
    for recipe in requested:
        identifier = aliases.get(recipe)
        if identifier is None:
            if recipe in new_parents:
                print(new_parents[recipe])
                continue
            raise ConfigError(f"Unknown recipe: {recipe}")
        path, override = overrides[identifier]
        parent = override.get("ParentRecipe")
        if not isinstance(parent, str) or not parent:
            raise ConfigError(f"{path}: missing ParentRecipe")
        print(parent)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and select AutoPkg recipes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    select = subparsers.add_parser("select")
    select.add_argument("recipes", nargs="*")
    select.add_argument("--state-dir", type=Path, default=STATE_DIR)
    selected = subparsers.add_parser("selected")
    selected.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parents = subparsers.add_parser("parents")
    parents.add_argument("recipes", nargs="*")
    parents.add_argument("--new-parents", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "validate":
            validate()
        elif arguments.command == "select":
            write_selection(arguments.recipes, arguments.state_dir)
        elif arguments.command == "selected":
            print_selection(arguments.state_dir)
        else:
            print_parents(arguments.recipes, arguments.new_parents)
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
