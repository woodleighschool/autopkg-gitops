#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import plistlib
import shutil
from pathlib import Path

from common import (
    ConfigError,
    STATE_DIR,
    load_manifest,
    load_overrides,
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
    state_overrides = state_dir / "overrides"
    state_overrides.mkdir(exist_ok=True)
    selected_names = {overrides[identifier][0].name for identifier in selected}
    for stale in state_overrides.glob("*.munki.recipe.yaml"):
        if stale.name not in selected_names:
            stale.unlink()
    for identifier in selected:
        source = overrides[identifier][0]
        shutil.copy2(source, state_overrides / source.name)

    with (state_dir / "recipes.plist").open("wb") as output:
        plistlib.dump({"recipes": selected}, output, sort_keys=False)
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


def print_parents(requested: list[str], allow_new_woodleigh: bool) -> None:
    overrides = load_overrides()
    requested = requested or sorted(overrides)
    aliases = {
        alias: identifier
        for identifier in overrides
        for alias in (identifier, identifier.removeprefix("local.munki."))
    }
    for recipe in requested:
        identifier = aliases.get(recipe)
        if identifier is None:
            if allow_new_woodleigh and recipe.startswith("local.munki."):
                print(
                    recipe.replace(
                        "local.munki.",
                        "com.github.woodleighschool.munki.",
                        1,
                    )
                )
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
    parents = subparsers.add_parser("parents")
    parents.add_argument("recipes", nargs="*")
    parents.add_argument("--allow-new-woodleigh", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.command == "validate":
            validate()
        elif arguments.command == "select":
            write_selection(arguments.recipes, arguments.state_dir)
        else:
            print_parents(arguments.recipes, arguments.allow_new_woodleigh)
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
