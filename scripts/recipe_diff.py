#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def read_recipes(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_processors(path: Path) -> dict[str, list[dict[str, str]]]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected an array")
    processors: dict[str, list[dict[str, str]]] = defaultdict(list)
    required = {"recipe", "processor", "path", "url"}
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != required
            or not all(isinstance(item[key], str) for key in required)
        ):
            raise ValueError(f"{path}: invalid changed processor entry")
        processors[item["recipe"]].append(item)
    return processors


def read_file_changes(
    path: Path, description: str
) -> dict[str, list[dict[str, str]]]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected an array")
    changes: dict[str, list[dict[str, str]]] = defaultdict(list)
    required = {"recipe", "path", "url"}
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != required
            or not all(isinstance(item[key], str) for key in required)
        ):
            raise ValueError(f"{path}: invalid changed {description} entry")
        changes[item["recipe"]].append(item)
    return changes


def read_added(path: Path) -> dict[str, str]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(
        isinstance(identifier, str) and isinstance(parent, str)
        for identifier, parent in value.items()
    ):
        raise ValueError(f"{path}: invalid added recipes")
    return value


def read_removed(path: Path) -> list[str]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{path}: invalid removed recipes")
    return value


def recipe_section(
    identifier: str,
    base: str,
    head: str,
    recipe_files: list[dict[str, str]],
    processors: list[dict[str, str]],
    resources: list[dict[str, str]],
    membership: str | None,
) -> str | None:
    patch = "".join(
        difflib.unified_diff(
            base.splitlines(keepends=True),
            head.splitlines(keepends=True),
            fromfile=f"{identifier} (base)",
            tofile=f"{identifier} (pull request)",
            n=6,
        )
    )
    if (
        not patch
        and not recipe_files
        and not processors
        and not resources
        and membership is None
    ):
        return None

    label = f" ({membership})" if membership else ""
    lines = [f"### `{identifier}`{label}", ""]
    if patch:
        lines.extend(["```diff", patch.rstrip(), "```"])
    linked_files = bool((not patch and recipe_files) or processors or resources)
    if linked_files:
        if patch:
            lines.append("")
        lines.extend(["Changed upstream files:", ""])
        if not patch:
            for recipe_file in recipe_files:
                lines.append(
                    f"- Recipe [`{recipe_file['path']}`]({recipe_file['url']})"
                )
        for processor in processors:
            lines.append(
                f"- Processor [`{processor['processor']}`]({processor['url']}) "
                f"(`{processor['path']}`)"
            )
        for resource in resources:
            lines.append(
                f"- Imported resource [`{resource['path']}`]({resource['url']})"
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff resolved AutoPkg recipe chains")
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--head-dir", type=Path, required=True)
    parser.add_argument("--recipes", type=Path, required=True)
    parser.add_argument("--recipe-files", type=Path, required=True)
    parser.add_argument("--processors", type=Path, required=True)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--added", type=Path, required=True)
    parser.add_argument("--removed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit-bytes", type=int, default=50_000)
    arguments = parser.parse_args()

    processors = read_processors(arguments.processors)
    recipe_files = read_file_changes(arguments.recipe_files, "recipe file")
    resources = read_file_changes(arguments.resources, "resource")
    added = read_added(arguments.added)
    removed = read_removed(arguments.removed)
    recipes = read_recipes(arguments.recipes)
    recipe_set = set(recipes)
    related = (
        set(recipe_files) | set(processors) | set(resources) | set(added) | set(removed)
    )
    if unknown := sorted(related - recipe_set):
        raise ValueError(
            "change metadata references recipes outside the affected set: "
            + ", ".join(unknown)
        )
    if overlap := sorted(set(added) & set(removed)):
        raise ValueError("recipes cannot be both added and removed: " + ", ".join(overlap))

    sections: list[str] = []
    for identifier in recipes:
        base_path = arguments.base_dir / f"{identifier}.yaml"
        head_path = arguments.head_dir / f"{identifier}.yaml"
        base = base_path.read_text(encoding="utf-8") if base_path.exists() else ""
        head = head_path.read_text(encoding="utf-8") if head_path.exists() else ""
        membership = (
            "new" if identifier in added else "removed" if identifier in removed else None
        )
        section = recipe_section(
            identifier,
            base,
            head,
            recipe_files.get(identifier, []),
            processors.get(identifier, []),
            resources.get(identifier, []),
            membership,
        )
        if section:
            sections.append(section)

    content = (
        "\n\n".join(sections) + "\n"
        if sections
        else "_No review-required recipe changes._\n"
    )
    if len(content.encode("utf-8")) > arguments.limit_bytes:
        kept: list[str] = []
        suffix = "\n\n_Additional recipe changes omitted at the comment size limit._\n"
        for section in sections:
            candidate = "\n\n".join([*kept, section]) + suffix
            if len(candidate.encode("utf-8")) > arguments.limit_bytes:
                break
            kept.append(section)
        content = "\n\n".join(kept) + suffix
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(content, encoding="utf-8")
    print(f"Wrote {len(content.encode('utf-8'))} bytes to {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
