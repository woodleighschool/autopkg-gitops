#!/usr/bin/env python3
from __future__ import annotations

import argparse
import plistlib
from pathlib import Path

from common import (
    ConfigError,
    MANIFEST_PATH,
    OVERRIDE_DIR,
    REPO_ROOT,
    ROOT,
    STATE_DIR,
    load_manifest,
    repository_map,
)


def write_preferences(
    state_dir: Path,
    repo_root: Path,
    override_dir: Path,
    recipes_dir: Path,
    manifest_path: Path,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)
    manifest_repositories = manifest["repositories"]
    assert isinstance(manifest_repositories, list)
    names = [repository["name"] for repository in manifest_repositories]

    repositories = repository_map(manifest)
    paths = [repo_root / name for name in names]
    for name, path in zip(names, paths, strict=True):
        if not path.is_dir():
            raise ConfigError(f"{name}: repository is not materialized at {path}")

    if not override_dir.is_dir():
        raise ConfigError(f"Override directory is missing: {override_dir}")

    search_dirs = [str(path) for path in paths]
    if recipes_dir.is_dir():
        search_dirs.insert(0, str(recipes_dir))

    preferences = {
        "RECIPE_MAP_PATH": str(state_dir / "recipe-map.json"),
        "RECIPE_OVERRIDE_DIRS": [str(override_dir)],
        "RECIPE_REPOS": {
            str(path): {"URL": repositories[name]["url"]}
            for name, path in zip(names, paths, strict=True)
        },
        "RECIPE_SEARCH_DIRS": search_dirs,
    }
    with (state_dir / "preferences.plist").open("wb") as output:
        plistlib.dump(preferences, output, sort_keys=False)
    print(f"Wrote preferences for {len(names)} repositories")


def main() -> int:
    parser = argparse.ArgumentParser(description="Write preferences")
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--override-dir", type=Path, default=OVERRIDE_DIR)
    parser.add_argument("--recipes-dir", type=Path, default=ROOT / "Recipes")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    arguments = parser.parse_args()
    try:
        write_preferences(
            arguments.state_dir,
            arguments.repo_root,
            arguments.override_dir,
            arguments.recipes_dir,
            arguments.manifest,
        )
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
