#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from common import ConfigError, OVERRIDE_DIR, expected_override_header, load_override


def expected_text(path: Path) -> str:
    original = path.read_text(encoding="utf-8")
    try:
        recipe = load_override(path)
    except ConfigError as error:
        raise SystemExit(str(error)) from error
    identifier = recipe["Identifier"]

    lines = original.splitlines()
    header = expected_override_header(identifier)
    body = lines[len(header) :] if lines[: len(header)] == header else lines
    if not body or body[0] != f"Identifier: {identifier}":
        raise SystemExit(
            f"{path}: expected raw AutoPkg output or the exact generated-file header"
        )
    return "\n".join([*header, *body]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Mark generated AutoPkg overrides")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("paths", nargs="*", type=Path)
    arguments = parser.parse_args()

    paths = arguments.paths or sorted(OVERRIDE_DIR.glob("*.munki.recipe.yaml"))
    changed: list[Path] = []
    for path in paths:
        expected = expected_text(path)
        if path.read_text(encoding="utf-8") == expected:
            continue
        changed.append(path)
        if not arguments.check:
            path.write_text(expected, encoding="utf-8")

    if arguments.check and changed:
        for path in changed:
            print(path)
        print(f"{len(changed)} generated overrides need headers")
        return 1
    print(f"Marked {len(changed)} of {len(paths)} generated overrides")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
