#!/usr/bin/env python3
"""Emit a JSON inventory of this repository.

Counts source files, Terraform resources, dependencies, tests and (if a
coverage.json is present) actual coverage. Everything reported here is measured,
not asserted — if coverage has not been run, the field is null rather than a
guess.

Usage:
    python scripts/inventory_report.py [--output inventory.json]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent

TF_RESOURCE_RE = re.compile(r'^resource\s+"([^"]+)"\s+"([^"]+)"', re.MULTILINE)
TF_DATA_RE = re.compile(r'^data\s+"([^"]+)"\s+"([^"]+)"', re.MULTILINE)
TF_VAR_RE = re.compile(r'^variable\s+"([^"]+)"', re.MULTILINE)
TF_OUTPUT_RE = re.compile(r'^output\s+"([^"]+)"', re.MULTILINE)
PY_TEST_RE = re.compile(r"^def\s+(test_\w+)", re.MULTILINE)
PY_FUNC_RE = re.compile(r"^\s*def\s+(\w+)", re.MULTILINE)
FINDING_ID_RE = re.compile(r"\bCMP-(COST|SEC|CODE|DEP|TEST|CFG)-(\d{3})\b")


def python_files() -> list[pathlib.Path]:
    return sorted(
        p
        for p in ROOT.rglob("*.py")
        if ".venv" not in p.parts and "build" not in p.parts and "__pycache__" not in p.parts
    )


def terraform_files() -> list[pathlib.Path]:
    return sorted((ROOT / "terraform").rglob("*.tf"))


def summarise_python() -> dict:
    files = python_files()
    total_lines = 0
    total_funcs = 0
    per_file = []

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.count("\n") + 1
        funcs = len(PY_FUNC_RE.findall(text))
        total_lines += lines
        total_funcs += funcs
        per_file.append(
            {
                "path": str(path.relative_to(ROOT)),
                "lines": lines,
                "functions": funcs,
            }
        )

    return {
        "file_count": len(files),
        "total_lines": total_lines,
        "total_functions": total_funcs,
        "files": per_file,
    }


def summarise_terraform() -> dict:
    files = terraform_files()
    resources: list[dict] = []
    data_sources: list[dict] = []
    variables: list[str] = []
    outputs: list[str] = []
    by_type: dict[str, int] = {}

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = str(path.relative_to(ROOT))

        for rtype, rname in TF_RESOURCE_RE.findall(text):
            resources.append({"type": rtype, "name": rname, "file": rel})
            by_type[rtype] = by_type.get(rtype, 0) + 1

        for dtype, dname in TF_DATA_RE.findall(text):
            data_sources.append({"type": dtype, "name": dname, "file": rel})

        variables.extend(TF_VAR_RE.findall(text))
        outputs.extend(TF_OUTPUT_RE.findall(text))

    return {
        "file_count": len(files),
        "resource_count": len(resources),
        "data_source_count": len(data_sources),
        "variable_count": len(variables),
        "output_count": len(outputs),
        "resources_by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "resources": resources,
        "variables": sorted(variables),
        "outputs": sorted(outputs),
    }


def summarise_dependencies() -> dict:
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.exists():
        return {"runtime": [], "dev": []}

    text = pyproject.read_text(encoding="utf-8")

    def block(header: str) -> list[str]:
        match = re.search(rf"{re.escape(header)}\s*=\s*\[(.*?)\]", text, re.DOTALL)
        if not match:
            return []
        return re.findall(r'"([^"]+)"', match.group(1))

    return {
        "runtime": block("dependencies"),
        "dev": block("dev"),
    }


def summarise_tests() -> dict:
    unit = sorted((ROOT / "unit-tests").rglob("test_*.py"))
    functional = sorted((ROOT / "functional-tests").rglob("test_*.py"))

    def count(paths: list[pathlib.Path]) -> int:
        return sum(len(PY_TEST_RE.findall(p.read_text(encoding="utf-8"))) for p in paths)

    return {
        "unit_files": len(unit),
        "unit_tests": count(unit),
        "functional_files": len(functional),
        "functional_tests": count(functional),
        "total_tests": count(unit) + count(functional),
    }


def summarise_coverage() -> dict | None:
    """Read coverage.json if it exists. Returns None otherwise — never a guess."""
    path = ROOT / "coverage.json"
    if not path.exists():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    totals = data.get("totals", {})
    return {
        "percent_covered": round(totals.get("percent_covered", 0.0), 2),
        "covered_lines": totals.get("covered_lines"),
        "num_statements": totals.get("num_statements"),
        "missing_lines": totals.get("missing_lines"),
        "source": "coverage.json",
    }


def summarise_seeded_findings() -> dict:
    """Count the stable finding IDs actually present in the tree."""
    found: dict[str, set[str]] = {}

    for path in list(python_files()) + terraform_files() + list(ROOT.rglob("*.md")):
        if ".venv" in path.parts or ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for category, number in FINDING_ID_RE.findall(text):
            found.setdefault(category, set()).add(f"CMP-{category}-{number}")

    return {
        "by_category": {k: len(v) for k, v in sorted(found.items())},
        "total_unique_ids": sum(len(v) for v in found.values()),
        "ids": {k: sorted(v) for k, v in sorted(found.items())},
    }


def build_inventory() -> dict:
    return {
        "repository": "cloud-media-pipeline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Deliberately vulnerable benchmark repository. Measured values only.",
        "python": summarise_python(),
        "terraform": summarise_terraform(),
        "dependencies": summarise_dependencies(),
        "tests": summarise_tests(),
        "coverage": summarise_coverage(),
        "seeded_findings": summarise_seeded_findings(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="write JSON here instead of stdout")
    parser.add_argument("--summary", action="store_true", help="print a short human summary")
    args = parser.parse_args()

    inventory = build_inventory()

    if args.summary:
        tf = inventory["terraform"]
        py = inventory["python"]
        tests = inventory["tests"]
        cov = inventory["coverage"]
        print(f"python files        : {py['file_count']} ({py['total_lines']} lines)")
        print(f"terraform resources : {tf['resource_count']} across {tf['file_count']} files")
        print(f"tests               : {tests['total_tests']}")
        print(f"coverage            : {cov['percent_covered'] if cov else 'not measured'}")
        print(f"seeded finding ids  : {inventory['seeded_findings']['total_unique_ids']}")
        return 0

    payload = json.dumps(inventory, indent=2)

    if args.output:
        pathlib.Path(args.output).write_text(payload, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(payload)

    return 0


if __name__ == "__main__":
    sys.exit(main())

