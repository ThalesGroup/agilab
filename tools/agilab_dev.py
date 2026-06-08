#!/usr/bin/env python3
"""Shortcuts for the most common AGILAB developer commands."""

from __future__ import annotations

import shlex
import subprocess
import sys
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
UV_RUN = ("uv", "--preview-features", "extra-build-dependencies", "run")
DEFAULT_DEV_UV_PROJECT_ENVIRONMENT = ROOT / ".venv-dev"
DEV_UV_PROJECT_ENVIRONMENT_ENV = "AGILAB_DEV_UV_PROJECT_ENVIRONMENT"
DEV_LOG_DIR = ROOT / "reports" / "dev-logs"
DEFAULT_SUMMARY_LINES = 40
SIGNAL_WORDS = (
    "error",
    "failed",
    "failure",
    "traceback",
    "exception",
    "fatal",
    "panic",
    "denied",
    "missing",
    "not found",
    "timeout",
    "warning",
    "assert",
)
DEFAULT_LINT_TARGETS = (
    "src/agilab/security",
    "src/agilab/evidence",
    "src/agilab/agent_runtime",
    "src/agilab/compat",
    "src/agilab/core/agi-env/src/agi_env/ui/pagelib_selection_support.py",
    "tools/agilab_audit.py",
    "tools/agilab_dev.py",
    "src/agilab/core/agi-env/test/test_pagelib_selection_support.py",
    "test/test_agilab_audit.py",
    "test/test_agilab_dev_shortcuts.py",
    "test/test_agilab_module_layout.py",
)
DEFAULT_UNDEFINED_NAME_LINT_TARGETS = (
    "src/agilab/core/agi-env/src/agi_env/ui/pagelib.py",
    "src/agilab/core/agi-env/test/test_pagelib.py",
)


def _uv_python(*args: str) -> list[str]:
    return [*UV_RUN, "python", *args]


def _uv_dev(*args: str) -> list[str]:
    return [*UV_RUN, "--extra", "dev", *args]


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV_RUN_RECURSION_DEPTH", None)
    env.setdefault(
        "UV_PROJECT_ENVIRONMENT",
        env.get(DEV_UV_PROJECT_ENVIRONMENT_ENV, str(DEFAULT_DEV_UV_PROJECT_ENVIRONMENT)),
    )
    return env


def _split_leading_values(
    args: Sequence[str], *, command_name: str
) -> tuple[list[str], list[str]]:
    values: list[str] = []
    rest: list[str] = []
    for index, item in enumerate(args):
        if item.startswith("-"):
            rest = list(args[index:])
            break
        values.append(item)
    else:
        rest = []
    if not values:
        raise SystemExit(f"{command_name}: at least one value is required")
    return values, rest


def _pop_option_value(args: Sequence[str], index: int, option: str) -> tuple[str, int]:
    item = args[index]
    if item.startswith(f"{option}="):
        return item.split("=", 1)[1], index + 1
    if index + 1 >= len(args):
        raise SystemExit(f"{option}: value is required")
    return args[index + 1], index + 2


