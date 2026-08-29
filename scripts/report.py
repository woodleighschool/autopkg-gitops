#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import plistlib
import re
from pathlib import Path
from typing import Any

from common import ROOT, STATE_DIR, load_manifest, load_selection, repository_map


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


def secret_values() -> list[str]:
    encrypted_keys = {
        key.strip()
        for key in os.environ.get("SOPS_AUTOPKG_KEYS", "").split(",")
        if key.strip()
    }
    values = {
        value
        for key, value in os.environ.items()
        if value
        and (
            key in encrypted_keys
            or (SECRET_KEY.search(key) and len(value) >= 6)
        )
    }
    return sorted(values, key=len, reverse=True)


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


def write_report(
    *,
    state_dir: Path = STATE_DIR,
    exit_code: int,
    output_dir: Path = ROOT / "artifacts",
) -> None:
    selection = load_selection(state_dir)
    raw_report = load_report(state_dir / "autopkg-results.plist")
    report = scrub(raw_report, secret_values())
    manifest = load_manifest()
    repositories = repository_map(manifest)
    result = {
        "exit_code": exit_code,
        "recipes": selection["recipes"],
        "repositories": {
            name: repository["revision"] for name, repository in repositories.items()
        },
        "failures": report.get("failures", []) if isinstance(report, dict) else [],
        "summary_results": (
            report.get("summary_results", {}) if isinstance(report, dict) else {}
        ),
    }
    markdown = render(result)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "autopkg-summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "autopkg-summary.md").write_text(markdown, encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as output:
            output.write(markdown)
    print(markdown, end="")
