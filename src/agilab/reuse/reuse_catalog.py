"""Reuse suggestions for AGILAB views and app projects."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import tomllib
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "agilab.reuse_suggestions.v1"
CATALOG_SCHEMA = "agilab.reuse_catalog.v1"
DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[1] / "resources" / "reuse_catalog.toml"
VALID_KINDS = frozenset({"page", "project"})
VALID_REUSE_DECISIONS = frozenset({"reuse", "extend", "clone", "new"})
REQUIRED_FIELDS = frozenset(
    {
        "id",
        "title",
        "purpose",
        "when_to_use",
        "tags",
        "reuse_policy",
        "reuse_decision",
        "reuse_rationale",
    }
)
REQUIRED_LIST_FIELDS = frozenset({"tags"})
KIND_LIST_FIELDS = {"page": "inputs", "project": "artifacts"}
APPS_PAGES_REL = Path("src/agilab/apps-pages")
BUILTIN_PROJECTS_REL = Path("src/agilab/apps/builtin")
DEFAULT_CHANGED_SIMILARITY_THRESHOLD = 8
TEXT_FILE_NAMES = (
    "README.md",
    "pyproject.toml",
    "app_settings.toml",
    "notebook_import_views.toml",
    "notebook_export.toml",
    "lab_stages.toml",
    "pipeline_view.dot",
)
MAX_SOURCE_CHARS = 120_000


@dataclass(frozen=True)
class ReuseEntry:
    kind: str
    id: str
    title: str
    purpose: str
    when_to_use: str
    tags: tuple[str, ...]
    package: str = ""
    inputs: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    reuse_policy: str = ""
    reuse_decision: str = ""
    reuse_rationale: str = ""
    checked_against: tuple[str, ...] = ()

    def search_text(self) -> str:
        parts = [
            self.kind,
            self.id,
            self.title,
            self.purpose,
            self.when_to_use,
            self.package,
            self.reuse_policy,
            self.reuse_decision,
            self.reuse_rationale,
            *self.tags,
            *self.inputs,
            *self.artifacts,
            *self.checked_against,
        ]
        return " ".join(part for part in parts if part)

    def as_dict(self, *, score: int | None = None, matched_terms: Sequence[str] = ()) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "package": self.package,
            "purpose": self.purpose,
            "when_to_use": self.when_to_use,
            "tags": list(self.tags),
            "inputs": list(self.inputs),
            "artifacts": list(self.artifacts),
            "reuse_policy": self.reuse_policy,
            "reuse_decision": self.reuse_decision,
            "reuse_rationale": self.reuse_rationale,
            "checked_against": list(self.checked_against),
        }
        if score is not None:
            payload["score"] = score
        if matched_terms:
            payload["matched_terms"] = list(matched_terms)
        return payload


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _catalog_path(path: Path | None = None) -> Path:
    return (path or DEFAULT_CATALOG_PATH).expanduser().resolve()


def load_catalog(path: Path | None = None) -> tuple[ReuseEntry, ...]:
    catalog_path = _catalog_path(path)
    if not catalog_path.is_file():
        return ()
    with catalog_path.open("rb") as stream:
        payload = tomllib.load(stream)

    entries: list[ReuseEntry] = []
    for kind in sorted(VALID_KINDS):
        rows = payload.get(kind, [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            entries.append(
                ReuseEntry(
                    kind=kind,
                    id=_clean_text(row.get("id")),
                    title=_clean_text(row.get("title")),
                    purpose=_clean_text(row.get("purpose")),
                    when_to_use=_clean_text(row.get("when_to_use")),
                    tags=_string_list(row.get("tags")),
                    package=_clean_text(row.get("package")),
                    inputs=_string_list(row.get("inputs")),
                    artifacts=_string_list(row.get("artifacts")),
                    reuse_policy=_clean_text(row.get("reuse_policy")),
                    reuse_decision=_clean_text(row.get("reuse_decision")),
                    reuse_rationale=_clean_text(row.get("reuse_rationale")),
                    checked_against=_string_list(row.get("checked_against")),
                )
            )
    return tuple(entry for entry in entries if entry.id)


def discover_repo_surfaces(repo_root: Path) -> dict[str, set[str]]:
    root = repo_root.expanduser().resolve()
    pages: set[str] = set()
    pages_root = root / APPS_PAGES_REL
    if pages_root.is_dir():
        for path in pages_root.iterdir():
            if path.is_dir() and (path / "pyproject.toml").is_file():
                pages.add(path.name)
            elif path.is_file() and path.suffix == ".py" and not path.name.startswith("_"):
                pages.add(path.stem)

    projects: set[str] = set()
    projects_root = root / BUILTIN_PROJECTS_REL
    if projects_root.is_dir():
        for path in projects_root.iterdir():
            if path.is_dir() and path.name.endswith("_project"):
                projects.add(path.name)
    return {"page": pages, "project": projects}


def _normalize_token(token: str) -> str:
    token = token.casefold()
    if len(token) > 4 and token.endswith("ies"):
        token = token[:-3] + "y"
    elif len(token) > 3 and token.endswith("s"):
        token = token[:-1]
    return token


def _tokens(text: str) -> tuple[str, ...]:
    raw = re.findall(r"[a-zA-Z0-9]+", text)
    return tuple(
        token
        for token in (_normalize_token(item) for item in raw)
        if len(token) >= 2
    )


def _notebook_text(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    parts: list[str] = [path.name]
    metadata = payload.get("metadata", {})
    if isinstance(metadata, Mapping):
        parts.append(json.dumps(metadata, sort_keys=True))
    for cell in payload.get("cells", []):
        if not isinstance(cell, Mapping):
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            parts.extend(str(item) for item in source)
        else:
            parts.append(str(source))
        outputs = cell.get("outputs", [])
        if isinstance(outputs, list):
            for output in outputs:
                if isinstance(output, Mapping):
                    parts.append(json.dumps(output.get("data", {}), sort_keys=True))
    return "\n".join(parts)


def text_from_path(path: Path) -> str:
    source = path.expanduser()
    if source.is_file():
        if source.suffix.casefold() == ".ipynb":
            return _notebook_text(source)
        return source.read_text(encoding="utf-8", errors="ignore")[:MAX_SOURCE_CHARS]
    if not source.is_dir():
        return str(path)

    parts: list[str] = [source.name]
    for name in TEXT_FILE_NAMES:
        for candidate in (source / name, source / "src" / name):
            if candidate.is_file():
                parts.append(candidate.read_text(encoding="utf-8", errors="ignore"))
    for pyproject in sorted(source.glob("src/*/pyproject.toml"))[:6]:
        parts.append(pyproject.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)[:MAX_SOURCE_CHARS]


def _entry_score(entry: ReuseEntry, query_tokens: set[str]) -> tuple[int, tuple[str, ...]]:
    entry_tokens = set(_tokens(entry.search_text()))
    title_tokens = set(_tokens(f"{entry.id} {entry.title}"))
    tag_tokens = set(_tokens(" ".join(entry.tags)))
    contract_tokens = set(_tokens(" ".join((*entry.inputs, *entry.artifacts))))
    matches = sorted(query_tokens & entry_tokens)
    score = len(matches)
    score += 3 * len(query_tokens & tag_tokens)
    score += 2 * len(query_tokens & contract_tokens)
    score += 2 * len(query_tokens & title_tokens)
    if query_tokens and entry.id.replace("_", " ") in " ".join(sorted(query_tokens)):
        score += 3
    return score, tuple(matches)


def suggest_reuse(
    query: str = "",
    *,
    kind: str = "all",
    from_path: Path | None = None,
    catalog_path: Path | None = None,
    limit: int = 5,
    min_score: int = 1,
) -> tuple[dict[str, Any], ...]:
    query_parts = [query]
    if from_path is not None:
        query_parts.append(text_from_path(from_path))
    query_text = "\n".join(part for part in query_parts if part)
    query_tokens = set(_tokens(query_text))
    if not query_tokens:
        return ()

    entries = load_catalog(catalog_path)
    if kind != "all":
        entries = tuple(entry for entry in entries if entry.kind == kind)

    scored: list[tuple[int, ReuseEntry, tuple[str, ...]]] = []
    for entry in entries:
        score, matched_terms = _entry_score(entry, query_tokens)
        if score >= min_score:
            scored.append((score, entry, matched_terms))
    scored.sort(key=lambda item: (-item[0], item[1].kind, item[1].id))
    return tuple(
        entry.as_dict(score=score, matched_terms=matched_terms)
        for score, entry, matched_terms in scored[: max(0, limit)]
    )


def build_suggestion_report(
    query: str = "",
    *,
    kind: str = "all",
    from_path: Path | None = None,
    catalog_path: Path | None = None,
    limit: int = 5,
    min_score: int = 1,
) -> dict[str, Any]:
    matches = suggest_reuse(
        query,
        kind=kind,
        from_path=from_path,
        catalog_path=catalog_path,
        limit=limit,
        min_score=min_score,
    )
    return {
        "schema": SCHEMA,
        "status": "match" if matches else "no_match",
        "kind": kind,
        "query": query,
        "source_path": str(from_path) if from_path is not None else "",
        "catalog_path": str(_catalog_path(catalog_path)),
        "match_count": len(matches),
        "matches": list(matches),
    }


def validate_catalog(
    *,
    catalog_path: Path | None = None,
    expected_pages: Iterable[str] = (),
    expected_projects: Iterable[str] = (),
) -> dict[str, Any]:
    path = _catalog_path(catalog_path)
    errors: dict[str, Any] = {}
    try:
        entries = load_catalog(path)
    except Exception as exc:
        return {
            "schema": "agilab.reuse_catalog_validation.v1",
            "status": "fail",
            "catalog_path": str(path),
            "errors": {"load": str(exc)},
        }

    by_kind: dict[str, dict[str, ReuseEntry]] = {kind: {} for kind in VALID_KINDS}
    duplicates: list[str] = []
    missing_fields: dict[str, list[str]] = {}
    invalid_decisions: dict[str, str] = {}
    missing_checked_against: dict[str, str] = {}
    for entry in entries:
        key = f"{entry.kind}:{entry.id}"
        if entry.id in by_kind[entry.kind]:
            duplicates.append(key)
        by_kind[entry.kind][entry.id] = entry
        missing = [
            field
            for field in sorted(REQUIRED_FIELDS)
            if not getattr(entry, field)
        ]
        list_field = KIND_LIST_FIELDS[entry.kind]
        if not getattr(entry, list_field):
            missing.append(list_field)
        for field in REQUIRED_LIST_FIELDS:
            if not getattr(entry, field):
                missing.append(field)
        if missing:
            missing_fields[key] = missing
        if entry.reuse_decision and entry.reuse_decision not in VALID_REUSE_DECISIONS:
            invalid_decisions[key] = entry.reuse_decision
        if entry.reuse_decision in {"extend", "clone", "new"} and not entry.checked_against:
            missing_checked_against[key] = entry.reuse_decision

    expected_by_kind = {
        "page": set(expected_pages),
        "project": set(expected_projects),
    }
    coverage_errors: dict[str, Any] = {}
    for kind_name, expected in expected_by_kind.items():
        actual = set(by_kind[kind_name])
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing or extra:
            coverage_errors[kind_name] = {"missing": missing, "extra": extra}

    if duplicates:
        errors["duplicate_ids"] = sorted(duplicates)
    if missing_fields:
        errors["missing_fields"] = missing_fields
    if invalid_decisions:
        errors["invalid_reuse_decisions"] = invalid_decisions
    if missing_checked_against:
        errors["missing_checked_against"] = missing_checked_against
    if coverage_errors:
        errors["coverage"] = coverage_errors

    return {
        "schema": "agilab.reuse_catalog_validation.v1",
        "status": "pass" if not errors else "fail",
        "catalog_path": str(path),
        "summary": {
            "page_count": len(by_kind["page"]),
            "project_count": len(by_kind["project"]),
        },
        "errors": errors,
    }


def _surface_from_changed_path(path: Path) -> tuple[str, str] | None:
    parts = path.parts
    page_parts = APPS_PAGES_REL.parts
    project_parts = BUILTIN_PROJECTS_REL.parts
    if len(parts) > len(page_parts) and parts[: len(page_parts)] == page_parts:
        name = parts[len(page_parts)]
        if name == "templates":
            return None
        if name.endswith(".py"):
            return ("page", Path(name).stem)
        return ("page", name)
    if len(parts) > len(project_parts) and parts[: len(project_parts)] == project_parts:
        name = parts[len(project_parts)]
        if name.endswith("_project"):
            return ("project", name)
    return None


def _surface_path(repo_root: Path, kind: str, surface_id: str) -> Path:
    if kind == "page":
        directory = repo_root / APPS_PAGES_REL / surface_id
        if directory.exists():
            return directory
        return repo_root / APPS_PAGES_REL / f"{surface_id}.py"
    return repo_root / BUILTIN_PROJECTS_REL / surface_id


def git_changed_paths(repo_root: Path, *, base_ref: str = "HEAD") -> tuple[str, ...]:
    commands = (
        ("git", "diff", "--name-only", "--diff-filter=ACMR", base_ref, "--"),
        ("git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "--"),
        ("git", "ls-files", "--others", "--exclude-standard"),
    )
    paths: set[str] = set()
    for command in commands:
        try:
            result = subprocess.run(
                command,
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        paths.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return tuple(sorted(paths))


def _entry_acknowledges(entry: ReuseEntry, match: Mapping[str, Any]) -> bool:
    acknowledged = set(entry.checked_against)
    match_id = str(match.get("id", "") or "")
    match_kind = str(match.get("kind", "") or "")
    return match_id in acknowledged or f"{match_kind}:{match_id}" in acknowledged


def validate_changed_surfaces(
    *,
    repo_root: Path,
    changed_paths: Iterable[str | Path],
    catalog_path: Path | None = None,
    similarity_threshold: int = DEFAULT_CHANGED_SIMILARITY_THRESHOLD,
) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    repo_surfaces = discover_repo_surfaces(root)
    catalog_validation = validate_catalog(
        catalog_path=catalog_path,
        expected_pages=repo_surfaces["page"],
        expected_projects=repo_surfaces["project"],
    )
    entries = load_catalog(catalog_path)
    by_key = {(entry.kind, entry.id): entry for entry in entries}
    changed_path_items = tuple(str(path) for path in changed_paths)
    changed_surfaces = sorted(
        {
            surface
            for raw_path in changed_path_items
            for surface in [_surface_from_changed_path(Path(raw_path))]
            if surface is not None
        }
    )

    missing_catalog: list[str] = []
    unacknowledged_similarity: dict[str, list[dict[str, Any]]] = {}
    for kind, surface_id in changed_surfaces:
        entry = by_key.get((kind, surface_id))
        surface_key = f"{kind}:{surface_id}"
        if entry is None:
            missing_catalog.append(surface_key)
            continue
        source_path = _surface_path(root, kind, surface_id)
        if not source_path.exists():
            continue
        matches = [
            match
            for match in suggest_reuse(
                kind=kind,
                from_path=source_path,
                catalog_path=catalog_path,
                limit=8,
                min_score=max(1, similarity_threshold),
            )
            if not (match.get("kind") == kind and match.get("id") == surface_id)
        ]
        unacknowledged = [
            {
                "match": f"{match.get('kind')}:{match.get('id')}",
                "score": match.get("score"),
                "matched_terms": match.get("matched_terms", []),
            }
            for match in matches
            if not _entry_acknowledges(entry, match)
        ]
        if unacknowledged:
            unacknowledged_similarity[surface_key] = unacknowledged

    errors: dict[str, Any] = {}
    if catalog_validation.get("status") != "pass":
        errors["catalog"] = catalog_validation.get("errors", {})
    if missing_catalog:
        errors["missing_catalog_entries"] = sorted(missing_catalog)
    if unacknowledged_similarity:
        errors["unacknowledged_similarity"] = unacknowledged_similarity

    return {
        "schema": "agilab.reuse_changed_validation.v1",
        "status": "pass" if not errors else "fail",
        "catalog_path": str(_catalog_path(catalog_path)),
        "repo_root": str(root),
        "similarity_threshold": similarity_threshold,
        "summary": {
            "changed_path_count": len(changed_path_items),
            "changed_surface_count": len(changed_surfaces),
        },
        "changed_surfaces": [f"{kind}:{surface_id}" for kind, surface_id in changed_surfaces],
        "errors": errors,
    }


def validate_changed(
    *,
    repo_root: Path,
    catalog_path: Path | None = None,
    base_ref: str = "HEAD",
    similarity_threshold: int = DEFAULT_CHANGED_SIMILARITY_THRESHOLD,
) -> dict[str, Any]:
    return validate_changed_surfaces(
        repo_root=repo_root,
        changed_paths=git_changed_paths(repo_root, base_ref=base_ref),
        catalog_path=catalog_path,
        similarity_threshold=similarity_threshold,
    )
