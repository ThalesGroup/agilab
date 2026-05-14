from __future__ import annotations

from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from package_split_contract import LIBRARY_PACKAGE_CONTRACTS, PACKAGE_NAMES, UMBRELLA_PACKAGE_CONTRACT


WORKFLOW_PATH = REPO_ROOT / ".github/workflows/pypi-publish.yaml"
TEST_PYPI_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/test-pypi-publish.yaml"


def test_pypi_publish_runs_live_artifact_index_evidence_before_publish() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "release-evidence:" in text
    assert "actions: read" in text
    assert "tools/github_actions_artifact_index.py" in text
    assert "--write-sample-directory" in text
    assert "--live-github" in text
    assert "tools/ci_artifact_harvest_report.py" in text
    assert "if uv --preview-features extra-build-dependencies run \\\n              python tools/github_actions_artifact_index.py" in text
    assert "tools/compatibility_report.py" in text
    assert "--artifact-index \"$RUNNER_TEMP/artifact_index.json\"" in text
    assert "public-evidence-sample" in text
    assert "retention-days: 7" in text
    assert (
        "publish-library-packages:\n    needs:\n      - test\n      - release-evidence\n"
        "      - supply-chain-evidence"
    ) in text
    assert "      - release-plan" in text


def test_pypi_publish_uploads_supply_chain_evidence_before_publish() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "supply-chain-evidence:" in text
    assert "tools/profile_supply_chain_scan.py" in text
    assert "--profile all" in text
    assert "--output-dir test-results/supply-chain" in text
    assert "--run" in text
    assert "scan-plan.json" in text
    assert "supply-chain-release-evidence" in text
    assert "retention-days: 90" in text


def test_pypi_publish_release_tests_use_local_parity_profiles() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert 'python-version: ["3.13"]' in text
    assert 'python-version: ["3.13", "3.14"]' not in text
    assert "tools/workflow_parity.py" in text
    assert "--profile agi-env" in text
    assert "--profile agi-gui" in text
    assert "--profile agi-core-combined" in text
    assert "--profile shared-core-typing" in text
    assert "--profile dependency-policy" in text
    assert "--profile release-proof" in text
    assert "uv run --dev --project agi-cluster python -m pytest" not in text


def test_pypi_publish_skips_existing_artifacts_and_requires_trusted_auth() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "release_tag:" in text
    assert "github.event.inputs.release_tag" in text
    assert "github.event.inputs.version" not in text
    assert "packages:" in text
    assert "roles:" in text
    assert "RELEASE_PACKAGES" in text
    assert "RELEASE_ROLES" in text
    assert "--packages \"$RELEASE_PACKAGES\"" in text
    assert "--roles \"$RELEASE_ROLES\"" in text
    assert "id-token: write" in text
    assert "name: ${{ matrix.pypi_environment }}" in text
    assert "name: pypi-agilab" in text
    assert "trusted-publisher-contract:" not in text
    assert "Render PyPI trusted publisher contract" in text
    assert "tools/pypi_trusted_publisher_contract.py" in text
    assert "--check-workflow .github/workflows/pypi-publish.yaml" in text
    assert "release-plan:" in text
    assert "Render release package plan" in text
    assert "tools/release_plan.py" in text
    assert "library_matrix: ${{ steps.release-plan.outputs.library_matrix }}" in text
    assert "library_selected: ${{ steps.release-plan.outputs.library_selected }}" in text
    assert "umbrella_selected: ${{ steps.release-plan.outputs.umbrella_selected }}" in text
    assert "pypi_publish_selected: ${{ steps.release-plan.outputs.pypi_publish_selected }}" in text
    assert "provenance_packages: ${{ steps.release-plan.outputs.provenance_packages }}" in text
    assert "include: ${{ fromJSON(needs.release-plan.outputs.library_matrix) }}" in text
    assert "needs.release-plan.outputs.library_selected == 'true'" in text
    assert "needs.release-plan.outputs.umbrella_selected == 'true'" in text
    assert "needs.release-plan.outputs.pypi_publish_selected == 'true'" in text
    assert "Report trusted publisher claim for ${{ matrix.package }}" in text
    assert "Report trusted publisher claim for agilab" in text
    assert "uses: pypa/gh-action-pypi-publish@" in text
    assert "# release/v1" in text
    assert "tools/pypi_distribution_state.py" in text
    assert "steps.library-pypi-state.outputs.all-exist != 'true'" in text
    assert "matrix.publish_to_pypi == 'true'" in text
    assert "steps.agilab-pypi-state.outputs.all-exist != 'true'" in text
    assert "PYPI_TRUSTED_PUBLISHING" in text
    assert "PyPI publication requires Trusted Publishing/OIDC" in text
    assert 'uv --preview-features extra-build-dependencies build --project "${{ matrix.project }}" --wheel' in text
    assert 'uv --preview-features extra-build-dependencies build --project "${{ matrix.project }}"' in text
    assert "uv --preview-features extra-build-dependencies build\n" in text
    assert "tools/release_artifact_manifest.py" in text
    assert "--artifact-policy wheel+sdist" in text
    assert "--artifact-policy \"${{ matrix.artifact_policy }}\"" in text
    assert "release-dist-${{ matrix.package }}" in text
    assert "workflow-dist-${{ matrix.package }}" in text
    assert "Upload ${{ matrix.package }} public release distribution evidence" in text
    assert "Upload ${{ matrix.package }} workflow-only distribution evidence" in text
    assert "release-dist-agilab" in text
    assert "packages-dir: dist-library/" not in text
    assert "packages-dir: ${{ matrix.dist }}" in text
    assert "packages-dir: dist/" in text
    assert "Build ${{ matrix.package }}" in text
    assert "Verify ${{ matrix.package }}" in text
    assert "PYPI_API_TOKEN" not in text
    assert "PYPI_SECRET" not in text
    assert "PYPI_TOKEN" not in text
    assert "TWINE_PASSWORD" not in text
    assert "twine upload" not in text