def _split_release_args(
    args: Sequence[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Split local release shortcut options from impact-validation options."""

    impact_args: list[str] = []
    release_plan_args: list[str] = []
    release_policy_args: list[str] = []
    preflight_args: list[str] = []
    index = 0
    while index < len(args):
        item = args[index]
        if item == "--release-mode" or item.startswith("--release-mode="):
            value, index = _pop_option_value(args, index, "--release-mode")
            release_policy_args.extend(["--release-mode", value])
            continue
        if item == "--impact-base-ref" or item.startswith("--impact-base-ref="):
            value, index = _pop_option_value(args, index, "--impact-base-ref")
            release_plan_args.extend(
                ["--skip-existing-pypi", "--impact-base-ref", value]
            )
            release_policy_args.extend(["--impact-base-ref", value])
            continue
        if item == "--packages" or item.startswith("--packages="):
            value, index = _pop_option_value(args, index, "--packages")
            release_plan_args.extend(["--packages", value])
            release_policy_args.extend(["--packages", value])
            preflight_args.extend(["--package", value])
            continue
        if item == "--roles" or item.startswith("--roles="):
            value, index = _pop_option_value(args, index, "--roles")
            release_plan_args.extend(["--roles", value])
            release_policy_args.extend(["--roles", value])
            preflight_args.extend(["--role", value])
            continue
        impact_args.append(item)
        index += 1
    if not impact_args:
        impact_args = ["--staged"]
    return impact_args, release_plan_args, release_policy_args, preflight_args


def _parse_positive_int(value: str, *, option: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise SystemExit(f"{option}: value must be an integer") from exc
    if parsed <= 0:
        raise SystemExit(f"{option}: value must be greater than zero")
    return parsed


def _pop_global_option(args: list[str], option: str) -> str:
    for index, item in enumerate(args):
        if item == option:
            if index + 1 >= len(args):
                raise SystemExit(f"{option}: value is required")
            value = args[index + 1]
            del args[index : index + 2]
            return value
        if item.startswith(f"{option}="):
            args.pop(index)
            return item.split("=", 1)[1]
    raise SystemExit(f"{option}: value is required")


def _is_signal_line(line: str) -> bool:
    lower = line.lower()
    if any(word in lower for word in SIGNAL_WORDS):
        return True
    stripped = line.lstrip()
    return stripped.startswith(("E   ", "E\t", "FAILED ", "ERROR "))


def _dedupe_keep_order(lines: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        kept.append(line)
    return kept


def _compact_log_path(command: Sequence[str], output: str) -> Path:
    DEV_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    family = Path(command[0]).name if command else "command"
    digest = sha256(
        ("\0".join(command) + "\n" + output).encode("utf-8", "replace")
    ).hexdigest()[:12]
    return DEV_LOG_DIR / f"{timestamp}-{family}-{digest}.log"


def _write_compact_log(command: Sequence[str], output: str) -> Path:
    path = _compact_log_path(command, output)
    path.write_text(output, encoding="utf-8", errors="replace")
    return path


def _summary_lines(
    output: str, *, max_lines: int, returncode: int
) -> tuple[list[str], int, int]:
    lines = output.splitlines()
    if not lines:
        return [], 0, 0
    signals = [
        (index + 1, line) for index, line in enumerate(lines) if _is_signal_line(line)
    ]
    signal_budget = max(1, max_lines * 3 // 4)
    tail_budget = max(1, max_lines - min(len(signals), signal_budget))

    selected: list[str] = []
    if len(signals) > signal_budget and signal_budget > 1:
        signal_sample = [signals[0], *signals[-(signal_budget - 1) :]]
    else:
        signal_sample = signals[-signal_budget:]
    for line_number, line in signal_sample:
        selected.append(f"{line_number}: {line}")

    if returncode != 0:
        tail = [line for line in lines[-tail_budget:] if line.strip()]
        if tail:
            if selected:
                selected.append("-- tail --")
            selected.extend(tail)

    selected = _dedupe_keep_order(selected)[:max_lines]
    omitted = max(len(lines) - len(selected), 0)
    return selected, len(signals), omitted


def _print_compact_result(
    command: Sequence[str],
    *,
    returncode: int,
    output: str,
    max_lines: int,
) -> None:
    log_path = _write_compact_log(command, output)
    lines = output.splitlines()
    selected, signal_count, omitted = _summary_lines(
        output, max_lines=max_lines, returncode=returncode
    )
    rel_log = log_path.relative_to(ROOT) if log_path.is_relative_to(ROOT) else log_path
    status = "ok" if returncode == 0 else "failed"
    print(
        f"./dev compact-output: {status} exit={returncode} lines={len(lines)} "
        f"signals={signal_count} omitted={omitted} log={rel_log}",
        file=sys.stderr,
        flush=True,
    )
    for line in selected:
        print(line, file=sys.stderr)
    if omitted > 0 and selected:
        print(
            f"... omitted {omitted} line(s); inspect {rel_log} for full output",
            file=sys.stderr,
        )


def _run_compact(command: Sequence[str], *, max_lines: int) -> int:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    _print_compact_result(
        command,
        returncode=completed.returncode,
        output=completed.stdout or "",
        max_lines=max_lines,
    )
    return completed.returncode


def planned_commands(argv: Sequence[str]) -> list[list[str]]:
    if not argv or argv[0] in {"help", "-h", "--help"}:
        return [["./dev", "help"]]

    command = argv[0]
    args = list(argv[1:])

    if command == "impact":
        forwarded = args or ["--staged"]
        return [_uv_python("tools/impact_validate.py", *forwarded)]

    if command in {"bugfix", "fix"}:
        forwarded = args or ["--staged"]
        helper_args = list(forwarded)
        if "--run" not in helper_args:
            helper_args.append("--run")
        return [_uv_python("tools/bugfix_validate.py", *helper_args)]

    if command == "test":
        return [
            [
                *UV_RUN,
                "pytest",
                "-q",
                "-o",
                "addopts=",
                "--import-mode=importlib",
                *args,
            ]
        ]

    if command == "lint":
        if args:
            return [_uv_dev("ruff", "check", *args)]
        return [
            _uv_dev("ruff", "check", *DEFAULT_LINT_TARGETS),
            _uv_dev(
                "ruff",
                "check",
                "--select",
                "F821,E9",
                *DEFAULT_UNDEFINED_NAME_LINT_TARGETS,
            ),
        ]

    if command == "ruff":
        return [_uv_dev("ruff", *(args or ["check"]))]

    if command in {"regress", "ga-regress"}:
        forwarded = args or ["--staged", "--run"]
        return [_uv_python("tools/ga_regression_selector.py", *forwarded)]

    if command in {"robust", "robustness"}:
        return [_uv_python("tools/robustness_matrix.py", *args)]

    if command in {"parallel-stage", "parallel"}:
        return [_uv_python("tools/parallel_stage.py", *args)]

    if command in {"app-contracts", "apps-contracts"}:
        return [_uv_python("tools/app_contract_matrix.py", *args)]

    if command in {"builtin-app-tests", "built-in-app-tests"}:
        return [_uv_python("tools/builtin_app_tests.py", *args)]

    if command in {"maintenance", "maintain"}:
        return [_uv_python("tools/maintenance_dashboard.py", *args)]

    if command in {"memory", "maint-memory"}:
        return [_uv_python("tools/maintenance_memory.py", *args)]

    if command == "audit":
        return [_uv_python("tools/agilab_audit.py", *args)]

    if command in {"audit-quality", "audit-preflight"}:
        forwarded = (
            ["--preflight"] if command == "audit-preflight" and not args else args
        )
        if command == "audit-quality" and not forwarded:
            forwarded = ["--preflight"]
        return [_uv_python("tools/audit_quality_evaluator.py", *forwarded)]

    if command in {"flow", "profile"}:
        profiles, extras = _split_leading_values(args, command_name=command)
        profile_args: list[str] = []
        for profile in profiles:
            profile_args.extend(["--profile", profile])
        return [_uv_python("tools/workflow_parity.py", *profile_args, *extras)]

    if command in {"ui-flow", "ui-impact", "ui-robots"}:
        return [
            _uv_python("tools/workflow_parity.py", "--select-ui-robot-profiles", *args)
        ]

    if command in {"perf-startup", "startup-perf"}:
        defaults = [
            "--scenario",
            "orchestrate-execute-import",
            "--scenario",
            "pipeline-ai-import",
            "--scenario",
            "runtime-distribution-import",
            "--scenario",
            "base-worker-import",
            "--repeats",
            "1",
            "--warmups",
            "0",
        ]
        return [_uv_python("tools/perf_smoke.py", *(args or defaults))]

    if command in {"worker-reuse", "worker-env-reuse"}:
        return [_uv_python("tools/worker_env_reuse.py", *args)]

    if command in {"typing", "ty"}:
        return [_uv_python("tools/workflow_parity.py", "--profile", "ty-typing", *args)]

    if command in {"release", "pre-release"}:
        impact_args, release_plan_args, release_policy_args, preflight_args = (
            _split_release_args(args)
        )
        return [
            _uv_python("tools/agilab_audit.py", "--strict"),
            _uv_python("tools/impact_validate.py", *impact_args),
            _uv_python(
                "tools/release_plan.py",
                "--check-workflow",
                ".github/workflows/pypi-publish.yaml",
                *release_plan_args,
            ),
            _uv_python(
                "tools/pypi_release_version_policy.py",
                "--skip-existing-pypi",
                *release_policy_args,
            ),
            _uv_python("tools/pypi_project_preflight.py", *preflight_args),
            _uv_python(
                "tools/pypi_trusted_publisher_contract.py",
                "--check-workflow",
                ".github/workflows/pypi-publish.yaml",
            ),
            _uv_dev("ruff", "--version"),
            _uv_python("tools/app_contract_matrix.py", "--quiet"),
            _uv_python(
                "tools/workflow_parity.py",
                "--profile",
                "dependency-policy",
                "--profile",
                "shared-core-typing",
                "--profile",
                "docs",
            ),
            _uv_python(
                "tools/coverage_badge_guard.py",
                "--changed-only",
                "--require-fresh-xml",
            ),
        ]

    if command in {"badge", "guard"}:
        defaults = ["--changed-only", "--require-fresh-xml"]
        return [_uv_python("tools/coverage_badge_guard.py", *defaults, *args)]

    if command == "docs":
        return [
            _uv_python("tools/sync_docs_source.py", "--apply", "--delete"),
            _uv_python("tools/sync_docs_source.py", "--verify-stamp"),
        ]

    if command == "clean":
        return [_uv_python("tools/clean_local_artifacts.py", *args)]

    if command in {"scope", "scope-guard"}:
        return [_uv_python("tools/worktree_scope_guard.py", *args)]

    if command in {"task-worktree", "worktree"}:
        if not args:
            raise SystemExit(f"{command}: branch name is required")
        return [_uv_python("tools/task_worktree.py", *args)]

    if command == "skills":
        skills, extras = _split_leading_values(args, command_name=command)
        return [
            ["python3", "tools/sync_agent_skills.py", "--skills", *skills, *extras],
            [
                "python3",
                "tools/codex_skills.py",
                "--root",
                ".codex/skills",
                "validate",
                "--strict",
            ],
            ["python3", "tools/codex_skills.py", "--root", ".codex/skills", "generate"],
            ["python3", "tools/agent_skill_catalog.py", "--apply"],
            ["python3", "tools/generate_skill_badges.py"],
            [
                "python3",
                "tools/agent_skill_quality_guard.py",
                "--roots",
                ".claude/skills",
                ".codex/skills",
                "--fail-on",
                "high",
            ],
            [
                "python3",
                "tools/skill_security_scan.py",
                "--roots",
                ".claude/skills",
                ".codex/skills",
                "--fail-on",
                "critical",
            ],
        ]

    raise SystemExit(f"unknown shortcut: {command}")


def _usage() -> str:
    return """Usage:
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] impact [impact_validate args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] bugfix [changed-file args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] test [pytest args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] lint|ruff [ruff args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] regress [ga_regression_selector args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] robust [robustness_matrix args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] parallel-stage [parallel_stage args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] app-contracts [app_contract_matrix args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] builtin-app-tests [builtin_app_tests args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] maintenance [maintenance_dashboard args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] memory [maintenance_memory args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] audit [agilab_audit args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] audit-quality [audit_quality_evaluator args|audit.md]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] audit-preflight
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] flow|profile <profile> [profile...] [workflow args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] ui-flow [workflow-parity changed-file args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] perf-startup [perf_smoke args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] worker-reuse [worker_env_reuse args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] typing [workflow-parity options]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] release [--release-mode MODE] [--impact-base-ref REF] [impact_validate args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] badge|guard [coverage_badge_guard args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] docs
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] clean [--apply]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] scope [worktree_scope_guard args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] task-worktree <branch> [task_worktree args]
  ./dev [--print-only] [--raw-output|--compact-output] [--summary-lines N] skills <skill> [skill...]

