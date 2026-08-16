#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from ruamel.yaml import YAML

from common import (
    ConfigError,
    MANIFEST_PATH,
    NAME_PATTERN,
    OVERRIDE_DIR,
    REPO_ROOT,
    ROOT,
    STATE_DIR,
    load_manifest,
    load_overrides,
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


def override_identifier(path: str) -> str:
    name = PurePosixPath(path).name.removesuffix(".recipe.yaml")
    parts = name.split(".")
    identifier = "local." + ".".join(reversed(parts))
    if len(parts) < 2 or not NAME_PATTERN.fullmatch(identifier):
        raise ConfigError(f"{path}: cannot derive an override identifier")
    return identifier


def recipe_catalog(manifest: Mapping[str, Any], repo_root: Path) -> dict[str, str]:
    yaml = YAML(typ="safe")
    catalog: dict[str, str] = {}
    for repository in manifest["repositories"]:
        if repository.get("gitops") is not True:
            continue
        checkout = ensure_checkout(repository, repo_root)
        revision = repository["revision"]
        paths = [
            path
            for path in git(
                checkout,
                "ls-tree",
                "-r",
                "--name-only",
                revision,
                capture=True,
            ).stdout.splitlines()
            if path.endswith(".munki.recipe.yaml")
        ]
        for path in paths:
            result = git(
                checkout,
                "show",
                f"{revision}:{path}",
                capture=True,
            )
            recipe = yaml.load(result.stdout)
            if not isinstance(recipe, Mapping):
                raise ConfigError(f"{repository['name']}:{path}: recipe must be a mapping")
            marker = recipe.get("GitOps")
            if marker is not None and not isinstance(marker, bool):
                raise ConfigError(f"{repository['name']}:{path}: GitOps must be boolean")
            if marker is not True:
                continue
            parent = recipe.get("Identifier")
            if not isinstance(parent, str) or not NAME_PATTERN.fullmatch(parent):
                raise ConfigError(f"{repository['name']}:{path}: invalid Identifier")
            identifier = override_identifier(path)
            if identifier in catalog:
                raise ConfigError(
                    f"{repository['name']}:{path}: duplicate GitOps recipe {identifier}"
                )
            catalog[identifier] = parent
    return dict(sorted(catalog.items()))


def overrides_at(revision: str) -> dict[str, str]:
    yaml = YAML(typ="safe")
    overrides: dict[str, str] = {}
    paths = [
        path
        for path in git_output(
            "ls-tree", "-r", "--name-only", revision, "--", "RecipeOverrides"
        ).splitlines()
        if path.endswith(".munki.recipe.yaml")
    ]
    for path in paths:
        recipe = yaml.load(git_output("show", f"{revision}:{path}"))
        if not isinstance(recipe, Mapping):
            raise ConfigError(f"{revision}:{path}: recipe must be a mapping")
        identifier = recipe.get("Identifier")
        parent = recipe.get("ParentRecipe")
        if not isinstance(identifier, str) or not isinstance(parent, str):
            raise ConfigError(f"{revision}:{path}: invalid generated override")
        overrides[identifier] = parent
    return overrides


def build_state(base: str, manifest_path: Path, repo_root: Path) -> dict[str, object]:
    previous = recipe_catalog(manifest_at(base), repo_root)
    desired = recipe_catalog(load_manifest(manifest_path), repo_root)
    base_overrides = overrides_at(base)
    added = {
        identifier: parent
        for identifier, parent in desired.items()
        if identifier not in base_overrides
    }
    removed = (
        sorted(base_overrides.keys() - desired.keys())
        if previous or desired
        else []
    )
    return {
        "desired": desired,
        "added": added,
        "removed": removed,
    }


def load_state(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"Cannot read {path}: {error}") from error
    if not isinstance(value, dict) or set(value) != {"desired", "added", "removed"}:
        raise ConfigError(f"{path}: invalid source sync state")
    for key in ("desired", "added"):
        mapping = value[key]
        if not isinstance(mapping, dict) or not all(
            isinstance(identifier, str) and isinstance(parent, str)
            for identifier, parent in mapping.items()
        ):
            raise ConfigError(f"{path}: invalid {key} recipes")
    removed = value["removed"]
    if not isinstance(removed, list) or not all(
        isinstance(identifier, str) for identifier in removed
    ):
        raise ConfigError(f"{path}: invalid removed recipes")
    return value


def check_sources(manifest_path: Path, override_dir: Path, repo_root: Path) -> None:
    desired = recipe_catalog(load_manifest(manifest_path), repo_root)
    overrides = load_overrides(override_dir)
    missing = sorted(desired.keys() - overrides.keys())
    stale = sorted(overrides.keys() - desired.keys()) if desired else []
    mismatched = sorted(
        identifier
        for identifier, parent in desired.items()
        if identifier in overrides and overrides[identifier][1].get("ParentRecipe") != parent
    )
    details = [f"{identifier}: generated override is missing" for identifier in missing]
    details.extend(f"{identifier}: generated override is stale" for identifier in stale)
    details.extend(
        f"{identifier}: generated override has the wrong parent" for identifier in mismatched
    )
    if details:
        raise ConfigError("GitOps recipe source mismatch:\n  " + "\n  ".join(details))
    print(f"Validated {len(desired)} declared GitOps recipes")


def prune(state_path: Path, override_dir: Path) -> None:
    state = load_state(state_path)
    overrides = load_overrides(override_dir)
    removed = state["removed"]
    for identifier in removed:
        if identifier not in overrides:
            print(f"Already removed {identifier}")
            continue
        path = overrides[identifier][0]
        if path.parent.resolve() != override_dir.resolve() or path.is_symlink():
            raise ConfigError(f"{identifier}: unsafe generated override path {path}")
        path.unlink()
        print(f"Removed {identifier}")


def print_active(state_path: Path, recipes: list[str]) -> None:
    removed = set(load_state(state_path)["removed"])
    for recipe in recipes:
        if recipe not in removed:
            print(recipe)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync declared GitOps recipes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--base", required=True)
    build.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    build.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    build.add_argument("--output", type=Path, required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    check.add_argument("--override-dir", type=Path, default=OVERRIDE_DIR)
    check.add_argument("--repo-root", type=Path, default=STATE_DIR / "recipe-sources")
    prune_parser = subparsers.add_parser("prune")
    prune_parser.add_argument("--state", type=Path, required=True)
    prune_parser.add_argument("--override-dir", type=Path, default=OVERRIDE_DIR)
    active = subparsers.add_parser("active")
    active.add_argument("--state", type=Path, required=True)
    active.add_argument("recipes", nargs="+")
    arguments = parser.parse_args()

    try:
        if arguments.command == "build":
            state = build_state(arguments.base, arguments.manifest, arguments.repo_root)
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(
                json.dumps(state, indent=2) + "\n", encoding="utf-8"
            )
            print(
                f"Declared {len(state['desired'])} recipes: "
                f"{len(state['added'])} added, {len(state['removed'])} removed"
            )
        elif arguments.command == "check":
            check_sources(arguments.manifest, arguments.override_dir, arguments.repo_root)
        elif arguments.command == "prune":
            prune(arguments.state, arguments.override_dir)
        else:
            print_active(arguments.state, arguments.recipes)
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
