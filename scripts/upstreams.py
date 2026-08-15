#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from common import (
    ConfigError,
    MANIFEST_PATH,
    NAME_PATTERN,
    REPO_ROOT,
    ROOT,
    iter_trust_paths,
    load_manifest,
    load_overrides,
    repository_map,
    repository_reference,
    validate_manifest,
)
from repositories import ensure_checkout, git


WOODLEIGH_SOURCE = "https://github.com/woodleighschool/autopkg"
WOODLEIGH_SOURCE_PREFIX = "com.github.woodleighschool.munki."
LOCAL_OVERRIDE_PREFIX = "local.munki."
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


def overrides_at(revision: str) -> dict[str, tuple[Path, Mapping[str, Any]]]:
    yaml = YAML(typ="safe")
    paths = [
        path
        for path in git_output(
            "ls-tree", "-r", "--name-only", revision, "--", "RecipeOverrides"
        ).splitlines()
        if path.endswith(".munki.recipe.yaml")
    ]
    overrides: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    for relative_path in paths:
        source = f"{revision}:{relative_path}"
        recipe = yaml.load(git_output("show", source))
        if not isinstance(recipe, Mapping):
            raise ConfigError(f"{source}: recipe must be a mapping")
        identifier = recipe.get("Identifier")
        if not isinstance(identifier, str) or not NAME_PATTERN.fullmatch(identifier):
            raise ConfigError(f"{source}: missing or invalid Identifier")
        if identifier in overrides:
            raise ConfigError(f"{revision}: duplicate override identifier {identifier}")
        overrides[identifier] = (Path(relative_path), recipe)
    return overrides


def references_by_recipe(
    overrides: Mapping[str, tuple[Path, Mapping[str, Any]]],
    repositories: list[dict[str, str]],
) -> dict[str, dict[str, set[str]]]:
    references: dict[str, dict[str, set[str]]] = {}
    for identifier, (path, recipe) in overrides.items():
        trust = recipe.get("ParentRecipeTrustInfo")
        if not isinstance(trust, Mapping):
            raise ConfigError(f"{path}: missing ParentRecipeTrustInfo")
        recipe_references: dict[str, set[str]] = {}
        for trust_path in iter_trust_paths(trust):
            reference = repository_reference(trust_path, repositories)
            if reference is None:
                raise ConfigError(
                    f"{path}: cannot map trusted path to repositories.json: {trust_path}"
                )
            name, relative = reference
            recipe_references.setdefault(name, set()).add(relative)
        references[identifier] = recipe_references
    return references


def processor_references_by_recipe(
    overrides: Mapping[str, tuple[Path, Mapping[str, Any]]],
    repositories: list[dict[str, str]],
) -> dict[str, dict[str, dict[str, set[str]]]]:
    references: dict[str, dict[str, dict[str, set[str]]]] = {}
    for identifier, (path, recipe) in overrides.items():
        trust = recipe.get("ParentRecipeTrustInfo")
        if not isinstance(trust, Mapping):
            raise ConfigError(f"{path}: missing ParentRecipeTrustInfo")
        processors = trust.get("non_core_processors", {})
        if not isinstance(processors, Mapping):
            raise ConfigError(f"{path}: non_core_processors must be a mapping")
        recipe_references: dict[str, dict[str, set[str]]] = {}
        for processor, details in processors.items():
            if not isinstance(processor, str) or not isinstance(details, Mapping):
                raise ConfigError(f"{path}: invalid non-core processor trust entry")
            trust_path = details.get("path")
            if not isinstance(trust_path, str):
                raise ConfigError(f"{path}: {processor} is missing its trusted path")
            reference = repository_reference(trust_path, repositories)
            if reference is None:
                raise ConfigError(
                    f"{path}: cannot map trusted path to repositories.json: {trust_path}"
                )
            name, relative = reference
            recipe_references.setdefault(name, {}).setdefault(relative, set()).add(
                processor
            )
        references[identifier] = recipe_references
    return references


def file_diff_url(
    previous: dict[str, str] | None, current: dict[str, str], path: str
) -> str:
    repository_url = current["url"].removesuffix(".git").removesuffix("/")
    anchor = hashlib.sha256(path.encode()).hexdigest()
    if previous is not None and previous["url"] == current["url"]:
        location = f"compare/{previous['revision']}...{current['revision']}"
    else:
        location = f"commit/{current['revision']}"
    return f"{repository_url}/{location}#diff-{anchor}"


def changed_paths(
    previous: dict[str, str], current: dict[str, str], repo_root: Path
) -> set[str] | None:
    if previous["url"] != current["url"] or previous["ref"] != current["ref"]:
        return None
    destination = ensure_checkout(current, repo_root)
    old_revision = previous["revision"]
    if git(
        destination, "cat-file", "-e", f"{old_revision}^{{commit}}", check=False
    ).returncode:
        git(destination, "fetch", "--no-tags", "origin", old_revision)
    return set(
        git(
            destination,
            "diff",
            "--no-renames",
            "--name-only",
            old_revision,
            current["revision"],
            capture=True,
        ).stdout.splitlines()
    )


def nested_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from nested_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_strings(child)


