"""Typed registry for reusable Workflow snippet candidates."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from agi_env.app_provider_registry import app_name_aliases
from agi_env.snippet_contract import is_generated_agi_snippet, is_supported_snippet_api


SNIPPET_REGISTRY_SCHEMA = "agilab.snippet_registry.v1"


@dataclass(frozen=True, slots=True)
class SnippetCandidateSpec:
    """Resolved metadata for one reusable Workflow snippet candidate."""

    path: Path
    source: str = "discovered"
    schema: str = SNIPPET_REGISTRY_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            object.__setattr__(self, "path", Path(self.path))
        normalized_source = str(self.source).strip()
        if not normalized_source:
            raise ValueError("Snippet candidate source must be non-empty")
        object.__setattr__(self, "source", normalized_source)

    @property
    def base_label(self) -> str:
        """Return the default display label before duplicate disambiguation."""

        return self.path.name

    def as_row(self) -> dict[str, str]:
        """Return a stable row for diagnostics and documentation."""

        return {
            "schema": self.schema,
            "label": self.base_label,
            "path": self.path.as_posix(),
            "source": self.source,
        }


class SnippetCandidateRegistry:
    """Immutable registry for Workflow snippet candidates and stale generated snippets."""

    def __init__(
        self,
        candidates: Iterable[SnippetCandidateSpec] = (),
        *,
        stale_snippets: Iterable[Path] = (),
    ) -> None:
        self._candidates = tuple(
            sorted(candidates, key=lambda candidate: (candidate.path.name.casefold(), str(candidate.path).casefold()))
        )
        self._stale_snippets = tuple(stale_snippets)

    def __iter__(self) -> Iterator[SnippetCandidateSpec]:
        return iter(self._candidates)

    def __len__(self) -> int:
        return len(self._candidates)

    @property
    def candidates(self) -> tuple[SnippetCandidateSpec, ...]:
        """Return candidates in deterministic display order."""

        return self._candidates

    @property
    def stale_snippets(self) -> tuple[Path, ...]:
        """Return generated snippets rejected because their snippet API is stale."""

        return self._stale_snippets

    def paths(self) -> tuple[Path, ...]:
        """Return candidate paths in deterministic display order."""

        return tuple(candidate.path for candidate in self._candidates)

    def as_option_map(self) -> dict[str, Path]:
        """Return a Streamlit selectbox label-to-path mapping with stable duplicate labels."""

        option_map: dict[str, Path] = {}
        for candidate in self._candidates:
            path = candidate.path
            base_label = path.name
            label = base_label
            if label in option_map:
                parent_name = path.parent.name or str(path.parent)
                label = f"{base_label} ({parent_name})"
                idx = 2
                while label in option_map:
                    label = f"{base_label} ({parent_name} #{idx})"
                    idx += 1
            option_map[label] = path
        return option_map

    def as_rows(self) -> list[dict[str, str]]:
        """Return registry rows suitable for rendering as a table."""

        return [candidate.as_row() for candidate in self._candidates]


def discover_pipeline_snippets(
    *,
    stages_file: Path,
    app_name: str,
    explicit_snippet: str | Path | None = None,
    safe_service_template: str | Path | None = None,
    runenv_root: str | Path | None = None,
    app_settings_file: str | Path | None = None,
) -> SnippetCandidateRegistry:
    """Discover reusable snippet files for the WORKFLOW page."""

    discovered: list[SnippetCandidateSpec] = []
    stale_snippets: list[Path] = []
    seen: set[str] = set()

    def add_candidate(candidate: str | Path | None, *, source: str) -> None:
        path = _usable_python_file(candidate)
        if path is None:
            return
        unique_key = _unique_path_key(path)
        if unique_key in seen:
            return
        seen.add(unique_key)
        if not _is_current_or_non_agi_snippet(path, stale_snippets):
            return
        discovered.append(SnippetCandidateSpec(path=path, source=source))

    add_candidate(explicit_snippet, source="session_state")
    add_candidate(Path(stages_file).parent / "AGI_run.py", source="lab_run")
    add_candidate(safe_service_template, source="safe_service_template")

    for runenv_snippet in _runenv_snippet_candidates(
        runenv_root=runenv_root,
        app_settings_file=app_settings_file,
        app_name=app_name,
    ):
        add_candidate(runenv_snippet, source="runenv")

    return SnippetCandidateRegistry(discovered, stale_snippets=stale_snippets)


def _runenv_snippet_candidates(
    *,
    runenv_root: str | Path | None,
    app_settings_file: str | Path | None,
    app_name: str,
) -> Iterator[Path]:
    """Yield short-lived, app-scoped runenv snippets aligned with app settings."""

    if not runenv_root:
        return
    try:
        runenv_path = Path(runenv_root).expanduser()
        app_settings_mtime = _mtime(app_settings_file)
        expected_suffixes = tuple(f"_{name}.py" for name in _snippet_app_names(app_name))
        if not expected_suffixes:
            return
        for py_file in sorted(runenv_path.glob("AGI_*.py")):
            if not py_file.name.endswith(expected_suffixes):
                continue
            if app_settings_mtime is not None:
                try:
                    if py_file.stat().st_mtime < app_settings_mtime:
                        continue
                except OSError:
                    continue
            yield py_file
    except (OSError, RuntimeError, TypeError, ValueError):
        return


def _snippet_app_names(app_name: str) -> tuple[str, ...]:
    """Return project and slug forms used by generated AGI snippet filenames."""

    normalized = Path(str(app_name or "").strip()).name.replace("-", "_")
    if not normalized:
        return ()
    names: list[str] = []

    def add(name: str) -> None:
        if name and name not in names:
            names.append(name)

    for alias in app_name_aliases(normalized):
        add(alias)
    return tuple(names)


def _usable_python_file(candidate: str | Path | None) -> Path | None:
    if candidate is None:
        return None
    path = _coerce_path(candidate)
    if path is None:
        return None
    try:
        if not path.exists() or not path.is_file() or path.suffix.lower() != ".py":
            return None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return path


def _coerce_path(candidate: str | Path) -> Path | None:
    try:
        return Path(candidate).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        try:
            return Path(str(candidate)).expanduser()
        except (OSError, RuntimeError, TypeError, ValueError):
            return None


def _unique_path_key(path: Path) -> str:
    try:
        return str(path.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return str(path)


def _is_current_or_non_agi_snippet(path: Path, stale_snippets: list[Path]) -> bool:
    try:
        code = path.read_text(encoding="utf-8")
    except (AttributeError, OSError, RuntimeError, TypeError, UnicodeDecodeError, ValueError):
        return True
    if not is_generated_agi_snippet(code):
        return True
    if is_supported_snippet_api(code):
        return True
    stale_snippets.append(path)
    return False


def _mtime(path: str | Path | None) -> float | None:
    if path is None:
        return None
    try:
        candidate = Path(path)
        return candidate.stat().st_mtime if candidate.exists() else None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
