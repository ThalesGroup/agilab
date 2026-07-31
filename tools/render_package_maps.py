# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Render curated package-map SVGs for the AGILAB docs.

``pyreverse`` package diagrams do not survive these packages: ``agi_env`` alone
holds 55 modules, so the generated view is either a wall of disconnected boxes
with clipped labels or, when regenerated today, a 15k-wide canvas. This module
renders a curated responsibility map instead: the *groups* are hand-declared and
stable, while every member list is read from the filesystem. Compatibility shims
are collapsed into their canonical module responsibility; any other duplicate
module stem fails validation instead of disappearing silently.

Run ``python tools/render_package_maps.py --check`` to fail on drift, or
``--apply`` to rewrite the checked-in SVGs.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "source" / "diagrams"

# Visual language shared with the hand-authored docs diagrams
# (agi-core-overview.svg, agilab_global_architecture.svg).
FONT = "Arial, Helvetica, sans-serif"
INK = "#0e223f"
MUTED = "#536984"
LANE = "#70849c"
CARD_STROKE = "#0e223f"
PALETTE = ("#d9f0ff", "#e3dcff", "#ffe8ac", "#d6f6d8", "#ffdbe2", "#e6ecf5")

# Arial advance width is ~0.5em averaged over mixed case; module names are
# lowercase with underscores, which run slightly wider. Budget 0.55em so the
# text-overflow defect class this file exists to fix cannot come back.
CHAR_EM = 0.55


@dataclass(frozen=True)
class Group:
    """One curated responsibility group inside a package."""

    title: str
    #: Filename globs, relative to the package source root.
    patterns: tuple[str, ...]
    #: Short description rendered under the group title.
    note: str = ""
    members: tuple[str, ...] = field(default=(), compare=False)


@dataclass(frozen=True)
class PackageMap:
    """A rendered figure: one package, several curated groups."""

    slug: str
    title: str
    subtitle: str
    source_root: Path
    groups: tuple[Group, ...]
    columns: int = 3
    #: Globs selecting every module this figure is responsible for. Anything
    #: matched here but absent from a group fails ``--check``, so a new module
    #: cannot slip into the package without appearing on the map.
    scope: tuple[str, ...] = ("**/*.py",)


def uncovered_modules(package: PackageMap) -> tuple[str, ...]:
    """Modules inside the figure's scope that no curated group claims."""

    in_scope: list[str] = []
    for pattern in package.scope:
        for path in sorted(package.source_root.glob(pattern)):
            if path.suffix != ".py" or path.stem == "__init__":
                continue
            if "__pycache__" in path.parts or "build" in path.parts:
                continue
            if path.stem not in in_scope:
                in_scope.append(path.stem)
    claimed = {member for group in _resolved_groups(package) for member in group.members}
    return tuple(name for name in in_scope if name not in claimed)


def _scoped_python_paths(package: PackageMap) -> tuple[Path, ...]:
    paths: list[Path] = []
    for pattern in package.scope:
        for path in sorted(package.source_root.glob(pattern)):
            if path.suffix != ".py" or path.stem == "__init__":
                continue
            if "__pycache__" in path.parts or "build" in path.parts:
                continue
            if path not in paths:
                paths.append(path)
    return tuple(paths)


def _is_compatibility_shim(path: Path) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "activate_compat_module" in source and "_TARGET_MODULE" in source


def ambiguous_module_stems(package: PackageMap) -> dict[str, tuple[str, ...]]:
    """Return duplicate stems that are not one canonical module plus shims."""

    by_stem: dict[str, list[Path]] = {}
    for path in _scoped_python_paths(package):
        by_stem.setdefault(path.stem, []).append(path)

    ambiguous: dict[str, tuple[str, ...]] = {}
    for stem, paths in by_stem.items():
        if len(paths) < 2:
            continue
        canonical = [path for path in paths if not _is_compatibility_shim(path)]
        if len(canonical) == 1:
            continue
        ambiguous[stem] = tuple(
            path.relative_to(package.source_root).as_posix() for path in paths
        )
    return ambiguous


def _module_names(source_root: Path, patterns: tuple[str, ...]) -> tuple[str, ...]:
    names: list[str] = []
    for pattern in patterns:
        for path in sorted(source_root.glob(pattern)):
            if path.suffix != ".py" or path.stem == "__init__":
                continue
            if path.stem not in names:
                names.append(path.stem)
    return tuple(names)


def _resolved_groups(package: PackageMap) -> tuple[Group, ...]:
    """Resolve every group's members, keeping the groups disjoint.

    Patterns are allowed to overlap for readability, so a module is claimed by
    the first group that matches it. Without this the rendered counts would
    double-count shared modules and the footer total would exceed the package.
    """

    claimed: set[str] = set()
    resolved: list[Group] = []
    for group in package.groups:
        members = tuple(
            name
            for name in _module_names(package.source_root, group.patterns)
            if name not in claimed
        )
        claimed.update(members)
        resolved.append(
            Group(
                title=group.title,
                patterns=group.patterns,
                note=group.note,
                members=members,
            )
        )
    return tuple(resolved)