def test_pypi_publish_uses_one_trusted_publish_call_per_pypi_project() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "PyPI OIDC tokens are project-scoped" in text
    assert "distinct GitHub environment claim" in text
    assert "dist-library" not in text
    assert "fail-fast: false" in text
    assert text.count("uses: pypa/gh-action-pypi-publish@") == 2

    static_package_entries = {
        match.strip()
        for match in re.findall(r"^\s*-\s+package:\s+(.+)$", text, re.MULTILINE)
    }
    assert static_package_entries.isdisjoint(
        {package.name for package in LIBRARY_PACKAGE_CONTRACTS}
    )

    assert UMBRELLA_PACKAGE_CONTRACT.pypi_environment in text
    assert "Publish ${{ matrix.package }} to PyPI with trusted publishing" in text


def test_pypi_publish_attests_and_uploads_release_supply_chain_assets() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "pypi-provenance-evidence:" in text
    assert "tools/pypi_provenance_check.py" in text
    assert "PROVENANCE_PACKAGES: ${{ needs.release-plan.outputs.provenance_packages }}" in text
    assert "for package in ${PROVENANCE_PACKAGES}; do" in text
    assert "pypi-provenance-evidence" in text
    assert "publish-release-assets:" in text
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in text
    assert "actions/attest@59d89421af93a897026c735860bf21b6eb4f7b26" in text
    assert "attestations: write" in text
    assert "artifact-metadata: write" in text
    assert "subject-path: github-release-assets/**" in text
    assert "supply-chain-release-evidence.tar.gz" in text
    assert "pypi-provenance-evidence.tar.gz" in text
    assert "release-distribution-evidence.tar.gz" in text
    assert "shasum -a 256 * > SHA256SUMS.txt" in text
    assert "gh release upload \"$release_tag\" github-release-assets/* --clobber" in text
    assert "gh release create \"$release_tag\"" in text


def test_pypi_publish_does_not_recreate_legacy_single_pypi_environment() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    expected_environments = {
        package.pypi_environment for package in LIBRARY_PACKAGE_CONTRACTS
    } | {UMBRELLA_PACKAGE_CONTRACT.pypi_environment}

    assert "pypi" not in expected_environments
    assert len(expected_environments) == len(LIBRARY_PACKAGE_CONTRACTS) + 1
    assert re.search(r"^\s*environment:\s*pypi\s*$", text, re.MULTILINE) is None
    assert re.search(r"^\s*name:\s*pypi\s*$", text, re.MULTILINE) is None


def test_test_pypi_publish_delegates_to_the_package_release_tool() -> None:
    text = TEST_PYPI_WORKFLOW_PATH.read_text(encoding="utf-8")
    tool_text = (REPO_ROOT / "tools/pypi_publish.py").read_text(encoding="utf-8")
    contract_text = (REPO_ROOT / "tools/package_split_contract.py").read_text(encoding="utf-8")

    assert "tools/pypi_publish.py" in text
    assert "--repo testpypi" in text
    assert "--dist both" in text
    assert "--git-reset-on-failure" in text
    assert "--no-pypirc-check" in text
    assert "TWINE_USERNAME: __token__" in text
    assert "TWINE_PASSWORD: ${{ secrets.TEST_PYPI_API_TOKEN || secrets.TEST_PYPI_SECRET }}" in text

    assert "CORE = [" not in text
    assert "versions.json" not in text
    assert "Build & upload library packages" not in text
    assert "Build & upload umbrella" not in text

    assert "package_split_contract" in tool_text
    for package in PACKAGE_NAMES:
        assert package in contract_text
