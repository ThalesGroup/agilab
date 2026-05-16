"""Model the in-product newcomer first-proof wizard."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import shlex
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
FIRST_PROOF_PROJECT = "flight_telemetry_project"
FIRST_PROOF_RECOMMENDED_ENTRY_ID = "source-checkout-first-proof"
FIRST_PROOF_RECOMMENDED_LABEL = "Source checkout first proof"
FIRST_PROOF_HELPER_SCRIPT_PREFIXES = (
    "AGI_install_",
    "AGI_run_",
    "AGI_get_",
)
FIRST_PROOF_CLI_COMMAND = (
    "uv --preview-features extra-build-dependencies run python "
    "tools/newcomer_first_proof.py --json"
)
COMPATIBILITY_REPORT_COMMAND = (
    "uv --preview-features extra-build-dependencies run python "
    "tools/compatibility_report.py --manifest {manifest_path} --compact"
)
FIRST_PROOF_REQUIRED_VALIDATIONS = (
    "proof_steps",
    "target_seconds",
    "recommended_project",
)
DOCUMENTED_ROUTE_IDS = ("notebook-quickstart",)
REMEDIATION_LINKS = (
    ("Troubleshooting", "https://thalesgroup.github.io/agilab/newcomer-troubleshooting.html"),
    ("Quick start", "https://thalesgroup.github.io/agilab/quick-start.html"),
    ("Compatibility matrix", "https://thalesgroup.github.io/agilab/compatibility-matrix.html"),
)


@dataclass(frozen=True)
class FirstProofToolContract:
    active_app: Path
    command_labels: tuple[str, ...]
    target_seconds: float
    cli_command: str
    source: str


@dataclass(frozen=True)
class FirstProofCompatibility:
    entry_id: str
    label: str
    status: str
    report_status: str
    report_check_ids: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class FirstProofContent:
    title: str
    intro: str
    recommended_path_id: str
    recommended_path_label: str
    actionable_route_ids: tuple[str, ...]
    documented_route_ids: tuple[str, ...]
    compatibility_status: str
    compatibility_report_status: str
    proof_command_labels: tuple[str, ...]
    target_seconds: float
    cli_command: str
    run_manifest_filename: str
    steps: tuple[tuple[str, str], ...]
    success_criteria: tuple[str, ...]
    links: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "intro": self.intro,
            "recommended_path_id": self.recommended_path_id,
            "recommended_path_label": self.recommended_path_label,
            "actionable_route_ids": list(self.actionable_route_ids),
            "documented_route_ids": list(self.documented_route_ids),
            "compatibility_status": self.compatibility_status,
            "compatibility_report_status": self.compatibility_report_status,
            "proof_command_labels": list(self.proof_command_labels),
            "target_seconds": self.target_seconds,
            "cli_command": self.cli_command,
            "run_manifest_filename": self.run_manifest_filename,
            "steps": list(self.steps),
            "success_criteria": list(self.success_criteria),
            "links": list(self.links),
        }


@dataclass(frozen=True)
class FirstProofWizardState:
    content: dict[str, Any]
    compatibility_slice: str
    compatibility_status: str
    compatibility_report_status: str
    recommended_path_id: str
    recommended_path_label: str
    actionable_route_ids: tuple[str, ...]
    documented_route_ids: tuple[str, ...]
    proof_command_labels: tuple[str, ...]
    target_seconds: float
    cli_command: str
    project_path: Path | None
    project_available: bool
    active_app_name: str
    current_app_matches: bool
    output_dir: Path
    run_manifest_path: Path
    run_manifest_loaded: bool
    run_manifest_status: str
    run_manifest_passed: bool
    run_manifest_summary: dict[str, Any]
    run_manifest_validation_rows: tuple[dict[str, Any], ...]
    run_manifest_error: str | None
    remediation_status: str
    remediation_title: str
    remediation_actions: tuple[str, ...]
    remediation_links: tuple[tuple[str, str], ...]
    evidence_commands: tuple[str, ...]
    helper_scripts_present: bool
    visible_outputs: tuple[Path, ...]
    run_output_detected: bool
    next_step: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "compatibility_slice": self.compatibility_slice,
            "compatibility_status": self.compatibility_status,
            "compatibility_report_status": self.compatibility_report_status,
            "recommended_path_id": self.recommended_path_id,
            "recommended_path_label": self.recommended_path_label,
            "actionable_route_ids": list(self.actionable_route_ids),
            "documented_route_ids": list(self.documented_route_ids),
            "proof_command_labels": list(self.proof_command_labels),
            "target_seconds": self.target_seconds,
            "cli_command": self.cli_command,
            "project_path": self.project_path,
            "project_available": self.project_available,
            "active_app_name": self.active_app_name,
            "current_app_matches": self.current_app_matches,
            "output_dir": self.output_dir,
            "run_manifest_path": self.run_manifest_path,
            "run_manifest_loaded": self.run_manifest_loaded,
            "run_manifest_status": self.run_manifest_status,
            "run_manifest_passed": self.run_manifest_passed,
            "run_manifest_summary": self.run_manifest_summary,
            "run_manifest_validation_rows": list(self.run_manifest_validation_rows),
            "run_manifest_error": self.run_manifest_error,
            "remediation_status": self.remediation_status,
            "remediation_title": self.remediation_title,
            "remediation_actions": list(self.remediation_actions),
            "remediation_links": list(self.remediation_links),
            "evidence_commands": list(self.evidence_commands),
            "helper_scripts_present": self.helper_scripts_present,
            "visible_outputs": list(self.visible_outputs),
            "run_output_detected": self.run_output_detected,
            "next_step": self.next_step,
            "diagnostics": self.diagnostics,
        }


def _load_tool_module(repo_root: Path, name: str) -> Any:
    module_path = repo_root / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_for_first_proof_wizard", module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"unable to load tool module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_run_manifest_module() -> Any:
    module_path = Path(__file__).resolve().parent / "run_manifest.py"
    spec = importlib.util.spec_from_file_location("agilab_run_manifest_for_first_proof_wizard", module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"unable to load run manifest module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def first_proof_tool_contract(repo_root: Path = REPO_ROOT) -> FirstProofToolContract:
    repo_root = repo_root.resolve()
    fallback_app = repo_root / "src" / "agilab" / "apps" / "builtin" / FIRST_PROOF_PROJECT
    try:
        newcomer_first_proof = _load_tool_module(repo_root, "newcomer_first_proof")
        active_app = Path(newcomer_first_proof.DEFAULT_ACTIVE_APP)
        commands = newcomer_first_proof.build_proof_commands(active_app, with_install=False)
        return FirstProofToolContract(
            active_app=active_app,
            command_labels=tuple(command.label for command in commands),
            target_seconds=float(newcomer_first_proof.DEFAULT_MAX_SECONDS),
            cli_command=FIRST_PROOF_CLI_COMMAND,
            source="tools/newcomer_first_proof.py",
        )
    except Exception:
        return FirstProofToolContract(
            active_app=fallback_app,
            command_labels=("preinit smoke", "source ui smoke"),
            target_seconds=600.0,
            cli_command=FIRST_PROOF_CLI_COMMAND,
            source="fallback",
        )


def first_proof_compatibility(repo_root: Path = REPO_ROOT) -> FirstProofCompatibility:
    repo_root = repo_root.resolve()
    try:
        compatibility_report = _load_tool_module(repo_root, "compatibility_report")
        report = compatibility_report.build_report(repo_root=repo_root)
        check_ids = tuple(str(check.get("id")) for check in report.get("checks", []))
        status_check = next(
            (
                check
                for check in report.get("checks", [])
                if check.get("id") == "required_public_statuses"
            ),
            {},
        )
        statuses = status_check.get("details", {}).get("actual_statuses", {})
        return FirstProofCompatibility(
            entry_id=FIRST_PROOF_RECOMMENDED_ENTRY_ID,
            label=FIRST_PROOF_RECOMMENDED_LABEL,
            status=str(statuses.get(FIRST_PROOF_RECOMMENDED_ENTRY_ID, "unknown")),
            report_status=str(report.get("status", "unknown")),
            report_check_ids=check_ids,
        )
    except Exception as exc:
        return FirstProofCompatibility(
            entry_id=FIRST_PROOF_RECOMMENDED_ENTRY_ID,
            label=FIRST_PROOF_RECOMMENDED_LABEL,
            status="unknown",
            report_status="unavailable",
            error=str(exc),
        )


def newcomer_first_proof_content(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    tool_contract = first_proof_tool_contract(repo_root)
    compatibility = first_proof_compatibility(repo_root)
    content = FirstProofContent(
        title=(
            "First proof with flight-telemetry-project: verify AGILAB end-to-end"
        ),
        intro=(
            "Run one packaged demo with sample data and expected outputs to "
            "prove that AGILAB can activate a demo, install it, execute it, "
            "and show evidence. Do this before notebooks, cluster mode, "
            "service mode, or custom apps."
        ),
        recommended_path_id=FIRST_PROOF_RECOMMENDED_ENTRY_ID,
        recommended_path_label=FIRST_PROOF_RECOMMENDED_LABEL,
        actionable_route_ids=(FIRST_PROOF_RECOMMENDED_ENTRY_ID,),
        documented_route_ids=DOCUMENTED_ROUTE_IDS,
        compatibility_status=compatibility.status,
        compatibility_report_status=compatibility.report_status,
        proof_command_labels=tool_contract.command_labels,
        target_seconds=tool_contract.target_seconds,
        cli_command=tool_contract.cli_command,
        run_manifest_filename=_load_run_manifest_module().RUN_MANIFEST_FILENAME,
        steps=(
            (
                "DEMO",
                "Activate the packaged `flight_telemetry_project` demo in place.",
            ),
            (
                "ORCHESTRATE",
                "Keep cluster, benchmark, and service options off. Click `INSTALL`, then `EXECUTE`.",
            ),
            ("ANALYSIS", "Open the default built-in view and confirm generated evidence is visible."),
        ),
        success_criteria=(
            "A visible `ANALYSIS` result opens for the built-in flight-telemetry project.",
            "`INSTALL` and `EXECUTE` finish without an error.",
            "`run_manifest.json` and generated files appear under `~/log/execute/flight_telemetry/`.",
        ),
        links=(
            ("Quick start", "https://thalesgroup.github.io/agilab/quick-start.html"),
            ("Newcomer guide", "https://thalesgroup.github.io/agilab/newcomer-guide.html"),
            ("Compatibility matrix", "https://thalesgroup.github.io/agilab/compatibility-matrix.html"),
            ("Flight-telemetry project guide", "https://thalesgroup.github.io/agilab/flight-telemetry-project.html"),
        ),
    )
    return content.as_dict()


def _resolve_installed_first_proof_project() -> Path | None:
    try:
        from agi_env.app_provider_registry import resolve_installed_app_project
    except Exception:
        return None

    try:
        project = resolve_installed_app_project(FIRST_PROOF_PROJECT)
    except Exception:
        return None
    if project is None:
        return None

    try:
        resolved = Path(project).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return resolved if (resolved / "pyproject.toml").is_file() else None


def newcomer_first_proof_project_path(env: Any, repo_root: Path = REPO_ROOT) -> Path | None:
    candidates: list[Path] = []
    try:
        apps_path = Path(getattr(env, "apps_path", "")).expanduser()
    except (TypeError, ValueError, RuntimeError):
        apps_path = Path()
    if str(apps_path):
        candidates.extend(
            [
                apps_path / FIRST_PROOF_PROJECT,
                apps_path / "builtin" / FIRST_PROOF_PROJECT,
            ]
        )

    candidates.append(repo_root / "src" / "agilab" / "apps" / "builtin" / FIRST_PROOF_PROJECT)
    installed_project = _resolve_installed_first_proof_project()
    if installed_project is not None:
        candidates.append(installed_project)
    candidates.append(Path(__file__).resolve().parent / "apps" / "builtin" / FIRST_PROOF_PROJECT)

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            return resolved
    return None


def first_proof_output_dir(env: Any) -> Path:
    log_root = Path(getattr(env, "AGILAB_LOG_ABS", Path.home() / "log")).expanduser()
    return log_root / "execute" / "flight"


def first_proof_run_manifest_path(output_dir: Path) -> Path:
    run_manifest = _load_run_manifest_module()
    return run_manifest.run_manifest_path(output_dir)


def load_first_proof_run_manifest(output_dir: Path) -> tuple[Any | None, str | None]:
    run_manifest = _load_run_manifest_module()
    return run_manifest.try_load_run_manifest(first_proof_run_manifest_path(output_dir))


def first_proof_compatibility_report_command(manifest_path: Path) -> str:
    quoted_path = shlex.quote(str(manifest_path.expanduser()))
    return COMPATIBILITY_REPORT_COMMAND.format(manifest_path=quoted_path)


def _manifest_validation_rows(manifest: Any | None) -> tuple[dict[str, Any], ...]:
    if manifest is None:
        return ()
    rows = [
        {
            "label": str(validation.label),
            "status": str(validation.status),
            "summary": str(validation.summary),
            "required": validation.label in FIRST_PROOF_REQUIRED_VALIDATIONS,
        }
        for validation in manifest.validations
    ]
    recorded_labels = {row["label"] for row in rows}
    rows.extend(
        {
            "label": label,
            "status": "missing",
            "summary": "Required first-proof validation was not recorded.",
            "required": True,
        }
        for label in FIRST_PROOF_REQUIRED_VALIDATIONS
        if label not in recorded_labels
    )
    return tuple(rows)


def _first_proof_manifest_passed(run_manifest_module: Any, manifest: Any | None) -> bool:
    if manifest is None:
        return False
    validation_statuses = {
        str(validation.label): str(validation.status)
        for validation in manifest.validations
    }
    target = manifest.timing.target_seconds
    return (
        manifest.path_id == FIRST_PROOF_RECOMMENDED_ENTRY_ID
        and run_manifest_module.manifest_passed(manifest)
        and all(validation_statuses.get(label) == "pass" for label in FIRST_PROOF_REQUIRED_VALIDATIONS)
        and target is not None
        and manifest.timing.duration_seconds <= target
    )


def _first_proof_remediation(
    *,
    manifest: Any | None,
    manifest_error: str | None,
    manifest_path: Path,
    manifest_passed: bool,
    validation_rows: tuple[dict[str, Any], ...],
    visible_outputs: tuple[Path, ...],
) -> dict[str, Any]:
    evidence_command = first_proof_compatibility_report_command(manifest_path)
    base_commands = (FIRST_PROOF_CLI_COMMAND, evidence_command)
    if manifest_passed:
        return {
            "status": "passed",
            "title": "First-proof evidence is valid.",
            "actions": (
                "Use the compatibility report command when you need to attach this manifest as evidence.",
                "Continue with another built-in demo only after this path stays green.",
            ),
            "links": REMEDIATION_LINKS,
            "evidence_commands": base_commands,
        }

    if manifest is None:
        if manifest_error and manifest_error != "missing":
            return {
                "status": "invalid",
                "title": "Run manifest exists but cannot be parsed.",
                "actions": (
                    f"Open `{manifest_path}` and fix or remove the malformed JSON.",
                    "Rerun the first-proof JSON command so AGILAB rewrites the manifest.",
                    "Run the compatibility report command to confirm the manifest loads.",
                ),
                "links": REMEDIATION_LINKS,
                "evidence_commands": base_commands,
            }
        if visible_outputs:
            return {
                "status": "missing_manifest_with_outputs",
                "title": "Generated outputs exist, but the manifest is missing.",
                "actions": (
                    "Rerun the first-proof JSON command to create the portable run manifest.",
                    "Keep the active app on `flight_telemetry_project`; do not switch routes yet.",
                    "Run the compatibility report command after the manifest appears.",
                ),
                "links": REMEDIATION_LINKS,
                "evidence_commands": base_commands,
            }
        return {
            "status": "missing",
            "title": "No first-proof run manifest yet.",
            "actions": (
                "In the UI: select the demo, then open the run page and click INSTALL and EXECUTE.",
                "Or run the first-proof JSON command from the repository root.",
                "Run the compatibility report command after `run_manifest.json` appears.",
            ),
            "links": REMEDIATION_LINKS,
            "evidence_commands": base_commands,
        }

    issues: list[str] = []
    if manifest.path_id != FIRST_PROOF_RECOMMENDED_ENTRY_ID:
        issues.append(
            f"path_id is `{manifest.path_id}`, expected `{FIRST_PROOF_RECOMMENDED_ENTRY_ID}`"
        )
    if manifest.status != "pass":
        issues.append(f"manifest status is `{manifest.status}`")
    failed_rows = [row for row in validation_rows if row["status"] != "pass"]
    if failed_rows:
        issue_summary = ", ".join(f"{row['label']}={row['status']}" for row in failed_rows)
        issues.append(f"validation issue(s): {issue_summary}")
    target = manifest.timing.target_seconds
    if target is None:
        issues.append("target_seconds is missing")
    elif manifest.timing.duration_seconds > target:
        issues.append(f"duration {manifest.timing.duration_seconds:.2f}s exceeds target {target:.2f}s")

    return {
        "status": "failing",
        "title": "Run manifest found, but the first proof is not green.",
        "actions": (
            "Fix the manifest issue(s): " + "; ".join(issues or ("unknown manifest failure",)),
            "Rerun the first-proof JSON command from the repository root.",
            "Run the compatibility report command to verify the evidence-backed status.",
        ),
        "links": REMEDIATION_LINKS,
        "evidence_commands": base_commands,
    }


def list_first_proof_outputs(output_dir: Path) -> tuple[Path, ...]:
    if not output_dir.exists():
        return ()
    run_manifest = _load_run_manifest_module()
    outputs: list[Path] = []
    for child in sorted(output_dir.iterdir(), key=lambda item: item.name):
        if child.name.startswith("."):
            continue
        if child.name == run_manifest.RUN_MANIFEST_FILENAME:
            continue
        if child.is_file() and child.suffix == ".py" and child.name.startswith(FIRST_PROOF_HELPER_SCRIPT_PREFIXES):
            continue
        outputs.append(child)
    return tuple(outputs)


def _active_app_name(env: Any) -> str:
    raw_value = str(getattr(env, "app", "") or "")
    if "/" in raw_value or "\\" in raw_value:
        return Path(raw_value).name
    return raw_value


def newcomer_first_proof_state(env: Any, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    content = newcomer_first_proof_content(repo_root)
    project_path = newcomer_first_proof_project_path(env, repo_root)
    active_app_name = _active_app_name(env)
    output_dir = first_proof_output_dir(env)
    run_manifest_path = first_proof_run_manifest_path(output_dir)
    run_manifest_module = _load_run_manifest_module()
    run_manifest, run_manifest_error = load_first_proof_run_manifest(output_dir)
    run_manifest_loaded = run_manifest is not None
    validation_rows = _manifest_validation_rows(run_manifest)
    visible_outputs = list_first_proof_outputs(output_dir)
    run_manifest_passed = _first_proof_manifest_passed(run_manifest_module, run_manifest)
    run_manifest_status = str(getattr(run_manifest, "status", "missing" if run_manifest_error == "missing" else "invalid"))
    run_manifest_summary = (
        run_manifest_module.manifest_summary(run_manifest)
        if run_manifest is not None
        else {}
    )
    remediation = _first_proof_remediation(
        manifest=run_manifest,
        manifest_error=run_manifest_error,
        manifest_path=run_manifest_path,
        manifest_passed=run_manifest_passed,
        validation_rows=validation_rows,
        visible_outputs=visible_outputs,
    )
    helper_scripts_present = all(
        (output_dir / script_name).exists()
        for script_name in (
            "AGI_install_flight_telemetry.py",
            "AGI_run_flight_telemetry.py",
        )
    )
    current_app_matches = active_app_name == FIRST_PROOF_PROJECT

    if project_path is None:
        next_step = (
            "Fix the app list first. The built-in flight-telemetry project "
            "(`flight_telemetry_project`) is missing."
        )
    elif not current_app_matches:
        next_step = "Select the built-in flight-telemetry demo (`flight_telemetry_project`) from this page."
    elif not run_manifest_loaded and not visible_outputs:
        next_step = "Go to `ORCHESTRATE`. Click INSTALL, then EXECUTE."
    elif not run_manifest_loaded:
        next_step = "Generate `run_manifest.json` with the first-proof JSON command."
    elif run_manifest_loaded and not run_manifest_passed:
        next_step = "Run manifest found but not passing. Follow the remediation checklist."
    else:
        next_step = "First proof done. Now you can try another demo."

    state = FirstProofWizardState(
        content=content,
        compatibility_slice=content["recommended_path_label"],
        compatibility_status=content["compatibility_status"],
        compatibility_report_status=content["compatibility_report_status"],
        recommended_path_id=content["recommended_path_id"],
        recommended_path_label=content["recommended_path_label"],
        actionable_route_ids=tuple(content["actionable_route_ids"]),
        documented_route_ids=tuple(content["documented_route_ids"]),
        proof_command_labels=tuple(content["proof_command_labels"]),
        target_seconds=float(content["target_seconds"]),
        cli_command=str(content["cli_command"]),
        project_path=project_path,
        project_available=project_path is not None,
        active_app_name=active_app_name,
        current_app_matches=current_app_matches,
        output_dir=output_dir,
        run_manifest_path=run_manifest_path,
        run_manifest_loaded=run_manifest_loaded,
        run_manifest_status=run_manifest_status,
        run_manifest_passed=run_manifest_passed,
        run_manifest_summary=run_manifest_summary,
        run_manifest_validation_rows=validation_rows,
        run_manifest_error=None if run_manifest_error == "missing" else run_manifest_error,
        remediation_status=str(remediation["status"]),
        remediation_title=str(remediation["title"]),
        remediation_actions=tuple(str(action) for action in remediation["actions"]),
        remediation_links=tuple((str(label), str(url)) for label, url in remediation["links"]),
        evidence_commands=tuple(str(command) for command in remediation["evidence_commands"]),
        helper_scripts_present=helper_scripts_present,
        visible_outputs=visible_outputs,
        run_output_detected=run_manifest_passed or bool(visible_outputs),
        next_step=next_step,
        diagnostics={
            "tool_command_count": len(content["proof_command_labels"]),
            "recommended_project": FIRST_PROOF_PROJECT,
            "run_manifest_filename": content["run_manifest_filename"],
        },
    )
    return state.as_dict()
