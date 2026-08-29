#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def clear_input(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(
            index
            for index, line in enumerate(lines)
            if line == "Input:" or line.startswith("Input: ")
        )
    except StopIteration as error:
        raise SystemExit(f"{path}: missing Input") from error

    end = start + 1
    while end < len(lines) and (not lines[end] or lines[end][0].isspace()):
        end += 1
    path.write_text(
        "\n".join([*lines[:start], "Input: {}", *lines[end:]]) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} OVERRIDE")
    clear_input(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
