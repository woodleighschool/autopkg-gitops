#!/usr/local/autopkg/python
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

import yaml


TRANSIENT_KEYS = {
    "PARENT_RECIPES",
    "ParentRecipe",
    "ParentRecipeTrustInfo",
    "RECIPE_PATH",
    "name",
}


def load_autopkg(path: Path):
    sys.path.insert(0, str(path.parent))
    loader = importlib.machinery.SourceFileLoader("autopkg_cli", str(path))
    specification = importlib.util.spec_from_loader(loader.name, loader)
    if specification is None:
        raise RuntimeError(f"Could not load AutoPkg from {path}")
    module = importlib.util.module_from_spec(specification)
    loader.exec_module(module)
    return module


def read_recipes(path: Path) -> list[str]:
    recipes = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [recipe for recipe in recipes if recipe]


def normalize(recipe: dict) -> dict:
    return {key: value for key, value in recipe.items() if key not in TRANSIENT_KEYS}


def main() -> int:
    parser = argparse.ArgumentParser(description="Render resolved AutoPkg recipe chains")
    parser.add_argument("--autopkg", type=Path, default=Path("/Library/AutoPkg/autopkg"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--override-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--recipes", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()

    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    search_dirs = [
        str(arguments.repo_root / repository["name"])
        for repository in manifest["repositories"]
        if (arguments.repo_root / repository["name"]).is_dir()
    ]
    recipes = read_recipes(arguments.recipes)
    if not recipes:
        parser.error(f"{arguments.recipes}: no recipes found")

    autopkg = load_autopkg(arguments.autopkg)
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    for identifier in recipes:
        recipe = autopkg.load_recipe(
            identifier,
            [str(arguments.override_dir)],
            search_dirs,
            make_suggestions=False,
            search_github=False,
        )
        if not recipe:
            parser.error(f"Could not resolve {identifier}")
        output = arguments.output_dir / f"{identifier}.yaml"
        output.write_text(
            yaml.safe_dump(
                normalize(recipe),
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
                width=100,
            ),
            encoding="utf-8",
        )
        print(f"Rendered {identifier}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
