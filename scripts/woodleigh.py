#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from common import (
    ConfigError,
    MANIFEST_PATH,
    OVERRIDE_DIR,
    REPO_ROOT,
    ROOT,
    STATE_DIR,
    load_manifest,
    load_overrides,
    validate_manifest,
)
from repositories import ensure_checkout, git


SOURCE_URL = "https://github.com/woodleighschool/autopkg"
SOURCE_PREFIX = "com.github.woodleighschool.munki."
OVERRIDE_PREFIX = "local.munki."
LOCAL_IMAGE_SUFFIXES = (".icns", ".jpeg", ".jpg", ".png", ".svg", ".webp")


def git_output(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise ConfigError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout


def manifest_at(revision: str) -> dict[str, Any]:
    source = f"{revision}:repositories.json"
    try:
        value = json.loads(git_output("show", source))
    except json.JSONDecodeError as error:
        raise ConfigError(f"{source}: {error}") from error
    return validate_manifest(value, source)


def source_repository(manifest: Mapping[str, Any]) -> dict[str, str] | None:
    for repository in manifest["repositories"]:
        if repository["url"].removesuffix(".git").removesuffix("/") == SOURCE_URL:
            return repository
    return None


def nested_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from nested_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_strings(child)


def recipe_index(
    checkout: Path,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    yaml = YAML(typ="safe")
    recipes: dict[str, Mapping[str, Any]] = {}
    paths: dict[str, str] = {}
    for path in sorted(checkout.rglob("*.recipe.yaml")):
        recipe = yaml.load(path.read_text(encoding="utf-8"))
        if not isinstance(recipe, Mapping):
            raise ConfigError(f"{path}: recipe must be a mapping")
        identifier = recipe.get("Identifier")
        if not isinstance(identifier, str):
            raise ConfigError(f"{path}: missing Identifier")
        if identifier in recipes:
            raise ConfigError(f"{path}: duplicate recipe identifier {identifier}")
        recipes[identifier] = recipe
        paths[path.relative_to(checkout).as_posix()] = identifier
    return recipes, paths


def recipe_traits(
    identifier: str,
    recipes: Mapping[str, Mapping[str, Any]],
    munki_names: Mapping[str, str],
    cache: dict[str, frozenset[str]],
    visiting: set[str],
) -> frozenset[str]:
    if identifier in cache:
        return cache[identifier]
    if identifier in visiting:
        return frozenset()

    visiting.add(identifier)
    recipe = recipes[identifier]
    traits: set[str] = set()
    inputs = recipe.get("Input", {})
    if isinstance(inputs, Mapping):
        version = inputs.get("VERSION")
        if version not in (None, "") and "%" not in str(version):
            traits.add("fixed-version")

    process = recipe.get("Process", [])
    if isinstance(process, list):
        for step in process:
            if not isinstance(step, Mapping) or step.get("Processor") != "FileFinder":
                continue
            arguments = step.get("Arguments", {})
            pattern = arguments.get("pattern") if isinstance(arguments, Mapping) else None
            if isinstance(pattern, str) and pattern.startswith("/Applications/"):
                traits.add("local-payload")

    for value in nested_strings(process):
        if "%RECIPE_DIR%/" not in value:
            continue
        filename = value.rsplit("/", 1)[-1].lower()
        if not filename.endswith(LOCAL_IMAGE_SUFFIXES):
            traits.add("local-payload")

    parent = recipe.get("ParentRecipe")
    if isinstance(parent, str) and parent in recipes:
        traits.update(recipe_traits(parent, recipes, munki_names, cache, visiting))

    pkginfo = inputs.get("pkginfo", {}) if isinstance(inputs, Mapping) else {}
    requirements = pkginfo.get("requires", []) if isinstance(pkginfo, Mapping) else []
    if isinstance(requirements, list):
        for requirement in requirements:
            dependency = munki_names.get(requirement) if isinstance(requirement, str) else None
            if dependency and "local-payload" in recipe_traits(
                dependency, recipes, munki_names, cache, visiting
            ):
                traits.add("local-payload")

    visiting.remove(identifier)
    result = frozenset(traits)
    cache[identifier] = result
    return result


def recurring_recipes(recipes: Mapping[str, Mapping[str, Any]]) -> set[str]:
    munki_names: dict[str, str] = {}
    for identifier, recipe in recipes.items():
        if not identifier.startswith(SOURCE_PREFIX):
            continue
        inputs = recipe.get("Input", {})
        name = inputs.get("NAME") if isinstance(inputs, Mapping) else None
        if isinstance(name, str):
            munki_names[name] = identifier

    cache: dict[str, frozenset[str]] = {}
    return {
        identifier
        for identifier in recipes
        if identifier.startswith(SOURCE_PREFIX)
        and not recipe_traits(identifier, recipes, munki_names, cache, set())
    }


def source_recipes(repository: dict[str, str], repo_root: Path) -> set[str]:
    checkout = ensure_checkout(repository, repo_root)
    recipes, _ = recipe_index(checkout)
    identifiers = {
        identifier for identifier in recipes if identifier.startswith(SOURCE_PREFIX)
    }
    if not identifiers:
        raise ConfigError(f"{checkout}: no Woodleigh Munki recipes found")
    return identifiers


def check_source(manifest_path: Path, override_dir: Path, repo_root: Path) -> None:
    repository = source_repository(load_manifest(manifest_path))
    if repository is None:
        raise ConfigError(f"repositories.json must contain {SOURCE_URL}")

    source = source_recipes(repository, repo_root)
    overrides = load_overrides(override_dir)
    expected_overrides = {
        identifier.replace(SOURCE_PREFIX, OVERRIDE_PREFIX, 1) for identifier in source
    }
    stale = sorted(set(overrides) - expected_overrides)
    if stale:
        revision = repository["revision"][:7]
        details = [
            f"{identifier} has an override but is not present in pinned "
            f"woodleighschool/autopkg@{revision}."
            for identifier in stale
        ]
        raise ConfigError("Pinned source mismatch:\n  " + "\n  ".join(details))

    print(
        f"Pinned source {repository['revision'][:12]} contains all "
        f"{len(overrides)} Woodleigh overrides"
    )


def added_recipes(base: str, manifest_path: Path, repo_root: Path) -> dict[str, str]:
    previous = source_repository(manifest_at(base))
    current = source_repository(load_manifest(manifest_path))
    if previous is None or current is None or previous["url"] != current["url"]:
        return {}
    if previous["revision"] == current["revision"]:
        return {}

    checkout = ensure_checkout(current, repo_root)
    if git(
        checkout,
        "cat-file",
        "-e",
        f"{previous['revision']}^{{commit}}",
        check=False,
    ).returncode:
        git(checkout, "fetch", "--no-tags", "origin", previous["revision"])
    paths = git(
        checkout,
        "diff",
        "--diff-filter=A",
        "--name-only",
        previous["revision"],
        current["revision"],
        "--",
        "*.munki.recipe.yaml",
        capture=True,
    ).stdout.splitlines()
    recipes, identifiers_by_path = recipe_index(checkout)
    recurring = recurring_recipes(recipes)
    added: dict[str, str] = {}
    for path in paths:
        parent = identifiers_by_path.get(path)
        if parent is None or not parent.startswith(SOURCE_PREFIX):
            raise ConfigError(
                f"{current['revision']}:{path}: expected a {SOURCE_PREFIX} identifier"
            )
        if parent not in recurring:
            print(f"Skipping on-demand source recipe {parent}")
            continue
        override = parent.replace(SOURCE_PREFIX, OVERRIDE_PREFIX, 1)
        added[override] = parent
    return dict(sorted(added.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Woodleigh's recipe source policy")
    subparsers = parser.add_subparsers(dest="command", required=True)
    added = subparsers.add_parser("added")
    added.add_argument("--base", required=True)
    added.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    added.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    added.add_argument("--output", type=Path, required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    check.add_argument("--override-dir", type=Path, default=OVERRIDE_DIR)
    check.add_argument("--repo-root", type=Path, default=STATE_DIR / "woodleigh-source")
    arguments = parser.parse_args()
    try:
        if arguments.command == "added":
            recipes = added_recipes(
                arguments.base,
                arguments.manifest,
                arguments.repo_root,
            )
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(
                json.dumps(recipes, indent=2) + "\n", encoding="utf-8"
            )
            print(f"Selected {len(recipes)} new recurring Woodleigh recipes")
        else:
            check_source(
                arguments.manifest,
                arguments.override_dir,
                arguments.repo_root,
            )
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
