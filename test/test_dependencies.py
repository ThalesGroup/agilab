import json
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Tuple

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

PKGS = ["agilab", "agi-core", "agi-env", "agi-cluster", "agi-node"]


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "pytest-version-check/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def get_version_and_requires(
    name: str, base_url: str, version: Optional[str] = None
) -> Tuple[str, List[str]]:
    """
    Return (version, requires_dist[]) for package `name` from a PyPI-like JSON API.
    If version is None, retrieves the latest.
    """
    base = base_url.rstrip("/")
    if not version:
        data = _fetch_json(f"{base}/pypi/{name}/json")
        version = data["info"]["version"]

    data = _fetch_json(f"{base}/pypi/{name}/{version}/json")
    requires = data["info"].get("requires_dist") or []
    return version, requires


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("alignment")
    group.addoption(
        "--version",
        dest="target_version",
        default=None,
        help="Specific version to check for all packages (default: latest per package).",
    )
    group.addoption(
        "--index-url",
        dest="index_url",
        default="https://test.pypi.org",
        help="Base index URL to read metadata from (default: TestPyPI).",
    )
    group.addoption(
        "--allow-mismatch",
        action="store_true",
        default=False,
        help="Allow differing published versions, only enforce inter-package requirement compatibility.",
    )


# test_dependencies.py
@pytest.fixture(scope="session")
def settings(pytestconfig) -> Dict[str, Optional[str]]:
    return {
        "target_version": pytestconfig.getoption("target_version", default=None),  # None => use latest
        "index_url": pytestconfig.getoption("index_url", default="https://test.pypi.org"),
        "allow_mismatch": pytestconfig.getoption("allow_mismatch", default=False),
    }



@pytest.fixture(scope="session")
def versions_and_requires(settings) -> Dict[str, Tuple[str, List[str]]]:
    base_url = settings["index_url"]
    target = settings["target_version"]
    out: Dict[str, Tuple[str, List[str]]] = {}
    errors = []
    for pkg in PKGS:
        try:
            ver, reqs = get_version_and_requires(pkg, base_url, version=target)
            out[pkg] = (ver, reqs)
        except urllib.error.HTTPError as e:
            errors.append(f"{pkg}: HTTP {e.code} at {e.url}")
        except Exception as e:  # pragma: no cover (network)
            errors.append(f"{pkg}: {type(e).__name__}: {e}")
    if errors:
        pytest.fail("Failed to fetch metadata:\n- " + "\n- ".join(errors))
    return out


def _all_equal(values: List[str]) -> bool:
    return all(v == values[0] for v in values)


def _parse_requirements(reqs: List[str]) -> List[Requirement]:
    parsed = []
    for r in reqs:
        try:
            parsed.append(Requirement(r))
        except Exception:
            # Ignore unparsable requirement lines rather than failing hard.
            # The compatibility test will only consider successfully parsed ones.
            pass
    return parsed


def test_versions_aligned(versions_and_requires, settings):
    """
    Ensures all packages share the same version (unless --allow-mismatch),
    using either the explicitly provided --version or each package's latest.
    """
    versions = {pkg: ver for pkg, (ver, _) in versions_and_requires.items()}
    if settings["allow_mismatch"]:
        pytest.skip("Version equality check skipped due to --allow-mismatch.")
    assert _all_equal(list(versions.values())), (
        "Versions are not aligned across packages.\n"
        + "\n".join(f"- {pkg}: {ver}" for pkg, ver in versions.items())
    )


@pytest.mark.parametrize("pkg", PKGS)
def test_inter_package_requirements_are_compatible(pkg, versions_and_requires):
    """
    For each package, if it declares dependencies on any of the sibling packages,
    ensure the specified specifier set includes that sibling's resolved version.
    """
    versions = {p: v for p, (v, _) in versions_and_requires.items()}
    _, reqs = versions_and_requires[pkg]
    parsed = _parse_requirements(reqs)

    problems = []
    for req in parsed:
        name = req.name.lower().replace("_", "-")
        if name in versions:  # dependency on a sibling package
            sibling_version = Version(versions[name])
            # If no specifier, accept any version; otherwise require compatibility.
            if req.specifier and not req.specifier.contains(sibling_version, prereleases=True):
                problems.append(
                    f"{pkg} requires '{req}' but published sibling {name} is {sibling_version}"
                )

    assert not problems, (
        f"Incompatible inter-package requirements found for {pkg}:\n- "
        + "\n- ".join(problems)
    )