Output:
  Default execution captures stdout/stderr, writes the full stream under reports/dev-logs/,
  and prints a bounded signal summary to stderr. Use --raw-output, or set
  AGILAB_DEV_OUTPUT=raw, for the old streaming behavior.

High-frequency mappings:
  impact    -> Analyze changed files and list the required local validations; defaults to --staged.
  bugfix    -> Run impact triage, then run the GA-selected fast regression subset; defaults to --staged.
  test      -> Run targeted pytest with -q and repo-wide coverage disabled, while keeping all extra pytest arguments.
  lint      -> Run Ruff through the repo dev extra on the default clean guardrail slice; pass paths for custom scope.
  regress   -> Use the GA regression selector on staged files and run the selected pytest subset.
  robust    -> Run the P0 robustness matrix of fail-closed bad-state scenarios.
  parallel-stage -> Create or validate a function + split rule + reducer contract for parallel execution.
  app-contracts -> Check built-in app, PyPI package, app catalog, and public-doc alignment.
  builtin-app-tests -> Run built-in app tests inside each app's own uv project environment.
  maintenance -> Report extension contracts, ADRs, docs drift, app/package contracts, evidence docs, release friction, TODO hotspots, generated artifacts, and coverage signals.
  memory    -> Check path-scoped maintenance memory notes for source drift.
  audit     -> Audit local AGILAB worktrees, release proof, docs mirror, PyPI projects, and latest release truth.
  audit-quality -> Score a Markdown AGILAB audit, or print the deep-audit preflight when no file is provided.
  audit-preflight -> Print the mandatory architecture-foundation preflight for deep AGILAB audits.
  flow      -> Run one or more workflow_parity profiles with repeated --profile flags. Cache-safe profiles reuse successful local results automatically.
  ui-flow   -> Select the minimal UI robot workflow profiles from changed files.
  perf-startup -> Measure startup-sensitive AGILAB import paths with perf_smoke.
  worker-reuse -> Compare worker manifest fingerprints against a deployed-env reuse marker.
  typing    -> Run the forward shared-core ty typing profile. Mypy remains the curated temporary release guard under shared-core-typing.
  release   -> Run local release guards: AGILAB audit/review, impact, generated PyPI plan, release cadence, PyPI project preflight, trusted publisher contract, Ruff availability, docs, dependency policy, typing, and badge freshness. Pass --release-mode hotfix and --impact-base-ref <tag> for same-day hotfixes.
  badge     -> Run the explicit release/pre-release coverage badge freshness guard.
  docs      -> Sync docs from the canonical docs checkout and verify the mirror stamp.
  clean     -> Dry-run cleanup of ignored local build/lib duplicate-source trees; pass --apply to remove them.
  scope     -> Group dirty tracked and untracked files by review scope and fail when unrelated scopes are mixed.
  task-worktree -> Create a clean sibling git worktree for an isolated task branch.
  skills    -> Sync repo skills from Claude to Codex, validate, regenerate indexes/catalog/badges, and scan skill quality/security risk.
