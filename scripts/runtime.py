#!/usr/bin/env python3
from __future__ import annotations

import argparse
import filecmp
import glob
import json
import plistlib
import re
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from common import (
    ConfigError,
    MANIFEST_PATH,
    OVERRIDE_DIR,
    REPO_ROOT,
    STATE_DIR,
    load_manifest,
    load_overrides,
    load_selection,
    repository_reference,
)


VARIABLE = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


def parse_recipe(data: bytes, source: Path | str) -> Mapping[str, Any]:
    try:
        if str(source).endswith((".yaml", ".yml")):
            value = YAML(typ="safe").load(data.decode("utf-8"))
        else:
            value = plistlib.loads(data)
    except (UnicodeDecodeError, plistlib.InvalidFileException) as error:
        raise ConfigError(f"Cannot parse recipe {source}: {error}") from error
    if not isinstance(value, Mapping):
        raise ConfigError(f"{source}: recipe must be a mapping")
    return value


def load_recipe(path: Path) -> Mapping[str, Any]:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ConfigError(f"Cannot read recipe {path}: {error}") from error
    return parse_recipe(data, path)


def nested_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from nested_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_strings(child)


def substitute(value: str, inputs: Mapping[str, Any]) -> str:
    resolved = value
    for _ in range(8):
        updated = VARIABLE.sub(
            lambda match: str(inputs.get(match.group(1), match.group(0))), resolved
        )
        if updated == resolved:
            return updated
        resolved = updated
    return resolved


def normalized_resource_pattern(
    value: str,
    inputs: Mapping[str, Any],
    *,
    marker_required: bool,
) -> str | None:
    resolved = substitute(value, inputs)
    marker = "%RECIPE_DIR%/"
    if marker not in resolved:
        if marker_required:
            return None
        relative = resolved
    else:
        if not resolved.startswith(marker):
            raise ConfigError(f"Unsupported embedded %RECIPE_DIR% path: {resolved}")
        relative = resolved.removeprefix(marker)
    if VARIABLE.search(relative):
        raise ConfigError(f"Cannot resolve recipe resource path: {resolved}")
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ConfigError(f"Recipe resource escapes its directory: {resolved}")
    return relative


def resource_patterns(recipe: Mapping[str, Any], inputs: Mapping[str, Any]) -> set[str]:
    recipe_inputs = recipe.get("Input", {})
    if not isinstance(recipe_inputs, Mapping):
        raise ConfigError("Recipe Input must be a mapping")
    resolved_inputs = {**recipe_inputs, **inputs}
    patterns: set[str] = set()
    for value in nested_strings(
        {"Input": recipe_inputs, "Process": recipe.get("Process", [])}
    ):
        pattern = normalized_resource_pattern(
            value,
            resolved_inputs,
            marker_required=True,
        )
        if pattern is not None:
            patterns.add(pattern)

    process = recipe.get("Process", [])
    if not isinstance(process, list):
        raise ConfigError("Recipe Process must be a list")
    for step in process:
        if not isinstance(step, Mapping) or step.get("Processor") != "PkgCreator":
            continue
        arguments = step.get("Arguments", {})
        request = arguments.get("pkg_request", {}) if isinstance(arguments, Mapping) else {}
        scripts = request.get("scripts") if isinstance(request, Mapping) else None
        if scripts in (None, ""):
            continue
        if not isinstance(scripts, str):
            raise ConfigError("PkgCreator scripts must be a string")
        pattern = normalized_resource_pattern(
            scripts,
            resolved_inputs,
            marker_required=False,
        )
        if pattern:
            patterns.add(pattern)
    return patterns


def existing_resource_root(recipe_dir: Path, relative: str) -> list[Path]:
    candidate = recipe_dir / relative
    if glob.has_magic(relative):
        matches = [Path(path) for path in glob.glob(str(candidate), recursive=True)]
        if not matches:
            raise ConfigError(f"Recipe resource pattern has no matches: {candidate}")
        return matches
    if candidate.exists():
        return [candidate]

    ancestor = candidate
    while ancestor != recipe_dir:
        ancestor = ancestor.parent
        if ancestor.is_file():
            return [ancestor]
    raise ConfigError(f"Recipe resource does not exist: {candidate}")


