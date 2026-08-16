#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import plistlib
from pathlib import Path

from common import ConfigError, MANIFEST_PATH, REPO_ROOT, STATE_DIR, load_manifest, repository_map


def write_preferences(
    state_dir: Path,
    repo_root: Path,
    override_dirs: list[Path] | None,
    manifest_path: Path,
    all_repositories: bool,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)
    if all_repositories:
        names = [repository["name"] for repository in manifest["repositories"]]
    else:
        try:
            selection = json.loads((state_dir / "selection.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigError(f"Cannot read {state_dir / 'selection.json'}: {error}") from error
        names = selection.get("repositories")
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ConfigError(f"{state_dir / 'selection.json'}: invalid repositories")

    repositories = repository_map(manifest)
    paths = [repo_root / name for name in names]
    for name, path in zip(names, paths, strict=True):
        if not path.is_dir():
            raise ConfigError(f"{name}: repository is not materialized at {path}")

    if override_dirs is None:
        override_dirs_path = state_dir / "override-dirs.json"
        try:
            values = json.loads(override_dirs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigError(f"Cannot read {override_dirs_path}: {error}") from error
        if not isinstance(values, list) or not values or not all(
            isinstance(value, str) for value in values
        ):
            raise ConfigError(f"{override_dirs_path}: invalid override directories")
        override_dirs = [Path(value) for value in values]
    for override_dir in override_dirs:
        if not override_dir.is_dir():
            raise ConfigError(f"Runtime override directory is missing: {override_dir}")

    preferences = {
        "RECIPE_MAP_PATH": str(state_dir / "recipe-map.json"),
        "RECIPE_OVERRIDE_DIRS": [str(path) for path in override_dirs],
        "RECIPE_REPOS": {
            str(path): {"URL": repositories[name]["url"]}
            for name, path in zip(names, paths, strict=True)
        },
        "RECIPE_SEARCH_DIRS": [str(path) for path in paths],
    }
    with (state_dir / "preferences.plist").open("wb") as output:
        plistlib.dump(preferences, output, sort_keys=False)
    print(f"Configured AutoPkg with {len(names)} repositories")


def main() -> int:
    parser = argparse.ArgumentParser(description="Write ephemeral AutoPkg preferences")
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--override-dir", type=Path, action="append")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--all-repositories", action="store_true")
    arguments = parser.parse_args()
    try:
        write_preferences(
            arguments.state_dir,
            arguments.repo_root,
            arguments.override_dir,
            arguments.manifest,
            arguments.all_repositories,
        )
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