"""


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    print_only = False
    raw_output = os.environ.get("AGILAB_DEV_OUTPUT", "").strip().lower() == "raw"
    summary_lines = _parse_positive_int(
        os.environ.get("AGILAB_DEV_SUMMARY_LINES", str(DEFAULT_SUMMARY_LINES)),
        option="AGILAB_DEV_SUMMARY_LINES",
    )
    if "--print-only" in args:
        print_only = True
        args = [item for item in args if item != "--print-only"]
    if "--raw-output" in args:
        raw_output = True
        args = [item for item in args if item != "--raw-output"]
    if "--compact-output" in args:
        raw_output = False
        args = [item for item in args if item != "--compact-output"]
    if "--summary-lines" in args or any(
        item.startswith("--summary-lines=") for item in args
    ):
        summary_lines = _parse_positive_int(
            _pop_global_option(args, "--summary-lines"),
            option="--summary-lines",
        )

    if not args or args[0] in {"help", "-h", "--help"}:
        print(_usage())
        return 0

    commands = planned_commands(args)
    for command in commands:
        output = sys.stdout if print_only else sys.stderr
        print(shlex.join(command), file=output, flush=True)
        if print_only:
            continue
        if raw_output:
            completed = subprocess.run(command, cwd=ROOT, env=_subprocess_env())
            if completed.returncode:
                return completed.returncode
        else:
            returncode = _run_compact(command, max_lines=summary_lines)
            if returncode:
                return returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
