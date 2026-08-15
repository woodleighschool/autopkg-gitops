#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
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


def affected_recipes(
    base: str, manifest_path: Path, repo_root: Path
) -> tuple[list[str], list[str], list[dict[str, str]]]:
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
    changed_processors: set[tuple[str, str, str, str]] = set()
    for name in changed_names:
        current = current_repositories[name]
        previous = previous_repositories.get(name)
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
    return sorted(affected), changed_names, processors


def write_github_output(
    recipes: list[str], repositories: list[str], processors: list[dict[str, str]]
) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        raise ConfigError("GITHUB_OUTPUT is not set")
    with Path(output_path).open("a", encoding="utf-8") as output:
        output.write(f"changed={'true' if recipes else 'false'}\n")
        output.write(f"repositories={json.dumps(repositories, separators=(',', ':'))}\n")
        output.write(f"processors={json.dumps(processors, separators=(',', ':'))}\n")
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
        recipes, repositories, processors = affected_recipes(
            arguments.base, arguments.manifest, arguments.repo_root
        )
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(
                "".join(f"{recipe}\n" for recipe in recipes), encoding="utf-8"
            )
        if arguments.github_output:
            write_github_output(recipes, repositories, processors)
        print(f"Selected {len(recipes)} affected overrides")
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
