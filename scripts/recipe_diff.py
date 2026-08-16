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


def read_resources(path: Path) -> dict[str, list[dict[str, str]]]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected an array")
    resources: dict[str, list[dict[str, str]]] = defaultdict(list)
    required = {"recipe", "path", "url"}
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != required
            or not all(isinstance(item[key], str) for key in required)
        ):
            raise ValueError(f"{path}: invalid changed resource entry")
        resources[item["recipe"]].append(item)
    return resources


def recipe_section(
    identifier: str,
    base: str,
    head: str,
    processors: list[dict[str, str]],
    resources: list[dict[str, str]],
) -> str:
    patch = "".join(
        difflib.unified_diff(
            base.splitlines(keepends=True),
            head.splitlines(keepends=True),
            fromfile=f"{identifier} (base)",
            tofile=f"{identifier} (pull request)",
            n=6,
        )
    )
    lines = [f"### `{identifier}`", ""]
    if patch:
        lines.extend(["```diff", patch.rstrip(), "```"])
    else:
        lines.append("_No effective recipe chain changes._")
    if processors:
        lines.extend(["", "Changed processors:", ""])
        for processor in processors:
            lines.append(
                f"- [`{processor['processor']}`]({processor['url']}) "
                f"(`{processor['path']}`)"
            )
    if resources:
        lines.extend(["", "Changed recipe resources:", ""])
        for resource in resources:
            lines.append(f"- [`{resource['path']}`]({resource['url']})")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff resolved AutoPkg recipe chains")
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--head-dir", type=Path, required=True)
    parser.add_argument("--recipes", type=Path, required=True)
    parser.add_argument("--processors", type=Path, required=True)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit-bytes", type=int, default=50_000)
    arguments = parser.parse_args()

    processors = read_processors(arguments.processors)
    resources = read_resources(arguments.resources)
    sections: list[str] = []
    for identifier in read_recipes(arguments.recipes):
        base = (arguments.base_dir / f"{identifier}.yaml").read_text(
            encoding="utf-8"
        )
        head = (arguments.head_dir / f"{identifier}.yaml").read_text(
            encoding="utf-8"
        )
        sections.append(
            recipe_section(
                identifier,
                base,
                head,
                processors.get(identifier, []),
                resources.get(identifier, []),
            )
        )

    content = "\n\n".join(sections) + "\n"
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
