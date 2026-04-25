"""Model the in-product newcomer first-proof wizard."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
FIRST_PROOF_PROJECT = "flight_project"
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
DOCUMENTED_ROUTE_IDS = ("notebook-quickstart", "published-package-route")


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
        title="Start here",
        intro=(
            "Goal: make the validated flight_project source-checkout proof work "
            "on your computer before branching into other routes."
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
        steps=(
            ("PROJECT", "Go to `PROJECT`. Choose `flight_project`."),
            ("ORCHESTRATE", "Go to `ORCHESTRATE`. Click INSTALL, then EXECUTE."),
            ("ANALYSIS", "Go to `ANALYSIS`. Open the default built-in view."),
        ),
        success_criteria=(
            "`flight_project` runs without error.",
            "Generated files are created under `~/log/execute/flight/`.",
            "A visible `ANALYSIS` result opens for `flight_project`.",
        ),
        links=(
            ("Quick start", "https://thalesgroup.github.io/agilab/quick-start.html"),
            ("Newcomer guide", "https://thalesgroup.github.io/agilab/newcomer-guide.html"),
            ("Compatibility matrix", "https://thalesgroup.github.io/agilab/compatibility-matrix.html"),
            ("Flight project guide", "https://thalesgroup.github.io/agilab/flight-project.html"),
        ),
    )
    return content.as_dict()


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


def list_first_proof_outputs(output_dir: Path) -> tuple[Path, ...]:
    if not output_dir.exists():
        return ()
    outputs: list[Path] = []
    for child in sorted(output_dir.iterdir(), key=lambda item: item.name):
        if child.name.startswith("."):
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
    visible_outputs = list_first_proof_outputs(output_dir)
    helper_scripts_present = all(
        (output_dir / script_name).exists()
        for script_name in (
            "AGI_install_flight.py",
            "AGI_run_flight.py",
        )
    )
    current_app_matches = active_app_name == FIRST_PROOF_PROJECT

    if project_path is None:
        next_step = "Fix the app list first. `flight_project` is missing."
    elif not current_app_matches:
        next_step = "Go to `PROJECT`. Choose `flight_project`."
    elif not visible_outputs:
        next_step = "Go to `ORCHESTRATE`. Click INSTALL, then EXECUTE."
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
        helper_scripts_present=helper_scripts_present,
        visible_outputs=visible_outputs,
        run_output_detected=bool(visible_outputs),
        next_step=next_step,
        diagnostics={
            "tool_command_count": len(content["proof_command_labels"]),
            "recommended_project": FIRST_PROOF_PROJECT,
        },
    )
    return state.as_dict()
