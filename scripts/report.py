#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
from pathlib import Path
from typing import Any

from common import ROOT, STATE_DIR, load_manifest, repository_map


SECRET_KEY = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|private|secret|token)",
    re.IGNORECASE,
)


def scrub(value: object, secrets: list[str]) -> object:
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if SECRET_KEY.search(str(key)) else scrub(child, secrets)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [scrub(child, secrets) for child in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = plistlib.loads(path.read_bytes())
    except (OSError, plistlib.InvalidFileException):
        return {}
    return value if isinstance(value, dict) else {}


def cell(value: object) -> str:
    text = str(value).replace("|", "\\|").replace("\n", "<br>")
    if text == "True":
        return "Yes"
    if text == "False":
        return "No"
    return text


def label(value: str) -> str:
    return value.replace("_", " ").strip().title()


def summary_tables(summary_results: object) -> tuple[list[str], int]:
    if not isinstance(summary_results, dict):
        return [], 0
    lines: list[str] = []
    row_count = 0
    for result in summary_results.values():
        if not isinstance(result, dict):
            continue
        rows = result.get("data_rows")
        if not isinstance(rows, list) or not rows:
            continue
        header = result.get("header")
        if not isinstance(header, list) or not all(isinstance(item, str) for item in header):
            first = rows[0]
            header = list(first) if isinstance(first, dict) else []
        title = result.get("summary_text") or "Processor changes"
        lines.extend([f"### {cell(title)}", ""])
        lines.append("| " + " | ".join(label(item) for item in header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in rows:
            if not isinstance(row, dict):
                continue
            lines.append("| " + " | ".join(cell(row.get(item, "")) for item in header) + " |")
            row_count += 1
        lines.append("")
    return lines, row_count


def failure_lines(failures: object) -> list[str]:
    if not isinstance(failures, list) or not failures:
        return []
    lines = ["### Failures", ""]
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        recipe = cell(failure.get("recipe", "Unknown recipe"))
        message = cell(failure.get("message", "No failure detail was reported."))
        lines.extend([f"- **{recipe}:** {message}"])
    lines.append("")
    return lines


def render(result: dict[str, Any]) -> str:
    succeeded = result["exit_code"] == 0 and not result["failures"]
    icon = "✅" if succeeded else "❌"
    status = "Succeeded" if succeeded else "Failed"
    tables, change_count = summary_tables(result["summary_results"])
    lines = [
        f"## AutoPkg run {icon}",
        "",
        "| Result | Recipes | Changes | Repositories |",
        "| --- | ---: | ---: | ---: |",
        f"| {status} | {len(result['recipes'])} | {change_count} | {len(result['repositories'])} |",
        "",
    ]
    lines.extend(failure_lines(result["failures"]))
    if tables:
        lines.extend(tables)
    elif succeeded:
        lines.extend(["Nothing changed.", ""])
    lines.extend(
        [
            "<details>",
            "<summary>Selected recipes</summary>",
            "",
            *(f"- `{recipe}`" for recipe in result["recipes"]),
            "",
            "</details>",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a sanitized AutoPkg v3 report")
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--exit-code", type=int, default=int(os.environ.get("AUTOPKG_EXIT_CODE", "1")))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts")
    arguments = parser.parse_args()

    selection = load_json(arguments.state_dir / "selection.json")
    raw_report = load_report(arguments.state_dir / "autopkg-results.plist")
    secrets = [
        value
        for key, value in os.environ.items()
        if value and SECRET_KEY.search(key) and len(value) >= 6
    ]
    report = scrub(raw_report, secrets)
    manifest = load_manifest()
    repositories = repository_map(manifest)
    selected_repositories = selection.get("repositories", [])
    result = {
        "exit_code": arguments.exit_code,
        "recipes": selection.get("recipes", []),
        "repositories": {
            name: repositories[name]["revision"]
            for name in selected_repositories
            if name in repositories
        },
        "failures": report.get("failures", []) if isinstance(report, dict) else [],
        "summary_results": (
            report.get("summary_results", {}) if isinstance(report, dict) else {}
        ),
    }
    markdown = render(result)
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    (arguments.output_dir / "autopkg-summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (arguments.output_dir / "autopkg-summary.md").write_text(markdown, encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as output:
            output.write(markdown)
    print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
