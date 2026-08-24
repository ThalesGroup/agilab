#!/usr/bin/env python3
"""Generate or run per-profile SBOM and pip-audit commands for AGILAB."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import tomllib
from typing import Iterable, Sequence

try:
    from tools.package_split_contract import APP_PROJECT_PACKAGE_SPECS
except ModuleNotFoundError:  # Direct execution via ``python tools/...``.
    from package_split_contract import APP_PROJECT_PACKAGE_SPECS

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGED_PROJECTS_PROFILE = "packaged-projects"


def _root_optional_extras(pyproject: Path = REPO_ROOT / "pyproject.toml") -> tuple[str, ...]:
    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    optional = payload.get("project", {}).get("optional-dependencies")
    if not isinstance(optional, dict) or not optional:
        raise ValueError(f"{pyproject}: [project.optional-dependencies] must be a non-empty table")
    if not all(isinstance(name, str) and name for name in optional):
        raise ValueError(f"{pyproject}: optional dependency profile names must be non-empty strings")
    return tuple(optional)


ROOT_OPTIONAL_EXTRAS = _root_optional_extras()
PROFILE_EXTRAS: dict[str, tuple[str, ...]] = {
    "base": (),
    **{extra: (extra,) for extra in ROOT_OPTIONAL_EXTRAS},
    PACKAGED_PROJECTS_PROFILE: (),
}
DEFAULT_PROFILES = tuple(PROFILE_EXTRAS)


@dataclass(frozen=True)
class ProfileScan:
    profile: str
    extras: tuple[str, ...]
    requirements: str
    audit_requirements: str
    pip_audit_json: str
    sbom_json: str
    input_requirements: str | None
    source_manifests: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["commands"] = [list(command) for command in self.commands]
        return payload


def _profile_output_dir(output_root: Path, profile: str) -> Path:
    return output_root / profile.replace("/", "-")


def packaged_project_manifests(repo_root: Path = REPO_ROOT) -> tuple[Path, ...]:
    manifests: set[Path] = set()
    for _package_name, project in APP_PROJECT_PACKAGE_SPECS:
        package_root = repo_root / project
        manifests.update(package_root.glob("src/*/project/**/pyproject.toml"))
    return tuple(sorted(manifests))


def packaged_project_dependencies(manifests: Iterable[Path]) -> tuple[str, ...]:
    dependencies: set[str] = set()
    for manifest in manifests:
        payload = tomllib.loads(manifest.read_text(encoding="utf-8"))
        project = payload.get("project")
        if not isinstance(project, dict):
            raise ValueError(f"{manifest}: missing [project] table")
        dependency_groups: list[object] = [project.get("dependencies", [])]
        optional = project.get("optional-dependencies", {})
        if not isinstance(optional, dict):
            raise ValueError(f"{manifest}: [project.optional-dependencies] must be a table")
        dependency_groups.extend(optional.values())
        for group in dependency_groups:
            if not isinstance(group, list) or not all(
                isinstance(requirement, str) and requirement.strip() for requirement in group
            ):
                raise ValueError(f"{manifest}: dependency entries must be non-empty strings")
            dependencies.update(requirement.strip() for requirement in group)
    return tuple(sorted(dependencies, key=str.casefold))


def write_packaged_project_requirements(
    destination: Path,
    manifests: Iterable[Path],
) -> None:
    dependencies = packaged_project_dependencies(manifests)
    if not dependencies:
        raise ValueError("No packaged embedded-project dependencies were discovered")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "# Direct dependencies from packaged embedded AGILAB projects.\n"
        + "\n".join(dependencies)
        + "\n",
        encoding="utf-8",
    )


def build_profile_scan(profile: str, *, output_root: Path) -> ProfileScan:
    """Return the command plan for one install profile."""
    if profile not in PROFILE_EXTRAS:
        raise ValueError(f"Unknown profile: {profile}")
    profile_dir = _profile_output_dir(output_root, profile)
    requirements = profile_dir / "requirements.txt"
    audit_requirements = profile_dir / "requirements-audit.txt"
    pip_audit_json = profile_dir / "pip-audit.json"
    sbom_json = profile_dir / "sbom-cyclonedx.json"
    input_requirements: Path | None = None
    source_manifests: tuple[Path, ...] = ()
    if profile == PACKAGED_PROJECTS_PROFILE:
        input_requirements = profile_dir / "requirements.in"
        source_manifests = packaged_project_manifests()
        export_cmd = [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "pip",
            "compile",
            "--generate-hashes",
            str(input_requirements),
            "--output-file",
            str(requirements),
        ]
    else:
        export_cmd = [
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "export",
            "--no-dev",
            "--format",
            "requirements-txt",
            "--output-file",
            str(requirements),
        ]
        for extra in PROFILE_EXTRAS[profile]:
            export_cmd.extend(["--extra", extra])

    commands = (
        tuple(export_cmd),
        (
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "--with",
            "pip-audit",
            "pip-audit",
            "-r",
            str(audit_requirements),
            "--no-deps",
            "--disable-pip",
            "--format",
            "json",
            "--output",
            str(pip_audit_json),
        ),
        (
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "--with",
            "cyclonedx-bom",
            "cyclonedx-py",
            "requirements",
            str(requirements),
            "--output-format",
            "JSON",
            "--output-file",
            str(sbom_json),
        ),
    )
    return ProfileScan(
        profile=profile,
        extras=PROFILE_EXTRAS[profile],
        requirements=str(requirements),
        audit_requirements=str(audit_requirements),
        pip_audit_json=str(pip_audit_json),
        sbom_json=str(sbom_json),
        input_requirements=str(input_requirements) if input_requirements else None,
        source_manifests=tuple(str(path.relative_to(REPO_ROOT)) for path in source_manifests),
        commands=commands,
    )


def build_scan_plan(profiles: Iterable[str], *, output_root: Path) -> list[ProfileScan]:
    return [build_profile_scan(profile, output_root=output_root) for profile in profiles]


def _expand_profiles(values: Sequence[str] | None) -> list[str]:
    if not values:
        return list(DEFAULT_PROFILES)
    expanded: list[str] = []
    for value in values:
        if value == "all":
            expanded.extend(DEFAULT_PROFILES)
            continue
        expanded.append(value)
    return list(dict.fromkeys(expanded))


def _is_local_requirement_line(stripped: str) -> bool:
    return (
        stripped.startswith("-e ")
        or stripped.startswith("--editable ")
        or stripped.startswith("file:")
        or " @ file:" in stripped
    )


def write_pip_audit_requirements(requirements: Path, audit_requirements: Path) -> None:
    """Write a pip-audit compatible requirements file without local editables."""

    lines = requirements.read_text(encoding="utf-8").splitlines(keepends=True)
    filtered: list[str] = []
    skipping_local_block = False
    for line in lines:
        stripped = line.strip()
        if skipping_local_block and (line.startswith((" ", "\t")) or stripped.startswith("--hash")):
            continue
        skipping_local_block = False
        if _is_local_requirement_line(stripped):
            skipping_local_block = True
            continue
        filtered.append(line)
    audit_requirements.write_text("".join(filtered), encoding="utf-8")


def _run_plan(plan: Sequence[ProfileScan]) -> None:
    for scan in plan:
        Path(scan.requirements).parent.mkdir(parents=True, exist_ok=True)
        if scan.input_requirements:
            write_packaged_project_requirements(
                Path(scan.input_requirements),
                (REPO_ROOT / manifest for manifest in scan.source_manifests),
            )
        for index, command in enumerate(scan.commands):
            subprocess.run(command, check=True)
            if index == 0:
                write_pip_audit_requirements(Path(scan.requirements), Path(scan.audit_requirements))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create per-profile supply-chain evidence commands. By default this prints a JSON plan; "
            "use --run to generate requirements, pip-audit JSON, and CycloneDX SBOM files."
        )
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=[*DEFAULT_PROFILES, "all"],
        help="Profile to scan. Repeatable. Defaults to all profiles.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("test-results/supply-chain"),
        help="Output directory for requirements, pip-audit JSON, and SBOM files.",
    )
    parser.add_argument("--run", action="store_true", help="Execute the generated scan commands.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    profiles = _expand_profiles(args.profile)
    plan = build_scan_plan(profiles, output_root=args.output_dir)
    payload = {
        "schema": "agilab.profile_supply_chain_scan.v1",
        "output_dir": str(args.output_dir),
        "profiles": [scan.as_dict() for scan in plan],
    }
    if args.run:
        _run_plan(plan)
    if args.json or not args.run:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
