#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from common import (
    ConfigError,
    MANIFEST_PATH,
    REPO_ROOT,
    ROOT,
    STATE_DIR,
    load_manifest,
    load_overrides,
    load_recipe_list,
    repository_map,
    trust_references,
    validate_manifest,
)


def canonical_url(value: str) -> str:
    return value.removesuffix(".git").removesuffix("/")


def git(
    path: Path, *arguments: str, capture: bool = False, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(path), *arguments],
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and result.returncode:
        detail = result.stderr.strip() if result.stderr else ""
        raise ConfigError(
            f"git -C {path} {' '.join(arguments)} failed"
            f"{': ' + detail if detail else ''}"
        )
    return result


def ensure_checkout(repository: dict[str, str], repo_root: Path) -> Path:
    destination = repo_root / repository["name"]
    if not destination.exists():
        repo_root.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                repository["url"],
                str(destination),
            ],
            check=False,
        )
        if completed.returncode:
            raise ConfigError(f"Could not clone {repository['url']}")
    if not destination.is_dir():
        raise ConfigError(f"{destination}: expected a Git repository directory")
    git(destination, "rev-parse", "--git-dir", capture=True)

    origin = git(destination, "remote", "get-url", "origin", capture=True).stdout.strip()
    if canonical_url(origin) != canonical_url(repository["url"]):
        raise ConfigError(f"{destination}: origin is {origin}, expected {repository['url']}")
    if git(destination, "status", "--porcelain", capture=True).stdout.strip():
        raise ConfigError(f"{destination}: refusing to change a dirty checkout")

    revision = repository["revision"]
    head = git(destination, "rev-parse", "HEAD", capture=True, check=False)
    if head.returncode == 0 and head.stdout.strip() == revision:
        print(f"{repository['name']}: {revision[:12]} ready")
        return destination

    commit = git(destination, "cat-file", "-e", f"{revision}^{{commit}}", check=False)
    remote_ref = f"refs/remotes/origin/{repository['ref']}"
    ancestor = git(
        destination,
        "merge-base",
        "--is-ancestor",
        revision,
        remote_ref,
        check=False,
    )
    if commit.returncode or ancestor.returncode:
        git(
            destination,
            "fetch",
            "--no-tags",
            "origin",
            f"+refs/heads/{repository['ref']}:{remote_ref}",
        )
        git(destination, "cat-file", "-e", f"{revision}^{{commit}}")
        if git(
            destination,
            "merge-base",
            "--is-ancestor",
            revision,
            remote_ref,
            check=False,
        ).returncode:
            raise ConfigError(
                f"{repository['name']}: {revision} is not on origin/{repository['ref']}"
            )
    git(destination, "checkout", "--detach", revision)
    print(f"{repository['name']}: checked out {revision[:12]}")
    return destination


def selected_names(names_file: Path | None, manifest: dict[str, Any]) -> list[str]:
    if names_file is None:
        return [repository["name"] for repository in manifest["repositories"]]
    try:
        names = [line.strip() for line in names_file.read_text(encoding="utf-8").splitlines()]
    except OSError as error:
        raise ConfigError(f"Cannot read {names_file}: {error}") from error
    names = [name for name in names if name]
    known = repository_map(manifest)
    unknown = sorted(set(names) - known.keys())
    if unknown:
        raise ConfigError(f"Unknown repositories: {', '.join(unknown)}")
    return names


def sync(names: list[str], manifest: dict[str, Any], repo_root: Path) -> None:
    repositories = repository_map(manifest)
    for name in names:
        ensure_checkout(repositories[name], repo_root)


