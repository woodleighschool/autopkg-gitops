#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path

from ruamel.yaml import YAML

from common import ConfigError, MANIFEST_PATH, OVERRIDE_DIR, STATE_DIR, load_manifest, load_overrides
from repositories import ensure_checkout


SOURCE_URL = "https://github.com/woodleighschool/autopkg"
SOURCE_PREFIX = "com.github.woodleighschool.munki."
OVERRIDE_PREFIX = "local.munki."


def canonical_url(value: str) -> str:
    return value.removesuffix(".git").removesuffix("/")


def source_repository(manifest: Mapping[str, object]) -> dict[str, str]:
    matches = [
        repository
        for repository in manifest["repositories"]
        if canonical_url(repository["url"]) == SOURCE_URL
    ]
    if len(matches) != 1:
        raise ConfigError(f"repositories.json must contain exactly one {SOURCE_URL} entry")
    return matches[0]


def source_recipes(repository: dict[str, str], repo_root: Path) -> set[str]:
    checkout = ensure_checkout(repository, repo_root)
    yaml = YAML(typ="safe")
    identifiers: set[str] = set()
    for path in sorted(checkout.rglob("*.munki.recipe.yaml")):
        recipe = yaml.load(path.read_text(encoding="utf-8"))
        if not isinstance(recipe, Mapping):
            raise ConfigError(f"{path}: recipe must be a mapping")
        identifier = recipe.get("Identifier")
        if not isinstance(identifier, str) or not identifier.startswith(SOURCE_PREFIX):
            raise ConfigError(f"{path}: expected a {SOURCE_PREFIX} identifier")
        if identifier in identifiers:
            raise ConfigError(f"{path}: duplicate recipe identifier {identifier}")
        identifiers.add(identifier)
    if not identifiers:
        raise ConfigError(f"{checkout}: no Woodleigh Munki recipes found")
    return identifiers


def check(manifest_path: Path, override_dir: Path, repo_root: Path) -> None:
    manifest = load_manifest(manifest_path)
    repository = source_repository(manifest)
    source = source_recipes(repository, repo_root)
    overrides = load_overrides(override_dir)
    expected_overrides = {
        identifier.replace(SOURCE_PREFIX, OVERRIDE_PREFIX, 1) for identifier in source
    }
    actual_overrides = set(overrides)

    stale = sorted(actual_overrides - expected_overrides)
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
        f"{len(actual_overrides)} recurring recipe overrides"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check recurring overrides exist in the pinned Woodleigh source"
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--override-dir", type=Path, default=OVERRIDE_DIR)
    parser.add_argument("--repo-root", type=Path, default=STATE_DIR / "pinned-source")
    arguments = parser.parse_args()
    try:
        check(arguments.manifest, arguments.override_dir, arguments.repo_root)
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
