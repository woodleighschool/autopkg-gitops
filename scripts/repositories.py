#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from common import (
    ConfigError,
    MANIFEST_PATH,
    REPO_ROOT,
    load_manifest,
)


def canonical_url(value: str) -> str:
    return value.removesuffix("/").removesuffix(".git")


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
    created = False
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
        created = True
    if not destination.is_dir():
        raise ConfigError(f"{destination}: expected a Git repository directory")
    git(destination, "rev-parse", "--git-dir", capture=True)

    origin = git(destination, "remote", "get-url", "origin", capture=True).stdout.strip()
    if canonical_url(origin) != canonical_url(repository["url"]):
        raise ConfigError(f"{destination}: origin is {origin}, expected {repository['url']}")
    if not created and git(
        destination, "status", "--porcelain", capture=True
    ).stdout.strip():
        raise ConfigError(f"{destination}: refusing to change a dirty checkout")

    revision = repository["revision"]
    head = git(destination, "rev-parse", "HEAD", capture=True, check=False)
    if not created and head.returncode == 0 and head.stdout.strip() == revision:
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


def sync(manifest: dict[str, object], repo_root: Path) -> None:
    repositories = manifest["repositories"]
    assert isinstance(repositories, list)
    for repository in repositories:
        ensure_checkout(repository, repo_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync repositories")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    arguments = parser.parse_args()

    try:
        manifest = load_manifest(arguments.manifest)
        sync(manifest, arguments.repo_root)
    except ConfigError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
