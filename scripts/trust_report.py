#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from common import ConfigError, load_manifest


def trust_failures(output: str) -> list[str]:
    failures: list[str] = []
    for line in output.splitlines():
        recipe, separator, status = line.rpartition(": ")
        if separator and status == "FAILED" and recipe:
            failures.append(recipe)
    return failures


def canonical_url(url: str) -> str:
    return url.removesuffix("/").removesuffix(".git")


def changed_repositories(
    base_manifest: dict[str, object], head_manifest: dict[str, object]
) -> list[str]:
    base_values = base_manifest["repositories"]
    head_values = head_manifest["repositories"]
    assert isinstance(base_values, list)
    assert isinstance(head_values, list)
    base = {canonical_url(repository["url"]): repository for repository in base_values}
    head = {canonical_url(repository["url"]): repository for repository in head_values}

    lines: list[str] = []
    for url in sorted(base.keys() | head.keys()):
        old = base.get(url)
        new = head.get(url)
        label = url.removeprefix("https://github.com/")
        if old is None:
            assert new is not None
            lines.append(
                f"- [{label}@{new['revision'][:12]}]({url}/commit/{new['revision']}) added"
            )
        elif new is None:
            lines.append(f"- {label}@{old['revision'][:12]} removed")
        elif old["revision"] != new["revision"]:
            lines.append(
                f"- [{label}: {old['revision'][:12]}...{new['revision'][:12]}]"
                f"({url}/compare/{old['revision']}...{new['revision']})"
            )
    return lines


def render(
    *,
    base_manifest_path: Path,
    head_manifest_path: Path,
    verification_path: Path,
) -> str:
    base_manifest = load_manifest(base_manifest_path)
    head_manifest = load_manifest(head_manifest_path)
    verification = verification_path.read_text(encoding="utf-8").strip()
    failures = trust_failures(verification)
    repositories = changed_repositories(base_manifest, head_manifest)

    lines = ["## Trust review", ""]
    if repositories:
        lines.extend(["### Repository changes", "", *repositories, ""])
    else:
        lines.extend(["No repository revisions changed.", ""])

    if failures:
        lines.extend(
            [
                "Source changes affect:",
                "",
                *(f"- `{recipe}`" for recipe in failures),
                "",
                "Trust info was refreshed and verified.",
                "",
            ]
        )
    else:
        lines.extend(["All overrides still match their parents.", ""])

    if len(verification) > 55_000:
        verification = verification[:55_000] + "\n... output truncated ..."
    lines.extend(
        [
            "<details>",
            "<summary>verify-trust-info -vv</summary>",
            "",
            "```text",
            verification or "No verification output.",
            "```",
            "",
            "</details>",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report trust changes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    failures = subparsers.add_parser("failures")
    failures.add_argument("verification", type=Path)
    report = subparsers.add_parser("render")
    report.add_argument("--base-manifest", type=Path, required=True)
    report.add_argument("--head-manifest", type=Path, required=True)
    report.add_argument("--verification", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    try:
        if arguments.command == "failures":
            output = arguments.verification.read_text(encoding="utf-8")
            for recipe in trust_failures(output):
                print(recipe)
        else:
            text = render(
                base_manifest_path=arguments.base_manifest,
                head_manifest_path=arguments.head_manifest,
                verification_path=arguments.verification,
            )
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(text, encoding="utf-8")
    except (ConfigError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
