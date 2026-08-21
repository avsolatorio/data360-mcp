"""Ensure release-please version manifest and config stay in sync with package versions."""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

CONFIG_PATH = REPO_ROOT / ".github" / "release-please-config.json"
MANIFEST_PATH = REPO_ROOT / ".github" / "release-please-manifest.json"
NPM_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "npm-release.yml"

_PYPROJECT_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _npm_version(name: str) -> str:
    data = json.loads((REPO_ROOT / "packages" / name / "package.json").read_text(encoding="utf-8"))
    assert isinstance(data.get("name"), str)
    assert data["name"] == f"@data360/{name}", f"{name} package.json name mismatch"
    v = data.get("version")
    assert isinstance(v, str) and v.strip()
    return v.strip()


def _py_version() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = _PYPROJECT_VERSION.search(text)
    assert match is not None, "missing version = ... in pyproject.toml"
    return match.group(1)


@pytest.fixture
def release_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def release_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_keys_match_config_packages(release_config: dict, release_manifest: dict) -> None:
    assert set(release_manifest) == set(release_config["packages"]), (
        "release-please-manifest keys must match config packages"
    )


def test_manifest_versions_match_package_versions(release_manifest: dict) -> None:
    expected = {
        ".": _py_version(),
        "packages/tool-types": _npm_version("tool-types"),
        "packages/mcp-viz-core": _npm_version("mcp-viz-core"),
        "packages/mcp-ui": _npm_version("mcp-ui"),
        "packages/mcp-ui-angular": _npm_version("mcp-ui-angular"),
    }
    for key, version in expected.items():
        assert release_manifest[key] == version, (
            f"manifest {key} version {release_manifest[key]!r} != package version {version!r}"
        )


def test_npm_workflow_publishes_all_config_npm_packages(release_config: dict) -> None:
    npm_names = {
        pkg[len("packages/") :]
        for pkg, cfg in release_config["packages"].items()
        if cfg["release-type"] == "node"
    }
    workflow_text = NPM_WORKFLOW_PATH.read_text(encoding="utf-8")
    for name in sorted(npm_names):
        assert f"@data360/{name}" in workflow_text, (
            f"npm-release.yml must publish @data360/{name} (missing from in-scope list)"
        )
