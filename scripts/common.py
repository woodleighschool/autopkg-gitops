from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "repositories.json"
OVERRIDE_DIR = ROOT / "RecipeOverrides"
REPO_ROOT = Path(
    os.environ.get("AUTOPKG_REPO_ROOT", Path.home() / "Library/AutoPkg/RecipeRepos")
).expanduser()
STATE_DIR = Path(os.environ.get("AUTOPKG_STATE_DIR", ROOT / ".autopkg-run")).expanduser()

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")


class ConfigError(RuntimeError):
    pass


def validate_manifest(manifest: object, source: Path | str) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ConfigError(f"{source}: version must be 1")
    repositories = manifest.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise ConfigError(f"{source}: repositories must be a non-empty array")

    names: set[str] = set()
    urls: set[str] = set()
    for index, repository in enumerate(repositories):
        location = f"{source}: repositories[{index}]"
        if not isinstance(repository, dict):
            raise ConfigError(f"{location} must be an object")
        if set(repository) != {"name", "url", "ref", "revision"}:
            raise ConfigError(f"{location} must contain name, url, ref, and revision")

        name = repository["name"]
        url = repository["url"]
        ref = repository["ref"]
        revision = repository["revision"]
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
            raise ConfigError(f"{location}: invalid name")
        if name in names:
            raise ConfigError(f"{location}: duplicate name {name}")
        names.add(name)
        if not isinstance(url, str) or not url.startswith("https://github.com/"):
            raise ConfigError(f"{location}: url must be an HTTPS GitHub repository")
        canonical_url = url.removesuffix(".git").removesuffix("/")
        if canonical_url in urls:
            raise ConfigError(f"{location}: duplicate url {url}")
        urls.add(canonical_url)
        if not isinstance(ref, str) or not REF_PATTERN.fullmatch(ref) or ".." in ref:
            raise ConfigError(f"{location}: invalid ref")
        if not isinstance(revision, str) or not SHA_PATTERN.fullmatch(revision):
            raise ConfigError(f"{location}: revision must be a lowercase 40-character SHA")
    return manifest


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"Cannot read {path}: {error}") from error
    return validate_manifest(manifest, path)


def load_override(path: Path) -> Mapping[str, Any]:
    yaml = YAML(typ="safe")
    try:
        recipe = yaml.load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigError(f"Cannot read {path}: {error}") from error
    if not isinstance(recipe, Mapping):
        raise ConfigError(f"{path}: recipe must be a mapping")
    identifier = recipe.get("Identifier")
    if not isinstance(identifier, str) or not NAME_PATTERN.fullmatch(identifier):
        raise ConfigError(f"{path}: missing or invalid Identifier")
    return recipe


def load_overrides(
    directory: Path = OVERRIDE_DIR,
) -> dict[str, tuple[Path, Mapping[str, Any]]]:
    overrides: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    for path in sorted(directory.glob("*.munki.recipe.yaml")):
        recipe = load_override(path)
        identifier = recipe["Identifier"]
        if identifier in overrides:
            raise ConfigError(f"Duplicate override identifier: {identifier}")
        overrides[identifier] = (path, recipe)
    if not overrides:
        raise ConfigError(f"{directory}: no overrides found")
    return overrides


def expected_override_header(identifier: str) -> list[str]:
    return [
        "# Generated file. DO NOT EDIT.",
        f"# Refresh with: mise run trust:update {identifier}",
    ]


def validate_override_headers(
    overrides: Mapping[str, tuple[Path, Mapping[str, Any]]],
) -> None:
    for identifier, (path, _) in overrides.items():
        actual = path.read_text(encoding="utf-8").splitlines()[:2]
        if actual != expected_override_header(identifier):
            raise ConfigError(f"{path}: missing generated-file header; run mise run format")


def select_recipes(requested: list[str], available: list[str]) -> list[str]:
    aliases = {
        alias: identifier
        for identifier in available
        for alias in (identifier, identifier.removeprefix("local.munki."))
    }
    unknown = sorted(set(requested) - aliases.keys())
    if unknown:
        raise ConfigError(f"Unknown recipe: {', '.join(unknown)}")
    return [aliases[item] for item in requested] if requested else available


def iter_trust_paths(value: object) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "path" and isinstance(child, str):
                yield child
            else:
                yield from iter_trust_paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_trust_paths(child)


def repository_reference(
    trust_path: str, repositories: list[dict[str, str]]
) -> tuple[str, str] | None:
    normalized = trust_path.replace("\\", "/")
    recipe_repos_marker = "/RecipeRepos/"
    if recipe_repos_marker in normalized:
        remainder = normalized.split(recipe_repos_marker, 1)[1]
        name, separator, relative = remainder.partition("/")
        if separator and any(repository["name"] == name for repository in repositories):
            return name, relative

    for repository in repositories:
        slug = repository["url"].removesuffix(".git").removesuffix("/").split(
            "github.com/", 1
        )[-1]
        marker = f"/{slug}/"
        if marker in normalized:
            return repository["name"], normalized.split(marker, 1)[1]
    return None


def trust_references(
    recipes: Iterable[str],
    overrides: Mapping[str, tuple[Path, Mapping[str, Any]]],
    repositories: list[dict[str, str]],
) -> dict[str, set[str]]:
    references: dict[str, set[str]] = {}
    for identifier in recipes:
        if identifier not in overrides:
            raise ConfigError(f"{identifier}: recipe has no generated override")
        path, override = overrides[identifier]
        trust = override.get("ParentRecipeTrustInfo")
        if not isinstance(trust, Mapping):
            raise ConfigError(f"{path}: missing ParentRecipeTrustInfo")
        for trust_path in iter_trust_paths(trust):
            reference = repository_reference(trust_path, repositories)
            if reference is None:
                raise ConfigError(f"{path}: cannot map trusted path to repositories.json: {trust_path}")
            name, relative = reference
            references.setdefault(name, set()).add(relative)
    return references


def repository_map(manifest: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    return {repository["name"]: repository for repository in manifest["repositories"]}
