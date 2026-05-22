#!/usr/bin/env python3
"""
Generate THIRD_PARTY_LICENSES.md from pip-licenses output.
Matches the pcn format: license-grouped, comma-separated package names.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# License name normalization: pip-licenses output -> SPDX / pcn-style
LICENSE_NORMALIZE: dict[str, str] = {
    "MIT License": "MIT",
    "MIT": "MIT",
    "Apache License 2.0": "Apache-2.0",
    "Apache-2.0": "Apache-2.0",
    "Apache Software License": "Apache-2.0",
    "BSD License": "BSD-2-Clause",
    "BSD-2-Clause": "BSD-2-Clause",
    "BSD 2-Clause": "BSD-2-Clause",
    "BSD 3-Clause": "BSD-3-Clause",
    "BSD-3-Clause": "BSD-3-Clause",
    "ISC License": "ISC",
    "ISC License (ISCL)": "ISC",
    "ISC": "ISC",
    "Python Software Foundation License": "PSF",
    "PSF": "PSF",
}


def normalize_license(raw: str) -> str:
    """Normalize license string to SPDX-style."""
    stripped = raw.strip()
    if not stripped:
        return "Unknown"
    # Full MIT license text sometimes appears as License field
    if "Permission is hereby granted" in stripped and (
        "MIT License" in stripped or "The MIT License" in stripped
    ):
        return "MIT"
    return LICENSE_NORMALIZE.get(stripped, stripped)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    out_path = repo_root / "THIRD_PARTY_LICENSES.md"

    result = subprocess.run(
        [
            "pip-licenses",
            "--format=json",
            "--order=license",
            "--from=mixed",
        ],
        check=False, capture_output=True,
        text=True,
        cwd=repo_root,
    )

    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return 1

    try:
        packages = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"Failed to parse pip-licenses output: {e}", file=sys.stderr)
        return 1

    # Group by normalized license (exclude the project itself)
    by_license: dict[str, list[str]] = {}
    for pkg in packages:
        name = pkg.get("Name", "")
        if name == "data360-mcp":
            continue
        license_raw = pkg.get("License", "Unknown")
        license_norm = normalize_license(license_raw) if license_raw else "Unknown"
        if license_norm not in by_license:
            by_license[license_norm] = []
        by_license[license_norm].append(name)

    # Sort packages within each license
    for key in by_license:
        by_license[key] = sorted(by_license[key])

    # Build markdown
    lines = [
        "# Third-party dependencies and open source licenses",
        "",
        "Generated from `pip-licenses`. Format: **Package name**, **License**.",
        "",
        "---",
        "",
    ]

    # Sort licenses: Unknown last, others alphabetically
    license_keys = sorted(by_license.keys(), key=lambda k: (k == "Unknown", k))

    for license_key in license_keys:
        pkgs = by_license[license_key]
        lines.append(f"## {license_key}")
        lines.append("")
        lines.append(", ".join(pkgs))
        lines.append("")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "Build uses **setuptools** (MIT), **setuptools-scm** (MIT). "
            "Optional dev uses **pip-licenses** (MIT).",
            "",
            "To regenerate this list: `uv run poe licenses`",
        ]
    )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