def _fits(text: str, *, font_size: float, width: float) -> bool:
    return len(text) * font_size * CHAR_EM <= width


def _wrap(items: tuple[str, ...], *, font_size: float, width: float, max_lines: int) -> list[str]:
    """Pack ``items`` into comma-separated lines that provably fit ``width``."""

    lines: list[str] = []
    current = ""
    remaining = list(items)
    while remaining:
        candidate = f"{current}, {remaining[0]}" if current else remaining[0]
        if _fits(candidate, font_size=font_size, width=width):
            current = candidate
            remaining.pop(0)
            continue
        if not current:
            # A single member wider than the card: keep it whole on its own line
            # rather than truncating into an unreadable stub.
            current = remaining.pop(0)
        lines.append(current)
        current = ""
        if len(lines) == max_lines - 1 and remaining:
            tail = f"+{len(remaining)} more"
            lines.append(tail)
            return lines
    if current:
        lines.append(current)
    return lines[:max_lines]


def _wrap_words(text: str, *, font_size: float, width: float, max_lines: int = 2) -> list[str]:
    """Wrap prose on word boundaries so a note can never cross its card edge."""

    if not text:
        return []
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if _fits(candidate, font_size=font_size, width=width):
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_svg(package: PackageMap) -> str:
    groups = _resolved_groups(package)
    total = sum(len(group.members) for group in groups)

    columns = package.columns
    rows = (len(groups) + columns - 1) // columns
    margin = 46
    gutter = 22
    card_w = 316
    header_h = 104
    footer_h = 52
    body_w = card_w - 40  # card padding left+right

    footer_text = (
        f"{total} logical module{'s' if total != 1 else ''} · compatibility shims collapsed · "
        "groups: tools/render_package_maps.py"
    )

    # Size every card to the tallest content in the family so peers keep a
    # shared bottom without leaving dead space under sparse groups.
    wrapped = {
        group.title: _wrap(group.members, font_size=13, width=body_w, max_lines=4)
        for group in groups
    }
    notes = {
        group.title: _wrap_words(group.note, font_size=13, width=body_w)
        for group in groups
    }
    body_lines = max((len(lines) for lines in wrapped.values()), default=1)
    note_lines = max((len(lines) for lines in notes.values()), default=0)
    card_h = 38 + note_lines * 20 + 4 * bool(note_lines) + body_lines * 19 + 18

    # A narrow grid must still hold its own header and footer: size the canvas
    # from the widest text run, not from the card grid alone.
    grid_w = margin * 2 + card_w * columns + gutter * (columns - 1)
    text_w = margin * 2 + max(
        len(package.title) * 24 * CHAR_EM,
        len(package.subtitle) * 15 * CHAR_EM,
        len(footer_text) * 13 * CHAR_EM,
    )
    width = int(max(grid_w, text_w))
    height = header_h + rows * card_h + (rows - 1) * gutter + footer_h + margin
    out: list[str] = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">'
    )
    out.append(f"  <title id=\"title\">{_escape(package.title)}</title>")
    out.append(f"  <desc id=\"desc\">{_escape(package.subtitle)}</desc>")
    out.append("  <defs>")
    out.append("    <style>")
    out.append(f"      text {{ font-family: {FONT}; fill: {INK}; }}")
    out.append("      .title { font-size: 24px; font-weight: 700; }")
    out.append(f"      .subtitle {{ font-size: 15px; fill: {MUTED}; }}")
    out.append("      .card-title { font-size: 17px; font-weight: 700; }")
    out.append(f"      .card-note {{ font-size: 13px; fill: {MUTED}; }}")
    out.append("      .member { font-size: 13px; }")
    out.append(f"      .count {{ font-size: 12px; font-weight: 700; fill: {LANE}; }}")
    out.append(f"      .footer {{ font-size: 13px; fill: {MUTED}; }}")
    out.append("    </style>")
    out.append('    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">')
    out.append('      <stop offset="0%" stop-color="#f8fbff" />')
    out.append('      <stop offset="100%" stop-color="#edf3fb" />')
    out.append("    </linearGradient>")
    out.append("  </defs>")
    out.append(f'  <rect width="{width}" height="{height}" fill="url(#bg)" rx="28" ry="28" />')
    out.append(f'  <text class="title" x="{margin}" y="52">{_escape(package.title)}</text>')
    out.append(f'  <text class="subtitle" x="{margin}" y="80">{_escape(package.subtitle)}</text>')

    for index, group in enumerate(groups):
        col = index % columns
        row = index // columns
        x = margin + col * (card_w + gutter)
        y = header_h + row * (card_h + gutter)
        fill = PALETTE[index % len(PALETTE)]
        out.append(
            f'  <rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="18" ry="18" '
            f'fill="{fill}" stroke="{CARD_STROKE}" stroke-width="2" />'
        )
        out.append(
            f'  <text class="card-title" x="{x + 20}" y="{y + 30}">{_escape(group.title)}</text>'
        )
        count_label = f"{len(group.members)} module" + ("s" if len(group.members) != 1 else "")
        out.append(
            f'  <text class="count" x="{x + card_w - 20}" y="{y + 30}" '
            f'text-anchor="end">{count_label}</text>'
        )
        text_y = y + 52
        for line in notes[group.title]:
            out.append(f'  <text class="card-note" x="{x + 20}" y="{text_y}">{_escape(line)}</text>')
            text_y += 20
        if notes[group.title]:
            text_y += 4
        for line in wrapped[group.title]:
            out.append(f'  <text class="member" x="{x + 20}" y="{text_y}">{_escape(line)}</text>')
            text_y += 19

    footer_y = header_h + rows * card_h + (rows - 1) * gutter + 32
    out.append(f'  <text class="footer" x="{margin}" y="{footer_y}">{_escape(footer_text)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


AGI_ENV_SRC = REPO_ROOT / "src/agilab/core/agi-env/src/agi_env"
AGI_DISTRIBUTOR_SRC = REPO_ROOT / "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor"
MINIMAL_APP_SRC = REPO_ROOT / "src/agilab/apps/builtin/minimal_app_project/src"
FLIGHT_TELEMETRY_SRC = REPO_ROOT / "src/agilab/apps/builtin/flight_telemetry_project/src"


PACKAGE_MAPS: tuple[PackageMap, ...] = (
    PackageMap(
        slug="packages_agi_env",
        title="agi-env module map",
        subtitle="Environment resolution for paths, app contracts, UI helpers, and worker staging.",
        source_root=AGI_ENV_SRC,
        groups=(
            Group("Core environment", ("agi_env*.py", "defaults.py", "env_*.py", "compat/*.py"),
                  "AgiEnv construction and configuration."),
            Group("Paths and share", ("share_*.py", "package_layout_support.py", "windows_link_support.py",
                                      "repository_support.py", "runtime/atomic_write_support.py",
                                      "runtime/destructive_path_support.py", "import_layout_support.py",
                                      "runtime/import_layout_support.py"),
                  "Local, cluster, and share-root resolution."),
            Group("App contract", ("app_*.py", "project_*.py", "connector_registry.py",
                                   "project/*.py"),
                  "Settings, arguments, providers, cloning."),
            Group("UI helpers", ("pagelib*.py", "ui_*.py", "streamlit_args.py", "_optional_ui.py",
                                 "ui/*.py"),
                  "Streamlit page and widget support."),
            Group("Runtime and workers", ("worker_*.py", "host_runtime_support.py", "runtime_bootstrap_support.py",
                                          "process_support.py", "execution_support.py", "bootstrap_support.py",
                                          "installation_support.py", "cython_build_config.py",
                                          "runtime/*.py"),
                  "Worker packaging and process execution."),
            Group("Support services", ("agi_logger.py", "credential_store_support.py", "mlflow_store.py",
                                       "data_archive_support.py", "source_analysis*.py", "hook_support.py",
                                       "snippet_contract.py", "content_renamer_support.py",
                                       "rename_gitignore_support.py"),
                  "Logging, secrets, tracking, analysis."),
        ),
    ),
    PackageMap(
        slug="packages_agi_distributor",
        title="agi-distributor module map",
        subtitle="Dispatch, deployment, and service lifecycle behind a single AGI.run request.",
        source_root=AGI_DISTRIBUTOR_SRC,
        groups=(
            Group("Entry and requests", ("agi_distributor.py", "cli.py", "entrypoint_support.py",
                                         "run_request_support.py", "api/*.py", "compat/*.py"),
                  "AGI facade, CLI, and request shaping."),
            Group("Deployment", ("deployment_*.py", "deployment/*.py"),
                  "Env build, install, and worker venv staging."),
            Group("Capacity and cleanup", ("background_jobs_support.py", "capacity_support.py",
                                           "cleanup_support.py"),
                  "Worker capacity and teardown."),
            Group("Runtime and transport", ("runtime_*.py", "transport_support.py", "scheduler_io_support.py",
                                            "uv_source_support.py", "runtime/*.py"),
                  "Scheduler IO and distribution modes."),
            Group("Service lifecycle", ("service_*.py", "lifecycle_guard_support.py"),
                  "Persistent workers and health gates."),
        ),
        columns=3,
    ),
    PackageMap(
        slug="packages_minimal_app",
        title="minimal_app package layout",
        subtitle="The smallest AGILAB app: a manager package, typed arguments, and a Streamlit form.",
        source_root=MINIMAL_APP_SRC,
        groups=(
            Group("Manager", ("minimal_app/minimal_app.py",), "BaseWorker subclass that builds the work plan."),
            Group("Arguments", ("minimal_app/app_args.py", "minimal_app/minimal_app_args.py"),
                  "Pydantic args and TOML round-trip."),
            Group("Argument form", ("app_args_form.py",), "Streamlit form rendered by the PROJECT page."),
        ),
        scope=("minimal_app/*.py", "app_args_form.py"),
    ),
    PackageMap(
        slug="packages_minimal_app_worker",
        title="minimal_app_worker package layout",
        subtitle="The worker ships as its own package so imports and dependencies stay isolated in ~/wenv.",
        source_root=MINIMAL_APP_SRC,
        groups=(
            Group("Worker runtime", ("minimal_app_worker/minimal_app_worker.py",),
                  "PolarsWorker subclass executing one work item."),
        ),
        columns=1,
        scope=("minimal_app_worker/*.py",),
    ),
    PackageMap(
        slug="packages_flight_telemetry",
        title="flight_telemetry package layout",
        subtitle="Manager, typed arguments, reduction contract, and the Streamlit argument form.",
        source_root=FLIGHT_TELEMETRY_SRC,
        groups=(
            Group("Manager", ("flight_telemetry/flight_telemetry.py",),
                  "Builds the two-level weighted distribution."),
            Group("Arguments", ("flight_telemetry/flight_args.py",), "Typed args with TOML persistence."),
            Group("Reduction", ("flight_telemetry/reduction.py",), "Reduce contract and summary evidence."),
            Group("Argument form", ("app_args_form.py",), "Streamlit form for the PROJECT page."),
        ),
        columns=2,
        scope=("flight_telemetry/*.py", "app_args_form.py"),
    ),
    PackageMap(
        slug="packages_flight_telemetry_worker",
        title="flight_telemetry_worker package layout",
        subtitle="A separately packaged PolarsWorker whose hot loop is compiled with Cython.",
        source_root=FLIGHT_TELEMETRY_SRC,
        groups=(
            Group("Worker runtime", ("flight_telemetry_worker/flight_telemetry_worker.py",),
                  "PolarsWorker subclass with the Cython hot loop."),
        ),
        columns=1,
        scope=("flight_telemetry_worker/*.py",),
    ),
)


def render_all(output_dir: Path) -> dict[Path, str]:
    return {output_dir / f"{package.slug}.svg": render_svg(package) for package in PACKAGE_MAPS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Fail when a checked-in figure is stale.")
    mode.add_argument("--apply", action="store_true", help="Rewrite the checked-in figures.")
    args = parser.parse_args(argv)

    output_dir = args.output_dir.expanduser().resolve()

    ambiguities = {
        package.slug: ambiguous_module_stems(package) for package in PACKAGE_MAPS
    }
    ambiguities = {slug: stems for slug, stems in ambiguities.items() if stems}
    if ambiguities:
        for slug, stems in ambiguities.items():
            for stem, paths in stems.items():
                print(
                    f"{slug}: ambiguous module stem {stem!r}: {', '.join(paths)}",
                    file=sys.stderr,
                )
        print(
            "rename the responsibility or mark one duplicate as an explicit "
            "activate_compat_module shim",
            file=sys.stderr,
        )
        return 1

    gaps = {package.slug: uncovered_modules(package) for package in PACKAGE_MAPS}
    gaps = {slug: names for slug, names in gaps.items() if names}
    if gaps:
        for slug, names in gaps.items():
            print(
                f"{slug}: {len(names)} module(s) belong to no curated group: "
                f"{', '.join(names)}",
                file=sys.stderr,
            )
        print(
            "add each module to a group in tools/render_package_maps.py so the map "
            "keeps describing the whole package",
            file=sys.stderr,
        )
        return 1

    rendered = render_all(output_dir)

    if args.apply:
        output_dir.mkdir(parents=True, exist_ok=True)
        for path, text in rendered.items():
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path}")
        return 0

    stale = [
        path
        for path, text in rendered.items()
        if not path.exists() or path.read_text(encoding="utf-8") != text
    ]
    if stale:
        for path in stale:
            print(f"stale package map: {path}", file=sys.stderr)
        print(
            "rerun `python tools/render_package_maps.py --apply` against the canonical "
            "docs checkout, then sync the public mirror",
            file=sys.stderr,
        )
        return 1
    if not args.check:
        for path in rendered:
            print(f"up to date: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