def copy_file(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise ConfigError(f"Recipe resources may not be symbolic links: {source}")
    if destination.exists():
        if not destination.is_file() or not filecmp.cmp(source, destination, shallow=False):
            raise ConfigError(f"Conflicting recipe resources target {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_resource(source: Path, recipe_dir: Path, bundle: Path) -> None:
    relative = source.relative_to(recipe_dir)
    current = recipe_dir
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ConfigError(f"Recipe resources may not be symbolic links: {current}")
    destination = bundle / relative
    if source.is_dir():
        for child in sorted(source.rglob("*")):
            if child.is_symlink():
                raise ConfigError(f"Recipe resources may not be symbolic links: {child}")
            if child.is_dir():
                continue
            copy_file(child, destination / child.relative_to(source))
    else:
        copy_file(source, destination)


def parent_recipe_paths(
    override_path: Path,
    override: Mapping[str, Any],
    repositories: list[dict[str, str]],
    repo_root: Path,
) -> list[Path]:
    trust = override.get("ParentRecipeTrustInfo")
    parents = trust.get("parent_recipes") if isinstance(trust, Mapping) else None
    if not isinstance(parents, Mapping):
        raise ConfigError(f"{override_path}: missing parent recipe trust paths")
    paths: list[Path] = []
    for details in parents.values():
        trust_path = details.get("path") if isinstance(details, Mapping) else None
        if not isinstance(trust_path, str):
            raise ConfigError(f"{override_path}: parent recipe is missing its trusted path")
        reference = repository_reference(trust_path, repositories)
        if reference is None:
            raise ConfigError(f"{override_path}: cannot map trusted path: {trust_path}")
        repository, relative = reference
        path = repo_root / repository / relative
        if not path.is_file():
            raise ConfigError(f"{override_path}: parent recipe is not materialized at {path}")
        paths.append(path)
    return paths


def prepare(
    state_dir: Path,
    repo_root: Path,
    manifest_path: Path,
    override_dir: Path,
) -> None:
    manifest = load_manifest(manifest_path)
    overrides = load_overrides(override_dir)
    selected = load_selection(state_dir)["recipes"]
    if not selected:
        raise ConfigError(f"{state_dir / 'selection.json'}: no recipes selected")
    runtime_root = state_dir / "overrides"
    runtime_root.mkdir(parents=True, exist_ok=True)
    prepared: list[str] = []

    for identifier in selected:
        if identifier not in overrides:
            raise ConfigError(f"{identifier}: generated override is missing")
        override_path, override = overrides[identifier]
        bundle = runtime_root / identifier
        if bundle.exists():
            shutil.rmtree(bundle)
        bundle.mkdir()
        shutil.copy2(override_path, bundle / override_path.name)
        inputs = override.get("Input", {})
        if not isinstance(inputs, Mapping):
            raise ConfigError(f"{override_path}: Input must be a mapping")

        resources = 0
        for recipe_path in parent_recipe_paths(
            override_path,
            override,
            manifest["repositories"],
            repo_root,
        ):
            recipe = load_recipe(recipe_path)
            for pattern in sorted(resource_patterns(recipe, inputs)):
                for source in existing_resource_root(recipe_path.parent, pattern):
                    copy_resource(source, recipe_path.parent, bundle)
                    resources += 1
        prepared.append(str(bundle))
        print(f"{identifier}: prepared {resources} recipe resources")

    (state_dir / "override-dirs.json").write_text(
        json.dumps(prepared, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare isolated runtime recipe overrides")
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--override-dir", type=Path, default=OVERRIDE_DIR)
    arguments = parser.parse_args()
    try:
        prepare(
            arguments.state_dir,
            arguments.repo_root,
            arguments.manifest,
            arguments.override_dir,
        )
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
