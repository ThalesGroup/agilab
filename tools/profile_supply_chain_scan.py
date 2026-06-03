#!/usr/bin/env python3
"""Generate or run per-profile SBOM and pip-audit commands for AGILAB."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
from typing import Iterable, Sequence


PROFILE_EXTRAS: dict[str, tuple[str, ...]] = {
    "base": (),
    "ui": ("ui",),
    "pages": ("pages",),
    "ai": ("ai",),
    "agents": ("agents",),
    "examples": ("examples",),
    "mlflow": ("mlflow",),
    "local-llm": ("local-llm",),
    "offline": ("offline",),
    "dev": ("dev",),
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
    commands: tuple[tuple[str, ...], ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["commands"] = [list(command) for command in self.commands]
        return payload


def _profile_output_dir(output_root: Path, profile: str) -> Path:
    return output_root / profile.replace("/", "-")


def build_profile_scan(profile: str, *, output_root: Path) -> ProfileScan:
    """Return the command plan for one install profile."""
    if profile not in PROFILE_EXTRAS:
        raise ValueError(f"Unknown profile: {profile}")
    profile_dir = _profile_output_dir(output_root, profile)
    requirements = profile_dir / "requirements.txt"
    audit_requirements = profile_dir / "requirements-audit.txt"
    pip_audit_json = profile_dir / "pip-audit.json"
    sbom_json = profile_dir / "sbom-cyclonedx.json"

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