def woodleigh_recipe_index(
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


def recurring_woodleigh_recipes(
    recipes: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    munki_names: dict[str, str] = {}
    for identifier, recipe in recipes.items():
        if not identifier.startswith(WOODLEIGH_SOURCE_PREFIX):
            continue
        inputs = recipe.get("Input", {})
        name = inputs.get("NAME") if isinstance(inputs, Mapping) else None
        if isinstance(name, str):
            munki_names[name] = identifier

    cache: dict[str, frozenset[str]] = {}
    return {
        identifier
        for identifier in recipes
        if identifier.startswith(WOODLEIGH_SOURCE_PREFIX)
        and not recipe_traits(identifier, recipes, munki_names, cache, set())
    }


def added_woodleigh_recipes(
    previous: dict[str, str] | None,
    current: dict[str, str],
    repo_root: Path,
) -> list[str]:
    if current["url"].removesuffix(".git").removesuffix("/") != WOODLEIGH_SOURCE:
        return []
    if previous is None or previous["url"] != current["url"]:
        return []

    destination = ensure_checkout(current, repo_root)
    paths = git(
        destination,
        "diff",
        "--diff-filter=A",
        "--name-only",
        previous["revision"],
        current["revision"],
        "--",
        "*.munki.recipe.yaml",
        capture=True,
    ).stdout.splitlines()
    recipes, identifiers_by_path = woodleigh_recipe_index(destination)
    recurring = recurring_woodleigh_recipes(recipes)
    identifiers: list[str] = []
    for path in paths:
        identifier = identifiers_by_path.get(path)
        if identifier is None or not identifier.startswith(WOODLEIGH_SOURCE_PREFIX):
            raise ConfigError(
                f"{current['revision']}:{path}: expected a {WOODLEIGH_SOURCE_PREFIX} identifier"
            )
        if identifier not in recurring:
            print(f"Skipping on-demand source recipe {identifier}")
            continue
        identifiers.append(identifier.replace(WOODLEIGH_SOURCE_PREFIX, LOCAL_OVERRIDE_PREFIX, 1))
    return sorted(identifiers)


def affected_recipes(
    base: str, manifest_path: Path, repo_root: Path
) -> tuple[list[str], list[str], list[dict[str, str]], list[str]]:
    previous_manifest = manifest_at(base)
    current_manifest = load_manifest(manifest_path)
    previous_repositories = repository_map(previous_manifest)
    current_repositories = repository_map(current_manifest)
    previous_references = references_by_recipe(
        overrides_at(base), previous_manifest["repositories"]
    )
    previous_processors = processor_references_by_recipe(
        overrides_at(base), previous_manifest["repositories"]
    )
    current_overrides = load_overrides()
    current_references = references_by_recipe(
        current_overrides, current_manifest["repositories"]
    )
    current_processors = processor_references_by_recipe(
        current_overrides, current_manifest["repositories"]
    )

    changed_names = [
        name
        for name, repository in current_repositories.items()
        if name not in previous_repositories
        or repository != previous_repositories[name]
    ]
    affected: set[str] = set()
    added: set[str] = set()
    changed_processors: set[tuple[str, str, str, str]] = set()
    for name in changed_names:
        current = current_repositories[name]
        previous = previous_repositories.get(name)
        added.update(added_woodleigh_recipes(previous, current, repo_root))
        paths = None if previous is None else changed_paths(previous, current, repo_root)
        matching = 0
        for identifier in current_overrides:
            trusted_paths = set()
            trusted_paths.update(previous_references.get(identifier, {}).get(name, set()))
            trusted_paths.update(current_references.get(identifier, {}).get(name, set()))
            if trusted_paths and (paths is None or trusted_paths & paths):
                affected.add(identifier)
                matching += 1

                processor_paths: dict[str, set[str]] = {}
                for recipe_processors in (previous_processors, current_processors):
                    for processor_path, processors in (
                        recipe_processors.get(identifier, {}).get(name, {}).items()
                    ):
                        processor_paths.setdefault(processor_path, set()).update(processors)
                for processor_path, processors in processor_paths.items():
                    if paths is not None and processor_path not in paths:
                        continue
                    url = file_diff_url(previous, current, processor_path)
                    for processor in processors:
                        changed_processors.add(
                            (identifier, processor, processor_path, url)
                        )
        detail = "all referenced paths" if paths is None else f"{len(paths)} changed files"
        print(f"{name}: {detail}, {matching} affected overrides")
    processors = [
        {
            "recipe": recipe,
            "processor": processor,
            "path": path,
            "url": url,
        }
        for recipe, processor, path, url in sorted(changed_processors)
    ]
    affected.update(added)
    return sorted(affected), changed_names, processors, sorted(added)


def write_github_output(
    recipes: list[str],
    repositories: list[str],
    processors: list[dict[str, str]],
    added: list[str],
) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        raise ConfigError("GITHUB_OUTPUT is not set")
    with Path(output_path).open("a", encoding="utf-8") as output:
        output.write(f"changed={'true' if recipes else 'false'}\n")
        output.write(f"repositories={json.dumps(repositories, separators=(',', ':'))}\n")
        output.write(f"processors={json.dumps(processors, separators=(',', ':'))}\n")
        output.write("added<<AUTOPKG_ADDED_RECIPES\n")
        output.write("\n".join(added))
        output.write("\nAUTOPKG_ADDED_RECIPES\n")
        output.write("recipes<<AUTOPKG_RECIPES\n")
        output.write("\n".join(recipes))
        output.write("\nAUTOPKG_RECIPES\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Select overrides affected by pinned upstream changes"
    )
    parser.add_argument("--base", required=True)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--github-output", action="store_true")
    arguments = parser.parse_args()

    try:
        recipes, repositories, processors, added = affected_recipes(
            arguments.base, arguments.manifest, arguments.repo_root
        )
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(
                "".join(f"{recipe}\n" for recipe in recipes), encoding="utf-8"
            )
        if arguments.github_output:
            write_github_output(recipes, repositories, processors, added)
        print(f"Selected {len(recipes)} affected overrides")
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
