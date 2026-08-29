from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from ruamel.yaml import YAML


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "repositories.json"
OVERRIDE_DIR = ROOT / "RecipeOverrides"
REPO_ROOT = Path(
    os.environ.get("AUTOPKG_REPO_ROOT", Path.home() / "Library/AutoPkg/RecipeRepos")
).expanduser()
STATE_DIR = Path(os.environ.get("AUTOPKG_STATE_DIR", ROOT / ".autopkg-run")).expanduser()

NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class ConfigError(RuntimeError):
    pass


def repository_name(url: str) -> str:
    parts = urlparse(url)
    domain = parts.netloc.rsplit("@", 1)[-1].split(":", 1)[0]
    reverse_domain = ".".join(reversed(domain.split(".")))
    path = os.path.splitext(parts.path)[0]
    return reverse_domain + path.replace("/", ".")


def validate_manifest(manifest: object, source: Path | str) -> dict[str, object]:
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ConfigError(f"{source}: version must be 1")
    values = manifest.get("repositories")
    if not isinstance(values, list) or not values:
        raise ConfigError(f"{source}: repositories must be a non-empty array")

    repositories: list[dict[str, str]] = []
    names: set[str] = set()
    urls: set[str] = set()
    for index, repository in enumerate(values):
        location = f"{source}: repositories[{index}]"
        if not isinstance(repository, dict) or set(repository) != {
            "url",
            "ref",
            "revision",
        }:
            raise ConfigError(f"{location} must contain url, ref, and revision")
        url = repository["url"]
        ref = repository["ref"]
        revision = repository["revision"]
        if not isinstance(url, str) or not url.startswith("https://github.com/"):
            raise ConfigError(f"{location}: url must be an HTTPS GitHub repository")
        canonical_url = url.removesuffix("/").removesuffix(".git")
        if canonical_url in urls:
            raise ConfigError(f"{location}: duplicate url {url}")
        urls.add(canonical_url)
        name = repository_name(url)
        if not NAME_PATTERN.fullmatch(name) or name in names:
            raise ConfigError(f"{location}: repository URL produces invalid name {name}")
        names.add(name)
        if not isinstance(ref, str) or not REF_PATTERN.fullmatch(ref) or ".." in ref:
            raise ConfigError(f"{location}: invalid ref")
        if not isinstance(revision, str) or not SHA_PATTERN.fullmatch(revision):
            raise ConfigError(f"{location}: revision must be a lowercase 40-character SHA")
        repositories.append(
            {"name": name, "url": url, "ref": ref, "revision": revision}
        )
    return {"version": 1, "repositories": repositories}


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, object]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"Cannot read {path}: {error}") from error
    return validate_manifest(manifest, path)


def load_override(path: Path) -> Mapping[str, object]:
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
    if not isinstance(recipe.get("Input"), Mapping):
        raise ConfigError(f"{path}: Input must be a mapping")
    if not isinstance(recipe.get("ParentRecipe"), str):
        raise ConfigError(f"{path}: missing or invalid ParentRecipe")
    if not isinstance(recipe.get("ParentRecipeTrustInfo"), Mapping):
        raise ConfigError(f"{path}: missing or invalid ParentRecipeTrustInfo")
    return recipe


def override_paths(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.recipe.yaml")) if directory.is_dir() else []


def load_overrides(
    directory: Path = OVERRIDE_DIR,
) -> dict[str, tuple[Path, Mapping[str, object]]]:
    overrides: dict[str, tuple[Path, Mapping[str, object]]] = {}
    for path in override_paths(directory):
        recipe = load_override(path)
        identifier = recipe["Identifier"]
        if identifier in overrides:
            raise ConfigError(f"Duplicate override identifier: {identifier}")
        overrides[identifier] = (path, recipe)
    if not overrides:
        raise ConfigError(f"{directory}: no overrides found")
    return overrides


def load_selection(state_dir: Path = STATE_DIR) -> dict[str, list[str]]:
    path = state_dir / "selection.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"Cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: selection must be an object")

    recipes = value.get("recipes")
    if set(value) != {"recipes"} or not isinstance(recipes, list) or not all(
        isinstance(recipe, str) for recipe in recipes
    ):
        raise ConfigError(f"{path}: invalid recipes")
    return {"recipes": recipes}


def recipe_aliases(identifier: str) -> tuple[str, ...]:
    short_name = identifier.rsplit(".", 1)[-1]
    return (identifier,) if short_name == identifier else (identifier, short_name)


def select_recipes(requested: list[str], available: list[str]) -> list[str]:
    if not requested:
        return available

    aliases: dict[str, list[str]] = {}
    for identifier in available:
        for alias in recipe_aliases(identifier):
            aliases.setdefault(alias, []).append(identifier)

    selected: list[str] = []
    for recipe in requested:
        matches = aliases.get(recipe, [])
        if not matches:
            raise ConfigError(f"Unknown recipe: {recipe}")
        if len(matches) > 1:
            raise ConfigError(
                f"Ambiguous recipe {recipe}: use {', '.join(sorted(matches))}"
            )
        selected.append(matches[0])
    return selected


def repository_map(manifest: Mapping[str, object]) -> dict[str, dict[str, str]]:
    repositories = manifest["repositories"]
    assert isinstance(repositories, list)
    return {repository["name"]: repository for repository in repositories}
