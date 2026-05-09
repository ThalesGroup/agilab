#!/usr/bin/env python3
"""Select a fast regression pytest subset with a small genetic algorithm."""

from __future__ import annotations

import argparse
import json
import random
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

import impact_validate


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_ROOTS = (
    "test",
    "src/agilab/test",
    "src/agilab/lib/agi-gui/test",
    "src/agilab/core/test",
    "src/agilab/core/agi-env/test",
)
COMMON_TOKENS = {
    "src",
    "agilab",
    "test",
    "tests",
    "tool",
    "tools",
    "python",
    "support",
    "helper",
    "helpers",
    "page",
    "pages",
    "project",
    "agi",
    "gui",
    "lib",
    "core",
    "env",
    "state",
}


@dataclass(frozen=True)
class TestCandidate:
    path: str
    score: float
    estimated_seconds: float
    reasons: tuple[str, ...]
    required: bool = False


@dataclass(frozen=True)
class SelectionResult:
    files: tuple[str, ...]
    selected_tests: tuple[str, ...]
    required_tests: tuple[str, ...]
    estimated_seconds: float
    score: float
    budget_seconds: float
    command: tuple[str, ...]
    reasons: dict[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["files"] = list(self.files)
        payload["selected_tests"] = list(self.selected_tests)
        payload["required_tests"] = list(self.required_tests)
        payload["command"] = list(self.command)
        payload["reasons"] = {key: list(value) for key, value in self.reasons.items()}
        return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Use a deterministic genetic algorithm to choose a small pytest "
            "regression subset for the current change. This is an accelerator, "
            "not a replacement for required parity gates."
        )
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--files", nargs="+", help="Explicit repo-relative files to analyze.")
    group.add_argument("--staged", action="store_true", help="Analyze staged files.")
    parser.add_argument("--base", default="origin/main", help="Base ref for unstaged diff analysis.")
    parser.add_argument(
        "--timings",
        nargs="*",
        default=(),
        help="Optional JUnit XML or JSON timing files. Defaults to test-results/junit-*.xml when present.",
    )
    parser.add_argument("--budget-seconds", type=float, default=45.0)
    parser.add_argument("--population", type=int, default=48)
    parser.add_argument("--generations", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260505)
    parser.add_argument("--max-candidates", type=int, default=96)
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument("--print-command", action="store_true", help="Print only the selected pytest command.")
    parser.add_argument("--run", action="store_true", help="Run the selected pytest command.")
    return parser


def _git_lines(args: Sequence[str]) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def collect_changed_files(args: argparse.Namespace) -> list[str]:
    if args.files:
        return impact_validate._normalize_paths(args.files)
    if args.staged:
        return impact_validate._normalize_paths(
            _git_lines(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
        )
    tracked = _git_lines(["diff", "--name-only", "--diff-filter=ACMR", args.base])
    untracked = _git_lines(["ls-files", "--others", "--exclude-standard"])
    return impact_validate._normalize_paths([*tracked, *untracked])


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", value.lower())
        if len(token) >= 3 and token not in COMMON_TOKENS
    }


