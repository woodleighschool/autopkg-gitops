#!/usr/bin/env python3
from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

from common import ConfigError, ROOT, STATE_DIR, load_overrides, load_selection
from report import write_report


AUTOPKG_CACHE_DIR = Path.home() / "Library/AutoPkg/Cache"
RAW_REPORT_NAME = "autopkg-results.plist"


class CleanupError(RuntimeError):
    pass


def remove(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    try:
        if stat.S_ISDIR(mode):
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as error:
        raise CleanupError(
            f"Cannot remove sensitive AutoPkg state at {path}: {error}"
        ) from error


def reject_link(path: Path) -> None:
    if path.is_symlink():
        raise CleanupError(f"Refusing to clean through symbolic link: {path}")


class SensitiveState:
    def __init__(
        self,
        *,
        state_dir: Path,
        cache_dir: Path,
        recipe_identifiers: set[str],
    ) -> None:
        self.state_dir = state_dir
        self.cache_dir = cache_dir
        self.recipe_identifiers = recipe_identifiers

    def clean(self) -> None:
        reject_link(self.state_dir)
        reject_link(self.cache_dir)
        remove(self.state_dir / RAW_REPORT_NAME)
        remove(self.cache_dir / "autopkg_results.plist")

        for identifier in sorted(self.recipe_identifiers):
            recipe_cache = self.cache_dir / identifier
            reject_link(recipe_cache)
            remove(recipe_cache / "receipts")


def run(
    *,
    state_dir: Path = STATE_DIR,
    cache_dir: Path = AUTOPKG_CACHE_DIR,
    output_dir: Path = ROOT / "artifacts",
) -> int:
    selection = load_selection(state_dir)
    recipes = selection["recipes"]
    if not recipes:
        raise ConfigError(f"{state_dir / 'selection.json'}: no recipes selected")

    selected_recipes_path = state_dir / "selected-recipes.txt"
    selected_recipes_path.write_text(
        "".join(f"{recipe}\n" for recipe in recipes), encoding="utf-8"
    )
    sensitive_state = SensitiveState(
        state_dir=state_dir,
        cache_dir=cache_dir,
        recipe_identifiers=set(load_overrides()),
    )
    sensitive_state.clean()

    try:
        completed = subprocess.run(
            [
                "autopkg",
                "run",
                "--quiet",
                f"--prefs={state_dir / 'preferences.plist'}",
                f"--recipe-list={selected_recipes_path}",
                f"--report-plist={state_dir / RAW_REPORT_NAME}",
            ],
            check=False,
        )
        write_report(
            state_dir=state_dir,
            exit_code=completed.returncode,
            output_dir=output_dir,
        )
        return completed.returncode
    finally:
        sensitive_state.clean()


if __name__ == "__main__":
    raise SystemExit(run())
