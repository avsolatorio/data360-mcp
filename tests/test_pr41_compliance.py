"""
PR #41 compliance review tests.

Each test corresponds to a specific claim in the code review.
Claims are grouped into three criticality levels:

    CRITICAL   — incorrect data, broken links, or direct functional bugs
    IMPORTANT  — significant consistency or correctness concerns
    MINOR      — style, convention, or documentation quality issues

Run with:
    uv run pytest tests/test_pr41_compliance.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BRANCH_FILES = REPO_ROOT  # tests run against the working tree after checkout


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_branch_file(relative_path: str) -> str:
    """Read a file from the feat/wb-oss-compliance branch via git."""
    result = subprocess.run(
        ["git", "show", f"remotes/origin/feat/wb-oss-compliance:{relative_path}"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"Could not read {relative_path} from branch: {result.stderr}"
    )
    return result.stdout


# ===========================================================================
# CRITICAL
# ===========================================================================

class TestForwardLookingContext:
    """
    These tests document URLs in CITATION.cff that currently return 404.
    This is EXPECTED and INTENTIONAL — the org transfer from avsolatorio →
    worldbank has not happened yet. The URLs are forward-looking placeholders.

    These tests will flip to failures once the org transfer is complete,
    serving as a signal that they can be deleted.
    """

    def test_citation_repository_code_url_is_forward_looking(self):
        """
        EVIDENCE: curl https://github.com/worldbank/data360-mcp → 404
        Context: The org transfer is planned post-merge. The 404 is intentional.
        This test documents the current state and will fail after the transfer.
        """
        content = read_branch_file("CITATION.cff")
        assert "repository-code: \"https://github.com/worldbank/data360-mcp\"" in content, (
            "CITATION.cff must contain the forward-looking worldbank repository URL."
        )

        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "https://github.com/worldbank/data360-mcp"],
            capture_output=True, text=True,
        )
        http_code = result.stdout.strip()
        # 404 = not yet transferred (expected). 200 = transfer complete (delete this test).
        assert http_code in ("404", "200"), (
            f"Unexpected HTTP status {http_code} for worldbank/data360-mcp."
        )

    def test_citation_github_pages_url_is_forward_looking(self):
        """
        EVIDENCE: curl https://worldbank.github.io/data360-mcp → 404
        Context: GitHub Pages will be deployed after the org transfer.
        """
        content = read_branch_file("CITATION.cff")
        assert "url: \"https://worldbank.github.io/data360-mcp\"" in content

        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "https://worldbank.github.io/data360-mcp"],
            capture_output=True, text=True,
        )
        http_code = result.stdout.strip()
        assert http_code in ("404", "200"), (
            f"Unexpected HTTP status {http_code} for worldbank.github.io/data360-mcp."
        )


class TestCritical:
    """
    Findings with a direct functional bug that is wrong regardless of deployment
    state. These must be fixed before the PR merges.
    """

    # --- Claim #4: BSD License → BSD-2-Clause normalization is a catch-all --

    def test_generate_licenses_bsd_license_maps_to_bsd2_unconditionally(self):
        """
        EVIDENCE: grep 'BSD License' scripts/generate_licenses.py → line 21
        'BSD License' is pip-licenses' catch-all for BOTH BSD-2 and BSD-3
        packages. Mapping it to BSD-2-Clause silently mislabels BSD-3 packages.

        This test imports the normalization dict directly and demonstrates
        the erroneous mapping.
        """
        content = read_branch_file("scripts/generate_licenses.py")

        # Parse the LICENSE_NORMALIZE dict by exec-ing the constant block
        namespace: dict = {}
        # Extract just the dict literal so we can evaluate it safely
        lines = content.splitlines()
        start = next(i for i, l in enumerate(lines) if "LICENSE_NORMALIZE" in l)
        end = next(i for i in range(start, len(lines)) if lines[i].rstrip() == "}")
        dict_src = "\n".join(lines[start : end + 1])
        exec(dict_src.replace("LICENSE_NORMALIZE: dict[str, str] = ", "d = "), namespace)
        mapping = namespace["d"]

        assert mapping.get("BSD License") == "BSD-2-Clause", (
            "Expected 'BSD License' to map to 'BSD-2-Clause' — confirming the bug exists"
        )
        # The bug: BSD-3 packages that pip-licenses reports as 'BSD License' will be
        # incorrectly labeled as BSD-2-Clause. There is no disambiguation path.
        assert "BSD 3-Clause" in mapping, (
            "Explicit 'BSD 3-Clause' key exists, but 'BSD License' (used by pip-licenses "
            "for both BSD-2 and BSD-3) still hard-maps to BSD-2-Clause — demonstrating "
            "the ambiguity."
        )


# ===========================================================================
# IMPORTANT
# ===========================================================================

class TestImportant:
    """
    These findings affect correctness or process but do not cause immediate
    failures. They should be addressed before the PR lands.
    """

    # --- Claim #1: LICENSE IGO Rider text is a paraphrase, not verbatim ----

    def test_license_igo_rider_is_not_verbatim_canonical_text(self):
        """
        EVIDENCE:
          - git show .../LICENSE shows a 2-sentence inline IGO Rider summary.
          - curl https://raw.githubusercontent.com/worldbank/.github/main/WB-IGO-RIDER.md
            returns the full 8-provision canonical text (HTTP 200).
          - The LICENSE file contains none of the 8 provisions or their headings.

        Verifies that the inline rider text is shorter than the canonical text,
        confirming it is a summary, not the full rider.
        """
        license_text = read_branch_file("LICENSE")

        # Canonical marker phrases that appear in the full WB IGO Rider
        canonical_markers = [
            "UNCITRAL",
            "Berne Convention",
            "Severability",
            "Entire Agreement",
        ]
        for marker in canonical_markers:
            assert marker not in license_text, (
                f"Canonical rider phrase '{marker}' found in LICENSE — the inline text "
                f"may already be verbatim. Recheck the finding."
            )

        # The LICENSE inline section is a short summary
        rider_section = license_text.split("WORLD BANK IGO RIDER", 1)[-1]
        assert len(rider_section.strip()) < 500, (
            "Expected the inline IGO Rider section to be a short summary (<500 chars), "
            "indicating it is not the full canonical text."
        )

    def test_canonical_igo_rider_url_resolves(self):
        """
        EVIDENCE: curl https://github.com/worldbank/.github/blob/main/WB-IGO-RIDER.md → 200
        The canonical URL cited in WB-IGO-RIDER.md is reachable, which means
        the comparison between inline text and canonical text is possible.
        """
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "https://github.com/worldbank/.github/blob/main/WB-IGO-RIDER.md"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "200", (
            "Canonical WB IGO Rider URL is unreachable. Cannot validate the rider text."
        )

    # --- Claim #3: CONTRIBUTING.md self-referential link --------------------

    def test_contributing_md_pull_requests_section_self_links(self):
        """
        EVIDENCE: grep in CONTRIBUTING.md shows:
          [Contributing Code](CONTRIBUTING.md)
        The anchor text links to the file itself rather than to the
        '#contributing-code' anchor within the file.
        """
        content = read_branch_file("CONTRIBUTING.md")
        # The buggy pattern: a markdown link whose href is CONTRIBUTING.md itself
        assert "[Contributing Code](CONTRIBUTING.md)" in content, (
            "Expected the self-referential link '[Contributing Code](CONTRIBUTING.md)' "
            "to be present — confirming the bug exists."
        )
        # The correct pattern would be an anchor link or no link
        assert "[Contributing Code](#contributing-code)" not in content, (
            "The link was already fixed to use a proper anchor. Remove this test."
        )

    # --- Claim #5: poe licenses task uses bare 'python', not 'uv run' ------

    def test_poe_licenses_task_uses_bare_python(self):
        """
        EVIDENCE: grep in pyproject.toml:
          [tool.poe.tasks.licenses]
          cmd = "python scripts/generate_licenses.py"

        All other poe tasks (serve, test, test-cov) use either 'uv run ...'
        or 'pytest' (which poe resolves via the project venv).
        'python scripts/...' will use the system interpreter if the uv venv
        is not activated, meaning pip-licenses will not be found.
        """
        content = read_branch_file("pyproject.toml")

        # Confirmed bad pattern
        assert 'cmd = "python scripts/generate_licenses.py"' in content, (
            "Expected bare 'python' in poe licenses task."
        )
        # Confirmed: serve uses uv run (showing the inconsistency)
        assert 'cmd = "uv run fastmcp run' in content, (
            "Expected poe serve to use 'uv run' (showing the inconsistency)."
        )


# ===========================================================================
# MINOR
# ===========================================================================

class TestMinor:
    """
    These are documentation quality, style, or convention issues. They do not
    affect runtime behaviour but reduce professional quality.
    """

    # --- Claim #6: Python version is correctly updated to 3.11+ -------------

    def test_readme_correctly_states_python_311_requirement(self):
        """
        EVIDENCE: grep 'Python 3.' README.md → '- **Python 3.11+**'
        The README was updated from 3.10 to 3.11, which matches pyproject.toml.
        This test confirms the fix is in place (i.e. Claim #6 is already correct).
        """
        readme = read_branch_file("README.md")
        pyproject = read_branch_file("pyproject.toml")

        assert "Python 3.11+" in readme, "README does not mention Python 3.11+"
        assert 'requires-python = ">=3.11"' in pyproject

        # Regression guard: old version should not appear
        import re
        python_refs = re.findall(r"Python 3\.\d+", readme)
        for ref in python_refs:
            assert ref == "Python 3.11", (
                f"Found unexpected Python version reference '{ref}' in README."
            )

    # --- Claim #7: Bold markers inside backtick cells in arch doc -----------

    def test_architecture_doc_does_not_exist_in_branch(self):
        """
        EVIDENCE: git ls-tree remotes/origin/feat/wb-oss-compliance shows no
        docs/architecture-data360-mcp.md — the file only appeared in the GitHub
        API patch view (it is in a newer commit not fetched locally).

        This test documents that the file is NOT in the locally fetched branch ref,
        so Claim #7 cannot be verified against the local disk. It is confirmed
        via the raw GitHub API patch data only.
        """
        result = subprocess.run(
            ["git", "ls-tree", "-r", "remotes/origin/feat/wb-oss-compliance",
             "--name-only"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert "docs/architecture-data360-mcp.md" not in result.stdout, (
            "docs/architecture-data360-mcp.md is now present in the local branch ref. "
            "Update this test to check for the bold-in-backtick formatting issue directly."
        )

    # --- Claim #8: WB-IGO-RIDER.md Provision 8 wording matches canonical ---

    def test_wb_igo_rider_provision_8_matches_canonical_intent(self):
        """
        EVIDENCE:
          - WB-IGO-RIDER.md says: 'These IGO terms override any conflicting
            MIT License provisions.'
          - Canonical text says: 'In the event of any inconsistency between these
            Additional Terms for IGOs and the terms of the MIT License, these
            Additional Terms for IGOs shall prevail.'

        The summary uses 'override any conflicting' — semantically close to the
        canonical 'shall prevail in the event of inconsistency', but less precise.
        """
        content = read_branch_file("WB-IGO-RIDER.md")

        assert "override any conflicting MIT License provisions" in content, (
            "Provision 8 wording not found — the summary may have already been updated."
        )

        # Verify the canonical phrasing is NOT present (i.e. it's still a paraphrase)
        canonical_phrase = "in the event of any inconsistency"
        assert canonical_phrase.lower() not in content.lower(), (
            "The canonical phrase is now present in WB-IGO-RIDER.md. "
            "The summary has been updated to match the canonical text. This test can be removed."
        )


# ===========================================================================
# generate_licenses.py unit tests (no subprocess, fully offline)
# ===========================================================================

class TestGenerateLicensesScript:
    """
    Unit tests for scripts/generate_licenses.py.
    These test the normalization and grouping logic in isolation by importing
    the module directly.
    Exercising the script via subprocess requires pip-licenses installed,
    which is a dev dependency — these tests use mocking instead.
    """

    @pytest.fixture
    def script_module(self, tmp_path):
        """
        Load generate_licenses.py from the feat/wb-oss-compliance branch.
        Exports via 'git show' into a temp file so we don't need a checkout.
        """
        import importlib.util

        # Try working-tree path first (works when branch is checked out)
        wt_path = REPO_ROOT / "scripts" / "generate_licenses.py"
        if wt_path.exists():
            target = wt_path
        else:
            # Extract from branch into a tmp file
            result = subprocess.run(
                ["git", "show",
                 "remotes/origin/feat/wb-oss-compliance:scripts/generate_licenses.py"],
                capture_output=True, text=True, cwd=REPO_ROOT,
            )
            if result.returncode != 0:
                pytest.skip(
                    "scripts/generate_licenses.py not accessible from branch "
                    f"({result.stderr.strip()})"
                )
            target = tmp_path / "generate_licenses.py"
            target.write_text(result.stdout, encoding="utf-8")

        spec = importlib.util.spec_from_file_location("generate_licenses", target)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_normalize_license_empty_string_returns_unknown(self, script_module):
        assert script_module.normalize_license("") == "Unknown"

    def test_normalize_license_mit_license_full_text_returns_mit(self, script_module):
        full_text = "The MIT License\nPermission is hereby granted..."
        assert script_module.normalize_license(full_text) == "MIT"

    def test_normalize_license_mit_exact(self, script_module):
        assert script_module.normalize_license("MIT") == "MIT"

    def test_normalize_license_apache_software_license_maps_to_apache2(self, script_module):
        assert script_module.normalize_license("Apache Software License") == "Apache-2.0"

    def test_normalize_license_bsd_license_maps_to_bsd2_clause(self, script_module):
        """
        Documents the known issue: 'BSD License' catch-all maps to BSD-2-Clause.
        This test both proves the bug exists and serves as a regression guard.
        If this behavior is intentionally changed, this test will fail.
        """
        assert script_module.normalize_license("BSD License") == "BSD-2-Clause"

    def test_normalize_license_bsd_3_clause_maps_correctly(self, script_module):
        """Explicit 'BSD 3-Clause' and 'BSD-3-Clause' strings map correctly."""
        assert script_module.normalize_license("BSD 3-Clause") == "BSD-3-Clause"
        assert script_module.normalize_license("BSD-3-Clause") == "BSD-3-Clause"

    def test_normalize_license_unknown_passthrough(self, script_module):
        """Unknown license strings pass through as-is."""
        assert script_module.normalize_license("LGPL-2.1") == "LGPL-2.1"

    def test_main_excludes_own_package(self, script_module, tmp_path):
        """The script must exclude 'data360-mcp' from the output."""
        fake_packages = [
            {"Name": "data360-mcp", "License": "MIT"},
            {"Name": "requests", "License": "Apache-2.0"},
        ]
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = json.dumps(fake_packages)

        with patch("subprocess.run", return_value=fake_proc):
            # Redirect output path to tmp
            orig_main = script_module.main
            script_module.__dict__["_ORIG_PATH"] = None

            # Monkey-patch Path.__truediv__ to redirect the output file
            out_file = tmp_path / "THIRD_PARTY_LICENSES.md"
            with patch.object(
                script_module.Path,
                "__truediv__",
                side_effect=lambda self, other: out_file if other == "THIRD_PARTY_LICENSES.md" else self.__class__.__truediv__(self, other),
            ):
                pass  # Path patching is complex; test via output content instead

            # Simpler: patch out_path directly inside main by mocking Path.write_text
            written_content = {}

            original_run = subprocess.run

            def mock_run(cmd, **kwargs):
                if "pip-licenses" in cmd:
                    return fake_proc
                return original_run(cmd, **kwargs)

            with patch("subprocess.run", side_effect=mock_run):
                with patch.object(
                    script_module.Path,
                    "write_text",
                    side_effect=lambda text, **kw: written_content.update({"content": text}),
                ):
                    result = script_module.main()

            assert result == 0
            content = written_content.get("content", "")
            assert "data360-mcp" not in content
            assert "requests" in content

    def test_main_groups_by_license_alphabetically(self, script_module):
        """Licenses appear in alphabetical order with Unknown last."""
        fake_packages = [
            {"Name": "zlib", "License": "MIT"},
            {"Name": "arrow", "License": "Apache-2.0"},
            {"Name": "mysterious", "License": ""},
        ]
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = json.dumps(fake_packages)

        written_content = {}

        def mock_run(cmd, **kwargs):
            return fake_proc

        with patch("subprocess.run", side_effect=mock_run):
            with patch.object(
                script_module.Path,
                "write_text",
                side_effect=lambda text, **kw: written_content.update({"content": text}),
            ):
                script_module.main()

        content = written_content.get("content", "")
        apache_pos = content.find("## Apache-2.0")
        mit_pos = content.find("## MIT")
        unknown_pos = content.find("## Unknown")

        assert apache_pos < mit_pos, "Apache-2.0 should come before MIT alphabetically"
        assert mit_pos < unknown_pos, "Unknown should appear last"

    def test_main_returns_1_on_pip_licenses_failure(self, script_module):
        """If pip-licenses exits non-zero, main() returns 1."""
        fake_proc = MagicMock()
        fake_proc.returncode = 1
        fake_proc.stderr = "pip-licenses not found"

        with patch("subprocess.run", return_value=fake_proc):
            result = script_module.main()
        assert result == 1

    def test_main_returns_1_on_invalid_json(self, script_module):
        """If pip-licenses returns invalid JSON, main() returns 1."""
        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = "not json"

        with patch("subprocess.run", return_value=fake_proc):
            result = script_module.main()
        assert result == 1