def _discover_test_files(test_roots: Sequence[str] = DEFAULT_TEST_ROOTS) -> list[str]:
    tests: list[str] = []
    seen: set[str] = set()
    for root in test_roots:
        root_path = REPO_ROOT / root
        if not root_path.exists():
            continue
        for path in sorted(root_path.rglob("test_*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel not in seen:
                tests.append(rel)
                seen.add(rel)
    return tests


def _is_shared_core_change(path: str) -> bool:
    return path.startswith(
        (
            "src/agilab/core/",
            "install.sh",
            "src/agilab/install_apps.sh",
            "src/agilab/apps/install.py",
        )
    )


def _is_gui_only_change(path: str) -> bool:
    return path.startswith(
        (
            "src/agilab/apps-pages/",
            "src/agilab/lib/",
            "src/agilab/pages/",
            "src/agilab/orchestrate_",
            "src/agilab/pipeline_",
            "src/agilab/main_page.py",
        )
    )


def _is_allowed_candidate(path: str, changed_files: Sequence[str], guessed_tests: set[str]) -> bool:
    if path in guessed_tests:
        return True
    shared_core_changed = any(_is_shared_core_change(changed) for changed in changed_files)
    gui_changed = any(_is_gui_only_change(changed) for changed in changed_files)
    if gui_changed and not shared_core_changed and path.startswith("src/agilab/core/"):
        return False
    return True


def _module_to_test_path(classname: str) -> str | None:
    module = classname.split("[", 1)[0]
    if not module:
        return None
    candidate = module.replace(".", "/") + ".py"
    if (REPO_ROOT / candidate).exists():
        return candidate
    parts = module.split(".")
    for index, part in enumerate(parts):
        if part.startswith("test_"):
            fallback = "/".join(parts[:index] + [part]) + ".py"
            if (REPO_ROOT / fallback).exists():
                return fallback
    return None


def _load_json_timings(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if all(isinstance(value, (int, float)) for value in payload.values()):
            return {str(key): float(value) for key, value in payload.items()}
        tests = payload.get("tests")
        if isinstance(tests, dict):
            return {str(key): float(value) for key, value in tests.items() if isinstance(value, (int, float))}
    return {}


def _load_junit_timings(path: Path) -> dict[str, float]:
    root = ET.parse(path).getroot()
    timings: dict[str, float] = {}
    for testcase in root.iter("testcase"):
        classname = testcase.attrib.get("classname", "")
        test_path = _module_to_test_path(classname)
        if not test_path:
            continue
        timings[test_path] = timings.get(test_path, 0.0) + float(testcase.attrib.get("time", "0") or 0)
    return timings


def _load_timing_file(path: Path) -> dict[str, float]:
    try:
        if path.suffix == ".json":
            return _load_json_timings(path)
        return _load_junit_timings(path)
    except (OSError, json.JSONDecodeError, ET.ParseError, ValueError) as exc:
        print(f"ga_regression_selector: ignoring unreadable timings {path}: {exc}", file=sys.stderr)
        return {}


def load_timings(paths: Sequence[str] = ()) -> dict[str, float]:
    timing_paths: list[Path] = []
    if paths:
        timing_paths.extend(Path(path) for path in paths)
    else:
        timing_paths.extend(sorted((REPO_ROOT / "test-results").glob("junit-*.xml")))
    timings: dict[str, float] = {}
    for raw_path in timing_paths:
        path = raw_path if raw_path.is_absolute() else REPO_ROOT / raw_path
        if not path.exists():
            continue
        loaded = _load_timing_file(path)
        for test_path, seconds in loaded.items():
            timings[test_path] = timings.get(test_path, 0.0) + seconds
    return timings


def _default_estimate(test_path: str) -> float:
    path = REPO_ROOT / test_path
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 1.0
    test_count = len(re.findall(r"^\s*def\s+test_", text, flags=re.MULTILINE))
    async_count = len(re.findall(r"^\s*async\s+def\s+test_", text, flags=re.MULTILINE))
    return max(0.25, 0.35 + (test_count + async_count) * 0.08)


def _score_test(path: str, changed_files: Sequence[str], guessed_tests: set[str]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    path_tokens = _tokens(path)

    if path in guessed_tests:
        score += 120.0
        reasons.append("direct impact match")

    changed_tokens = set().union(*(_tokens(changed) for changed in changed_files)) if changed_files else set()
    overlap = sorted(path_tokens & changed_tokens)
    if overlap:
        score += min(60.0, len(overlap) * 12.0)
        reasons.append("token overlap: " + ", ".join(overlap[:6]))

    for changed in changed_files:
        changed_path = Path(changed)
        changed_name = changed_path.stem.lower()
        if changed_name and changed_name in path.lower():
            score += 45.0
            reasons.append(f"name affinity: {changed_name}")
        if changed.startswith("src/agilab/orchestrate_") and "test_orchestrate" in path:
            score += 35.0
            reasons.append("orchestrate surface")
        if changed.startswith("src/agilab/pipeline_") and "test_pipeline" in path:
            score += 35.0
            reasons.append("pipeline surface")
        if changed.startswith("src/agilab/main_page.py") and "test_about" in path:
            score += 35.0
            reasons.append("about page surface")
        if changed.startswith("src/agilab/apps-pages/"):
            parts = changed_path.parts
            page_name = parts[3] if len(parts) > 3 else ""
            if page_name and path.startswith(f"test/test_{page_name}"):
                score += 70.0
                reasons.append(f"apps-page match: {page_name}")
        if changed.startswith("docs/source/") and (
            path in {"test/test_audit_response_docs.py", "test/test_sync_docs_source.py"}
            or "docs" in path
        ):
            score += 30.0
            reasons.append("docs surface")
        if changed.startswith(".github/workflows/") and path.endswith("_workflow.py"):
            score += 30.0
            reasons.append("workflow surface")
        if changed.startswith("badges/") or "coverage" in changed:
            if "coverage" in path or "badge" in path:
                score += 30.0
                reasons.append("coverage/badge surface")
        if changed.startswith("src/agilab/core/agi-env/") and "agi-env/test" in path:
            score += 80.0
            reasons.append("agi-env core surface")
        if changed.startswith("src/agilab/core/") and "src/agilab/core/test" in path:
            score += 50.0
            reasons.append("shared core surface")

    if not reasons:
        score += 1.0
        reasons.append("low-affinity fallback")
    return score, reasons


def build_candidates(changed_files: Sequence[str], timings: dict[str, float]) -> list[TestCandidate]:
    impact = impact_validate.analyze_paths(list(changed_files))
    guessed_tests = set(impact.guessed_tests)
    candidates: list[TestCandidate] = []
    for path in _discover_test_files():
        if not _is_allowed_candidate(path, changed_files, guessed_tests):
            continue
        score, reasons = _score_test(path, changed_files, guessed_tests)
        if score <= 1.0 and path not in guessed_tests:
            continue
        estimate = timings.get(path, _default_estimate(path))
        candidates.append(
            TestCandidate(
                path=path,
                score=score,
                estimated_seconds=max(0.05, estimate),
                reasons=tuple(dict.fromkeys(reasons)),
                required=path in guessed_tests,
            )
        )
    return sorted(candidates, key=lambda item: (-item.required, -item.score, item.estimated_seconds, item.path))


def _fitness(
    genome: Sequence[bool],
    optional: Sequence[TestCandidate],
    required: Sequence[TestCandidate],
    budget_seconds: float,
) -> float:
    selected = [*required, *(candidate for bit, candidate in zip(genome, optional) if bit)]
    score = sum(candidate.score for candidate in selected)
    seconds = sum(candidate.estimated_seconds for candidate in selected)
    penalty = max(0.0, seconds - budget_seconds) * 15.0
    size_penalty = max(0, len(selected) - 12) * 2.0
    return score - seconds * 0.35 - penalty - size_penalty


def _random_genome(length: int, rng: random.Random, density: float) -> list[bool]:
    return [rng.random() < density for _ in range(length)]


def _tournament(
    population: Sequence[list[bool]],
    fitnesses: Sequence[float],
    rng: random.Random,
    size: int = 3,
) -> list[bool]:
    contenders = [rng.randrange(len(population)) for _ in range(size)]
    winner = max(contenders, key=lambda index: fitnesses[index])
    return list(population[winner])


def select_tests(
    candidates: Sequence[TestCandidate],
    *,
    budget_seconds: float = 45.0,
    population_size: int = 48,
    generations: int = 80,
    seed: int = 20260505,
    max_candidates: int = 96,
) -> list[TestCandidate]:
    required = [candidate for candidate in candidates if candidate.required]
    optional = [candidate for candidate in candidates if not candidate.required][:max_candidates]
    if not optional:
        return sorted(required, key=lambda candidate: candidate.path)

    rng = random.Random(seed)
    population_size = max(8, population_size)
    generations = max(1, generations)
    length = len(optional)
    greedy = [False] * length
    remaining = max(0.0, budget_seconds - sum(candidate.estimated_seconds for candidate in required))
    for index, candidate in sorted(
        enumerate(optional),
        key=lambda pair: (-(pair[1].score / max(pair[1].estimated_seconds, 0.05)), pair[1].path),
    ):
        if candidate.estimated_seconds <= remaining:
            greedy[index] = True
            remaining -= candidate.estimated_seconds

    population: list[list[bool]] = [
        [False] * length,
        greedy,
        [index < min(8, length) for index in range(length)],
    ]
    while len(population) < population_size:
        density = rng.choice((0.08, 0.16, 0.24, 0.32))
        population.append(_random_genome(length, rng, density))

    for _ in range(generations):
        fitnesses = [_fitness(genome, optional, required, budget_seconds) for genome in population]
        ranked = sorted(range(len(population)), key=lambda index: fitnesses[index], reverse=True)
        next_population = [list(population[ranked[0]]), list(population[ranked[1]])]
        while len(next_population) < population_size:
            left = _tournament(population, fitnesses, rng)
            right = _tournament(population, fitnesses, rng)
            cut = rng.randrange(1, length) if length > 1 else 1
            child = left[:cut] + right[cut:]
            mutation_rate = 1.0 / max(8, length)
            for index in range(length):
                if rng.random() < mutation_rate:
                    child[index] = not child[index]
            next_population.append(child)
        population = next_population

    fitnesses = [_fitness(genome, optional, required, budget_seconds) for genome in population]
    best = population[max(range(len(population)), key=lambda index: fitnesses[index])]
    selected = [*required, *(candidate for bit, candidate in zip(best, optional) if bit)]
    selected = _prune_to_budget(selected, budget_seconds)
    return sorted(selected, key=lambda candidate: (-candidate.required, -candidate.score, candidate.path))


def _prune_to_budget(selected: Sequence[TestCandidate], budget_seconds: float) -> list[TestCandidate]:
    kept = list(selected)
    required_seconds = sum(candidate.estimated_seconds for candidate in kept if candidate.required)
    if required_seconds >= budget_seconds:
        return kept
    while sum(candidate.estimated_seconds for candidate in kept) > budget_seconds:
        optional = [candidate for candidate in kept if not candidate.required]
        if not optional:
            break
        weakest = min(
            optional,
            key=lambda candidate: (
                candidate.score / max(candidate.estimated_seconds, 0.05),
                candidate.score,
                -candidate.estimated_seconds,
                candidate.path,
            ),
        )
        kept.remove(weakest)
    return kept


def build_selection(
    files: Sequence[str],
    *,
    timings: dict[str, float] | None = None,
    budget_seconds: float = 45.0,
    population: int = 48,
    generations: int = 80,
    seed: int = 20260505,
    max_candidates: int = 96,
) -> SelectionResult:
    timing_map = timings or {}
    candidates = build_candidates(files, timing_map)
    selected = select_tests(
        candidates,
        budget_seconds=budget_seconds,
        population_size=population,
        generations=generations,
        seed=seed,
        max_candidates=max_candidates,
    )
    selected_tests = tuple(candidate.path for candidate in selected)
    command = ()
    if selected_tests:
        command = (
            "uv",
            "--preview-features",
            "extra-build-dependencies",
            "run",
            "pytest",
            "-q",
            "-o",
            "addopts=",
            *selected_tests,
        )
    return SelectionResult(
        files=tuple(files),
        selected_tests=selected_tests,
        required_tests=tuple(candidate.path for candidate in selected if candidate.required),
        estimated_seconds=round(sum(candidate.estimated_seconds for candidate in selected), 3),
        score=round(sum(candidate.score for candidate in selected), 3),
        budget_seconds=budget_seconds,
        command=command,
        reasons={candidate.path: candidate.reasons for candidate in selected},
    )


def _render_human(result: SelectionResult) -> str:
    lines = [
        f"GA regression selection: {len(result.selected_tests)} test file(s), "
        f"estimated {result.estimated_seconds:.2f}s / budget {result.budget_seconds:.2f}s",
    ]
    if result.files:
        lines.append("Changed files:")
        lines.extend(f"- {path}" for path in result.files)
    if result.selected_tests:
        lines.append("Selected tests:")
        for path in result.selected_tests:
            reason = "; ".join(result.reasons.get(path, ()))
            lines.append(f"- {path} ({reason})")
        lines.append("Command:")
        lines.append(shlex.join(result.command))
    else:
        lines.append("No matching regression tests found.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        files = collect_changed_files(args)
    except RuntimeError as exc:
        parser.exit(2, f"ga_regression_selector: {exc}\n")

    timings = load_timings(args.timings)
    result = build_selection(
        files,
        timings=timings,
        budget_seconds=args.budget_seconds,
        population=args.population,
        generations=args.generations,
        seed=args.seed,
        max_candidates=args.max_candidates,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2), flush=True)
    elif args.print_command:
        print(shlex.join(result.command), flush=True)
    else:
        print(_render_human(result), flush=True)
    if args.run and result.selected_tests:
        completed = subprocess.run(result.command, cwd=REPO_ROOT, check=False)
        return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
