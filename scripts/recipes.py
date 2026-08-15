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
    load_recipe_list,
    select_recipes,
    trust_references,
    validate_override_headers,
)


def validate() -> None:
    manifest = load_manifest()
    production = load_recipe_list()
    overrides = load_overrides()
    validate_override_headers(overrides)
    missing = sorted(set(production) - overrides.keys())
    if missing:
        raise ConfigError(f"Enabled recipes missing generated overrides: {', '.join(missing)}")
    references = trust_references(overrides, overrides, manifest["repositories"])
    print(
        f"Validated {len(production)} enabled recipes, {len(overrides)} generated overrides, "
        f"and {len(references)} referenced repositories"
    )


def write_selection(requested: list[str], state_dir: Path, all_overrides: bool) -> None:
    manifest = load_manifest()
    production = load_recipe_list()
    overrides = load_overrides()
    validate_override_headers(overrides)
    if all_overrides and requested:
        raise ConfigError("Specific recipes and --all-overrides cannot be used together")
    selected = sorted(overrides) if all_overrides else select_recipes(requested, production)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and select AutoPkg recipes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    select = subparsers.add_parser("select")
    select.add_argument("recipes", nargs="*")
    select.add_argument("--state-dir", type=Path, default=STATE_DIR)
    select.add_argument("--all-overrides", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.command == "validate":
            validate()
        else:
            write_selection(arguments.recipes, arguments.state_dir, arguments.all_overrides)
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