def old_manifest(base: str) -> dict[str, Any] | None:
    result = subprocess.run(
        ["git", "show", f"{base}:repositories.json"],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ConfigError(f"{base}:repositories.json: {error}") from error
    return validate_manifest(value, f"{base}:repositories.json")


def compare_url(repository: dict[str, str], old: str, new: str) -> str:
    return f"{canonical_url(repository['url'])}/compare/{old}...{new}"


def changed_repositories(
    current: dict[str, Any], previous: dict[str, Any] | None, repo_root: Path
) -> dict[str, Any]:
    if previous is None:
        return {"baseline": False, "changes": []}
    old_by_name = repository_map(previous)
    current_by_name = repository_map(current)
    production = load_recipe_list()
    references = trust_references(
        production, load_overrides(), current["repositories"]
    )

    changes: list[dict[str, Any]] = []
    changed_names = [
        name
        for name, repository in current_by_name.items()
        if name in old_by_name
        and repository["revision"] != old_by_name[name]["revision"]
    ]
    sync(changed_names, current, repo_root)
    for name in changed_names:
        repository = current_by_name[name]
        old_revision = old_by_name[name]["revision"]
        new_revision = repository["revision"]
        destination = repo_root / name
        if git(
            destination, "cat-file", "-e", f"{old_revision}^{{commit}}", check=False
        ).returncode:
            git(destination, "fetch", "--no-tags", "origin", old_revision)
        paths = git(
            destination,
            "diff",
            "--name-only",
            old_revision,
            new_revision,
            capture=True,
        ).stdout.splitlines()
        relevant = sorted(set(paths) & references.get(name, set()))
        changes.append(
            {
                "name": name,
                "ref": repository["ref"],
                "old_revision": old_revision,
                "new_revision": new_revision,
                "compare_url": compare_url(repository, old_revision, new_revision),
                "changed_paths": paths,
                "changed_recipe_paths": [path for path in paths if ".recipe" in path],
                "changed_python_paths": [path for path in paths if path.endswith(".py")],
                "relevant_paths": relevant,
            }
        )
    return {"baseline": True, "changes": changes}


def markdown(report: dict[str, Any]) -> str:
    lines = ["## AutoPkg upstream changes", ""]
    if not report["baseline"]:
        lines.append("No previous repository manifest is available.")
    elif not report["changes"]:
        lines.append("No pinned repository revisions changed.")
    else:
        for change in report["changes"]:
            lines.extend(
                [
                    f"### [{change['name']}]({change['compare_url']})",
                    "",
                    f"`{change['old_revision'][:12]}` to `{change['new_revision'][:12]}` on `{change['ref']}`",
                    "",
                    f"{len(change['changed_paths'])} files changed; "
                    f"{len(change['changed_recipe_paths'])} recipes and "
                    f"{len(change['changed_python_paths'])} Python files.",
                    "",
                ]
            )
            if change["relevant_paths"]:
                lines.append("Changed files owned by enabled recipe chains:")
                lines.append("")
                lines.extend(f"- `{path}`" for path in change["relevant_paths"])
            else:
                lines.append("No changed file is owned by an enabled recipe chain.")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def append_github_summary(value: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as output:
            output.write(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize pinned AutoPkg repositories")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--names-file", type=Path, default=STATE_DIR / "repositories.txt")
    sync_parser.add_argument("--all", action="store_true")
    diff_parser = subparsers.add_parser("diff")
    diff_parser.add_argument("--base", default=os.environ.get("AUTOPKG_DIFF_BASE", "origin/main"))
    diff_parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts")
    arguments = parser.parse_args()

    try:
        manifest = load_manifest(arguments.manifest)
        if arguments.command == "sync":
            names_file = None if arguments.all else arguments.names_file
            sync(selected_names(names_file, manifest), manifest, arguments.repo_root)
        else:
            report = changed_repositories(
                manifest, old_manifest(arguments.base), arguments.repo_root
            )
            value = markdown(report)
            arguments.output_dir.mkdir(parents=True, exist_ok=True)
            (arguments.output_dir / "upstream-changes.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            (arguments.output_dir / "upstream-changes.md").write_text(
                value, encoding="utf-8"
            )
            print(value, end="")
            append_github_summary(value)
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
