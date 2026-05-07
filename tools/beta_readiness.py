#!/usr/bin/env python3
"""Check whether AGILAB is ready for a beta release promotion."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
BETA_CLASSIFIER = "Development Status :: 4 - Beta"
ALPHA_CLASSIFIER = "Development Status :: 3 - Alpha"
RELEASE_PACKAGE_PYPROJECTS = (
    "pyproject.toml",
    "src/agilab/core/agi-core/pyproject.toml",
    "src/agilab/core/agi-env/pyproject.toml",
    "src/agilab/core/agi-node/pyproject.toml",
    "src/agilab/core/agi-cluster/pyproject.toml",
    "src/agilab/lib/agi-gui/pyproject.toml",
)
TYPING_POLICY_PACKAGE_MODULES = {
    "pyproject.toml": "agilab",
    "src/agilab/core/agi-core/pyproject.toml": "agi_core",
    "src/agilab/core/agi-env/pyproject.toml": "agi_env",
    "src/agilab/core/agi-node/pyproject.toml": "agi_node",
    "src/agilab/core/agi-cluster/pyproject.toml": "agi_cluster",
}
RELEASE_PREFLIGHT_PROFILES = (
    "agi-env",
    "agi-core-combined",
    "agi-gui",
    "docs",
    "installer",
    "shared-core-typing",
    "dependency-policy",
)
PUBLIC_DOC_FILES = (
    "README.md",
    "docs/source/index.rst",
    "docs/source/package-publishing-policy.rst",
    "docs/source/beta-readiness.rst",
)
README_MATURITY_STATUSES = {
    "Local run": "Stable",
    "Distributed (Dask)": "Stable",
    "UI Streamlit": "Beta",
    "MLflow": "Beta",
    "Production": "Experimental",
}
README_MATURITY_SCOPE_MARKERS = (
    "remote cluster\nmounts, credentials, and hardware stacks remain environment-dependent",
    "Production-grade MLOps features are delivered through integrations",
    "not\nyet a packaged platform claim",
)
ALLOWED_APP_ENTRIES = {
    ".DS_Store",
    ".gitignore",
    "README.md",
    "__init__.py",
    "__pycache__",
    "builtin",
    "install.py",
    "src",
    "templates",
}
FINAL_NETWORK_COMMANDS = (
    "uv --preview-features extra-build-dependencies run python tools/hf_space_smoke.py --json",
)
FINAL_LOCAL_COMMANDS = (
    "uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile agi-env --profile agi-core-combined --profile agi-gui --profile docs --profile installer --profile shared-core-typing --profile dependency-policy",
    "uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py --with-install",
    "uv --preview-features extra-build-dependencies run python tools/pypi_publish.py --repo testpypi --dry-run --verbose",
)


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class GateCheck:
    name: str
    success: bool
    detail: str
    severity: str = "error"
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GateSummary:
    final: bool
    include_network: bool
    success: bool
    checks: list[GateCheck]
    required_commands: list[str]


def _run_command(argv: Sequence[str], *, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=str(cwd),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _read_pyproject(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def package_classifiers(repo_root: Path = REPO_ROOT) -> dict[str, list[str]]:
    classifiers: dict[str, list[str]] = {}
    for rel_path in RELEASE_PACKAGE_PYPROJECTS:
        path = repo_root / rel_path
        payload = _read_pyproject(path)
        project = payload.get("project", {})
        values = project.get("classifiers", [])
        classifiers[rel_path] = [str(value) for value in values]
    return classifiers


def check_package_classifiers(repo_root: Path = REPO_ROOT, *, final: bool) -> GateCheck:
    classifiers = package_classifiers(repo_root)
    missing_status = [
        path
        for path, values in classifiers.items()
        if not any(value.startswith("Development Status :: ") for value in values)
    ]
    if missing_status:
        return GateCheck(
            "package classifiers",
            False,
            "Missing Development Status classifier in: " + ", ".join(missing_status),
            evidence=missing_status,
        )

    if final:
        not_beta = [
            path
            for path, values in classifiers.items()
            if BETA_CLASSIFIER not in values or ALPHA_CLASSIFIER in values
        ]
        return GateCheck(
            "package classifiers",
            not not_beta,
            (
                "All release packages are marked beta."
                if not not_beta
                else "Release packages still need beta classifiers: " + ", ".join(not_beta)
            ),
            evidence=not_beta,
        )

    alpha = [path for path, values in classifiers.items() if ALPHA_CLASSIFIER in values]
    return GateCheck(
        "package classifiers",
        True,
        (
            "Development Status classifiers are present. "
            f"{len(alpha)} package(s) still say Alpha; switch them only after the final gate passes."
        ),
        severity="info",
        evidence=alpha,
    )


def _workflow_profiles(repo_root: Path = REPO_ROOT) -> set[str]:
    workflow_path = repo_root / "tools" / "workflow_parity.py"
    if not workflow_path.is_file():
        return set()

    sys.path.insert(0, str(repo_root / "tools"))
    try:
        import workflow_parity  # type: ignore

        return set(workflow_parity._profile_descriptions())
    finally:
        try:
            sys.path.remove(str(repo_root / "tools"))
        except ValueError:
            pass


def check_release_preflight_profiles(repo_root: Path = REPO_ROOT) -> GateCheck:
    workflow_profiles = _workflow_profiles(repo_root)
    missing_workflow = [profile for profile in RELEASE_PREFLIGHT_PROFILES if profile not in workflow_profiles]

    publish_text = (repo_root / "tools/pypi_publish.py").read_text(encoding="utf-8")
    missing_publish = [
        profile
        for profile in RELEASE_PREFLIGHT_PROFILES
        if f'"{profile}"' not in publish_text and f"'{profile}'" not in publish_text
    ]
    missing = sorted(set(missing_workflow + missing_publish))
    return GateCheck(
        "release preflight profiles",
        not missing,
        (
            "PyPI release preflight includes the required local parity profiles."
            if not missing
            else "Missing release preflight profile(s): " + ", ".join(missing)
        ),
        evidence=missing,
    )


def _mypy_policy_disallows_untyped_defs(payload: dict, module_name: str) -> bool:
    tool = payload.get("tool", {})
    mypy = tool.get("mypy", {}) if isinstance(tool, dict) else {}
    if not isinstance(mypy, dict):
        return False
    if mypy.get("disallow_untyped_defs") is True:
        return True

    overrides = mypy.get("overrides", [])
    if not isinstance(overrides, list):
        return False
    accepted_modules = {module_name, f"{module_name}.*"}
    for override in overrides:
        if not isinstance(override, dict) or override.get("disallow_untyped_defs") is not True:
            continue
        modules = override.get("module")
        if isinstance(modules, str):
            module_values = {modules}
        elif isinstance(modules, list):
            module_values = {str(item) for item in modules}
        else:
            module_values = set()
        if module_values & accepted_modules:
            return True
    return False


def check_typing_policy(repo_root: Path = REPO_ROOT) -> GateCheck:
    missing: list[str] = []
    for rel_path, module_name in TYPING_POLICY_PACKAGE_MODULES.items():
        path = repo_root / rel_path
        if not path.is_file():
            missing.append(f"{rel_path}: missing pyproject")
            continue
        payload = _read_pyproject(path)
        if not _mypy_policy_disallows_untyped_defs(payload, module_name):
            missing.append(f"{rel_path}: disallow_untyped_defs not enforced for {module_name}")

    return GateCheck(
        "typing policy",
        not missing,
        (
            "Release pyprojects enforce disallow_untyped_defs for public package code."
            if not missing
            else "Typing policy drift detected: " + "; ".join(missing)
        ),
        evidence=missing,
    )


def _top_level_app_entry(rel_path: str) -> str | None:
    parts = PurePosixPath(rel_path).parts
    if len(parts) < 4 or parts[:3] != ("src", "agilab", "apps"):
        return None
    return parts[3]


def _tracked_app_entry_names(repo_root: Path, runner: CommandRunner) -> list[str] | None:
    result = runner(["git", "-C", str(repo_root), "ls-files", "-z", "--", "src/agilab/apps"])
    if result.returncode != 0:
        return None

    names = {
        name
        for raw_path in result.stdout.split("\0")
        if raw_path
        for name in [_top_level_app_entry(raw_path)]
        if name is not None
    }
    return sorted(names)


def _filesystem_app_entry_names(repo_root: Path) -> list[str]:
    apps_dir = repo_root / "src/agilab/apps"
    if not apps_dir.is_dir():
        return []
    return sorted(entry.name for entry in apps_dir.iterdir())


def _format_local_app_entry(entry: Path) -> str:
    return f"{entry.name} -> {entry.readlink()}" if entry.is_symlink() else entry.name


def _is_git_ignored(repo_root: Path, rel_path: str, runner: CommandRunner) -> bool:
    result = runner(["git", "-C", str(repo_root), "check-ignore", "--quiet", rel_path])
    return result.returncode == 0


def _ignored_local_non_public_app_entries(
    repo_root: Path,
    tracked_names: set[str],
    runner: CommandRunner,
) -> list[str]:
    apps_dir = repo_root / "src/agilab/apps"
    if not apps_dir.is_dir():
        return []

    ignored: list[str] = []
    for entry in sorted(apps_dir.iterdir(), key=lambda item: item.name):
        if entry.name in ALLOWED_APP_ENTRIES or entry.name in tracked_names:
            continue
        rel_path = str(entry.relative_to(repo_root))
        if _is_git_ignored(repo_root, rel_path, runner):
            ignored.append(_format_local_app_entry(entry))
    return ignored


def check_public_app_tree(
    repo_root: Path = REPO_ROOT,
    runner: CommandRunner = _run_command,
) -> GateCheck:
    tracked_names = _tracked_app_entry_names(repo_root, runner)
    if tracked_names is None:
        app_names = _filesystem_app_entry_names(repo_root)
        source = "filesystem entries"
    else:
        app_names = tracked_names
        source = "tracked release entries"

    offenders = [name for name in app_names if name not in ALLOWED_APP_ENTRIES]
    ignored = _ignored_local_non_public_app_entries(repo_root, set(tracked_names or []), runner)
    if offenders:
        detail = f"Non-public app entries found in {source}: " + ", ".join(offenders)
    elif ignored:
        detail = (
            "src/agilab/apps tracked release entries are public-only. "
            "Ignored local non-public app entries are present but not release-blocking: "
            + ", ".join(ignored)
        )
    else:
        detail = "src/agilab/apps contains only public deploy entries."
    return GateCheck(
        "public app tree",
        not offenders,
        detail,
        evidence=offenders,
    )


def check_docs_have_beta_readiness(repo_root: Path = REPO_ROOT, *, final: bool) -> GateCheck:
    missing = [path for path in PUBLIC_DOC_FILES if not (repo_root / path).is_file()]
    if missing:
        return GateCheck(
            "beta readiness docs",
            False,
            "Missing public beta-readiness documentation: " + ", ".join(missing),
            evidence=missing,
        )

    if final:
        stale_alpha: list[str] = []
        for rel_path in PUBLIC_DOC_FILES:
            text = (repo_root / rel_path).read_text(encoding="utf-8").lower()
            if "alpha-stage" in text or "development status :: 3 - alpha" in text:
                stale_alpha.append(rel_path)
        return GateCheck(
            "beta readiness docs",
            not stale_alpha,
            (
                "Public docs no longer present the promoted release as alpha."
                if not stale_alpha
                else "Public docs still contain alpha wording: " + ", ".join(stale_alpha)
            ),
            evidence=stale_alpha,
        )

    return GateCheck(
        "beta readiness docs",
        True,
        "Public beta-readiness documentation is present.",
        severity="info",
    )


def readme_maturity_statuses(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    readme_path = repo_root / "README.md"
    if not readme_path.is_file():
        return {}

    lines = readme_path.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("### Maturity snapshot")
    except ValueError:
        return {}

    statuses: dict[str, str] = {}
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped:
            if statuses:
                break
            continue
        if not stripped.startswith("|"):
            if statuses:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 2 or cells[0] in {"Capability", "---"}:
            continue
        statuses[cells[0]] = cells[1]
    return statuses


def check_public_maturity_positioning(repo_root: Path = REPO_ROOT) -> GateCheck:
    readme_path = repo_root / "README.md"
    if not readme_path.is_file():
        return GateCheck(
            "public maturity positioning",
            False,
            "README.md is missing, so public maturity claims cannot be checked.",
            evidence=["README.md"],
        )

    statuses = readme_maturity_statuses(repo_root)
    mismatches = [
        f"{capability}: expected {expected}, found {statuses.get(capability, '<missing>')}"
        for capability, expected in README_MATURITY_STATUSES.items()
        if statuses.get(capability) != expected
    ]
    readme = readme_path.read_text(encoding="utf-8")
    missing_scope = [marker for marker in README_MATURITY_SCOPE_MARKERS if marker not in readme]
    success = not mismatches and not missing_scope
    detail = (
        "README maturity snapshot matches the audited beta scope."
        if success
        else "README maturity snapshot drifted from audited scope."
    )
    evidence = mismatches + [f"missing scope marker: {marker}" for marker in missing_scope]
    return GateCheck(
        "public maturity positioning",
        success,
        detail if not evidence else f"{detail} " + "; ".join(evidence),
        evidence=evidence,
    )


def check_git_clean(
    runner: CommandRunner = _run_command,
    *,
    allow_dirty: bool,
) -> GateCheck:
    result = runner(["git", "status", "--porcelain=v1"])
    dirty_lines = [line for line in result.stdout.splitlines() if line.strip()]
    success = result.returncode == 0 and (allow_dirty or not dirty_lines)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git status failed").strip()
    elif dirty_lines and not allow_dirty:
        detail = "Working tree has uncommitted changes."
    elif dirty_lines:
        detail = "Working tree is dirty, allowed for this non-final check."
    else:
        detail = "Working tree is clean."
    return GateCheck("git clean", success, detail, evidence=dirty_lines)


def check_git_aligned(
    runner: CommandRunner = _run_command,
    *,
    final: bool,
) -> GateCheck:
    head = runner(["git", "rev-parse", "HEAD"])
    origin = runner(["git", "rev-parse", "origin/main"])
    if head.returncode != 0 or origin.returncode != 0:
        detail = (head.stderr or origin.stderr or "Unable to resolve HEAD/origin/main").strip()
        return GateCheck("git origin alignment", not final, detail, severity="warning")
    head_sha = head.stdout.strip()
    origin_sha = origin.stdout.strip()
    return GateCheck(
        "git origin alignment",
        head_sha == origin_sha or not final,
        (
            "HEAD matches origin/main."
            if head_sha == origin_sha
            else f"HEAD {head_sha[:12]} differs from origin/main {origin_sha[:12]}."
        ),
        severity="error" if final else "info",
        evidence=[] if head_sha == origin_sha else [head_sha, origin_sha],
    )


def check_hf_space_public(
    runner: CommandRunner = _run_command,
    *,
    final: bool,
) -> GateCheck:
    result = runner(["hf", "spaces", "info", "jpmorard/agilab", "--format", "json"])
    if result.returncode != 0:
        return GateCheck(
            "Hugging Face Space public",
            not final,
            "Unable to query HF Space: " + (result.stderr or result.stdout).strip(),
            severity="error" if final else "warning",
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return GateCheck(
            "Hugging Face Space public",
            False,
            f"Unable to parse HF Space JSON: {exc}",
        )
    private = bool(payload.get("private"))
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    stage = str(runtime.get("stage", "unknown"))
    runtime_raw = runtime.get("raw") if isinstance(runtime.get("raw"), dict) else {}
    runtime_sha = str(runtime_raw.get("sha", ""))
    repo_sha = str(payload.get("sha", ""))
    success = not private and stage == "RUNNING" and bool(repo_sha) and runtime_sha == repo_sha
    detail = (
        f"private={private}, stage={stage}, repo_sha={repo_sha[:12]}, runtime_sha={runtime_sha[:12]}"
    )
    return GateCheck("Hugging Face Space public", success, detail)


def build_required_commands(*, include_network: bool) -> list[str]:
    commands = list(FINAL_LOCAL_COMMANDS)
    if include_network:
        commands.extend(FINAL_NETWORK_COMMANDS)
    else:
        commands.append("uv --preview-features extra-build-dependencies run python tools/hf_space_smoke.py --json")
    return commands


def run_gate(
    *,
    repo_root: Path = REPO_ROOT,
    final: bool = False,
    include_network: bool = False,
    allow_dirty: bool = False,
    runner: CommandRunner = _run_command,
) -> GateSummary:
    checks = [
        check_git_clean(runner, allow_dirty=allow_dirty and not final),
        check_git_aligned(runner, final=final),
        check_package_classifiers(repo_root, final=final),
        check_release_preflight_profiles(repo_root),
        check_typing_policy(repo_root),
        check_public_app_tree(repo_root, runner),
        check_docs_have_beta_readiness(repo_root, final=final),
        check_public_maturity_positioning(repo_root),
    ]
    if include_network:
        checks.append(check_hf_space_public(runner, final=final))
    elif final:
        checks.append(
            GateCheck(
                "Hugging Face Space public",
                False,
                "Final beta gate requires --include-network so the public Space SHA and runtime are verified.",
            )
        )

    success = all(check.success or check.severity in {"info", "warning"} for check in checks)
    if final:
        success = all(check.success for check in checks)

    return GateSummary(
        final=final,
        include_network=include_network,
        success=success,
        checks=checks,
        required_commands=build_required_commands(include_network=include_network),
    )


def render_human(summary: GateSummary) -> str:
    lines = [
        "AGILAB beta-readiness gate",
        f"mode: {'final' if summary.final else 'planning'}",
        f"network: {'included' if summary.include_network else 'not included'}",
        f"verdict: {'PASS' if summary.success else 'FAIL'}",
        "",
        "Checks:",
    ]
    for check in summary.checks:
        status = "OK" if check.success else ("WARN" if check.severity == "warning" else "FAIL")
        lines.append(f"- {check.name}: {status} - {check.detail}")
    lines.extend(["", "Required final RC commands:"])
    for command in summary.required_commands:
        lines.append(f"- {command}")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check AGILAB beta release readiness.")
    parser.add_argument("--final", action="store_true", help="Require the final beta promotion contract.")
    parser.add_argument(
        "--include-network",
        action="store_true",
        help="Query Hugging Face Space state as part of the gate.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow a dirty worktree in planning mode. Ignored with --final.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    summary = run_gate(
        final=args.final,
        include_network=args.include_network,
        allow_dirty=args.allow_dirty,
    )
    if args.json:
        print(json.dumps(asdict(summary), indent=2))
    else:
        print(render_human(summary))
    return 0 if summary.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
