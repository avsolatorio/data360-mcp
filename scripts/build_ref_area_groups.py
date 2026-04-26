"""Transform FMR hierarchy + codelist into a compact lookup for runtime use.

Reads the official FMR SDMX files committed under examples/ and writes a
purpose-built JSON to src/data360/data/ref_area_groups.json that is shipped
as package data. The output contains all 147 group codes with their country
memberships, drawn from the H_REF_AREA_GROUPS hierarchy v38.0.

Usage:
    uv run python scripts/build_ref_area_groups.py

Re-run this script whenever:
- A new FMR hierarchy version is available (e.g. annual income reclassification)
- The examples/ source files are updated

The hierarchy is versioned (omitting version returns latest from FMR):
  https://fmr.worldbank.org/FMR/sdmx/v2/structure/hierarchy/WB/H_REF_AREA_GROUPS/
The codelist:
  https://fmr.worldbank.org/FMR/sdmx/v2/structure/codelist/WB/CL_REF_GROUPINGS/

Group types included in output (all types with country memberships):
  REGION     - WB regional classifications (SAS, SSF, EAS, ...)
  INCOME     - Income groups (LIC, HIC, LMC, UMC, ...)
  LENDING    - IDA/IBRD/blend classifications
  OTHER      - FCS, LDC, small states, OECD, EU, ...
  REGION_UN  - UN M49 statistical divisions
  CONTINENT  - Numeric continent codes

Excluded:
  WLD, _T    - Leaf-only entries (individual countries, not groups)
"""

import json
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HIERARCHY_FILE = REPO_ROOT / "examples" / "H_AREA_GROUPS38.json"
CODELIST_FILE = REPO_ROOT / "examples" / "CL_REF_GROUPINGS.json"
OUTPUT_FILE = REPO_ROOT / "src" / "data360" / "data" / "ref_area_groups.json"

# Group types whose entries are all leaf countries -- not expandable groups.
# Exclude them from the output entirely.
LEAF_ONLY_TYPES = {"WLD", "_T"}


def load_name_map(codelist_path: Path) -> dict[str, str]:
    """Build a {code: name} map from CL_REF_GROUPINGS."""
    with open(codelist_path, encoding="utf-8") as f:
        data = json.load(f)
    codes = data["data"]["codelists"][0]["codes"]
    return {c["id"]: c["name"] for c in codes}


def extract_groups(
    hierarchy_path: Path,
    name_map: dict[str, str],
) -> tuple[dict[str, dict], set[str], str]:
    """Parse the FMR hierarchy and return (groups, all_countries, version).

    groups format:
        {
            "SAS": {"name": "South Asia", "type": "REGION", "countries": [...]},
            ...
        }
    all_countries: set of all individual country codes appearing in any group.
    """
    with open(hierarchy_path, encoding="utf-8") as f:
        data = json.load(f)

    hcl = data["data"]["hierarchicalCodelists"][0]
    version = hcl["version"]
    hierarchy = hcl["hierarchies"][0]
    top_level = hierarchy["hierarchicalCodes"]

    groups: dict[str, dict] = {}
    all_countries: set[str] = set()

    for type_node in top_level:
        group_type = type_node["id"]
        if group_type in LEAF_ONLY_TYPES:
            continue

        for group_node in type_node.get("hierarchicalCodes", []):
            group_id = group_node["id"]
            country_nodes = group_node.get("hierarchicalCodes", [])
            if not country_nodes:
                # This group has no children in the hierarchy -- skip.
                continue

            countries = sorted(c["id"] for c in country_nodes)
            all_countries.update(countries)

            # Strip UTF-8 mojibake that appears in some FMR source names
            # (e.g. 9WN: "Western Asia\u00c2\u00a0 and ..." — UTF-8 NBSP bytes
            # decoded as Latin-1 produce the two-character sequence \u00c2\u00a0).
            raw_name = name_map.get(group_id, group_id)
            clean_name = " ".join(raw_name.replace("\u00c2\u00a0", " ").split())

            groups[group_id] = {
                "name": clean_name,
                "type": group_type,
                "countries": countries,
            }

    return groups, all_countries, version


def build(hierarchy_path: Path, codelist_path: Path, output_path: Path) -> None:
    """Build and write the ref_area_groups.json output file."""
    print(f"Reading hierarchy: {hierarchy_path}")
    print(f"Reading codelist:  {codelist_path}")

    name_map = load_name_map(codelist_path)
    groups, all_countries, version = extract_groups(hierarchy_path, name_map)

    group_types = sorted({v["type"] for v in groups.values()})

    output = {
        "_meta": {
            "source": f"FMR H_REF_AREA_GROUPS v{version} + CL_REF_GROUPINGS",
            "built_at": datetime.now(UTC).strftime("%Y-%m-%d"),
            "hierarchy_version": version,
            "total_groups": len(groups),
            "total_countries": len(all_countries),
            "group_types": group_types,
            "note": (
                "Re-generate with: uv run python scripts/build_ref_area_groups.py"
            ),
        },
        "groups": groups,
        "all_countries": sorted(all_countries),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {output_path}")
    print(f"  Groups: {len(groups)}")
    print(f"  Countries: {len(all_countries)}")
    print(f"  Group types: {group_types}")
    size_kb = output_path.stat().st_size / 1024
    print(f"  File size: {size_kb:.1f} KB")


if __name__ == "__main__":
    build(HIERARCHY_FILE, CODELIST_FILE, OUTPUT_FILE)
