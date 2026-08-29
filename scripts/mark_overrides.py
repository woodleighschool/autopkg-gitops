#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    ConfigError,
    OVERRIDE_DIR,
    expected_override_header,
    load_override,
    override_paths,
)


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
            f"{path}: expected Identifier after the trust refresh comment"
        )
    return "\n".join([*header, *body]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize override headers")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("paths", nargs="*", type=Path)
    arguments = parser.parse_args()

    paths = arguments.paths or override_paths(OVERRIDE_DIR)
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
        print(f"{len(changed)} overrides need the trust refresh comment")
        return 1
    print(f"Updated {len(changed)} of {len(paths)} override headers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
