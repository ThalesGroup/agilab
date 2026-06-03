from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "agilab.pipeline_recipe_memory.v1"
RECIPE_MEMORY_ENABLED_ENV = "AGILAB_PIPELINE_RECIPE_MEMORY"
RECIPE_MEMORY_ROOTS_ENV = "AGILAB_PIPELINE_RECIPE_MEMORY_ROOTS"
RECIPE_MEMORY_PATH_ENV = "AGILAB_PIPELINE_RECIPE_MEMORY_PATH"
RECIPE_MEMORY_INCLUDE_CANDIDATES_ENV = "AGILAB_PIPELINE_RECIPE_MEMORY_INCLUDE_CANDIDATES"
DEFAULT_MEMORY_RELATIVE_PATH = Path(".agilab") / "pipeline_recipe_memory" / "cards.jsonl"
ELIGIBLE_STATUSES = {"validated", "pass", "passed", "success", "succeeded", "completed", "executed"}
FAILED_STATUSES = {"fail", "failed", "error", "errored", "invalid"}
MAX_RECIPE_SOURCES = 200
MAX_RECIPE_CARDS = 500

_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9]{6})[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(sk-proj)-[A-Za-z0-9_\-]{4,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)\b((?:OPENAI|MISTRAL|ANTHROPIC|AZURE|AGILAB|GITHUB)_[A-Z0-9_]*(?:KEY|TOKEN|SECRET)\s*=\s*)[^\s'\"]+"),
]
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "that",
    "this",
    "then",
    "data",
    "frame",
    "dataframe",
    "column",
    "columns",
    "value",
    "values",
    "step",
    "python",
    "code",
    "using",
    "create",
    "make",
    "show",
}
_OPERATION_METHODS = {
    "agg",
    "apply",
    "assign",
    "clip",
    "concat",
    "drop",
    "dropna",
    "fillna",
    "filter",
    "groupby",
    "join",
    "map",
    "merge",
    "melt",
    "pivot",
    "pivot_table",
    "query",
    "rank",
    "rename",
    "resample",
    "rolling",
    "sort_values",
    "to_datetime",
}


@dataclass(frozen=True)
class RecipeCard:
    id: str
    intent: str
    code: str
    summary: str
    dependencies: tuple[str, ...]
    output_columns: tuple[str, ...]
    schema_hints: tuple[str, ...]
    operations: tuple[str, ...]
    validation_status: str
    validation_summary: str
    source_kind: str
    source_path: str
    source_ref: str
    model: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "id": self.id,
            "intent": self.intent,
            "code": self.code,
            "summary": self.summary,
            "dependencies": list(self.dependencies),
            "output_columns": list(self.output_columns),
            "schema_hints": list(self.schema_hints),
            "operations": list(self.operations),
            "validation_status": self.validation_status,
            "validation_summary": self.validation_summary,
            "source_kind": self.source_kind,
            "source_path": self.source_path,
            "source_ref": self.source_ref,
            "model": self.model,
        }


def recipe_memory_enabled(envars: Mapping[str, str] | None = None) -> bool:
    raw = _lookup_setting(RECIPE_MEMORY_ENABLED_ENV, envars, default="1")
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def recipe_memory_path(envars: Mapping[str, str] | None = None) -> Path:
    raw = _lookup_setting(RECIPE_MEMORY_PATH_ENV, envars, default="")
    if raw:
        return Path(str(raw)).expanduser()
    return Path.home() / DEFAULT_MEMORY_RELATIVE_PATH


def redact_recipe_text(text: str, *, home: Path | None = None) -> str:
    redacted = str(text or "")
    home_path = str(home or Path.home())
    if home_path and home_path not in {"/", "."}:
        redacted = redacted.replace(home_path, "$HOME")
    redacted = re.sub(r"/Users/[^/\s'\"]+", "$HOME", redacted)
    redacted = re.sub(r"/home/[^/\s'\"]+", "$HOME", redacted)
    redacted = re.sub(r"[A-Za-z]:\\Users\\[^\\\s'\"]+", "$HOME", redacted)
    redacted = _EMAIL_RE.sub("<email>", redacted)
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}<redacted>", redacted)
    return redacted


def normalize_recipe_code(code: str) -> str:
    text = redact_recipe_text(str(code or ""))
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def build_recipe_card(
    *,
    intent: str,
    code: str,
    summary: str = "",
    validation_status: str = "candidate",
    validation_summary: str = "",
    source_kind: str,
    source_path: Path | str,
    source_ref: str,
    model: str = "",
    schema_hints: Sequence[str] = (),
) -> RecipeCard | None:
    normalized_code = normalize_recipe_code(code)
    normalized_intent = _clean_text(intent)
    if not normalized_code or not normalized_intent:
        return None
    normalized_source = redact_recipe_text(str(source_path))
    dependencies = _extract_imports(normalized_code)
    output_columns = _extract_dataframe_outputs(normalized_code)
    operations = _extract_operations(normalized_code)
    hints = _dedupe_sorted(
        [
            *_string_hints(normalized_intent),
            *_string_hints(normalized_code),
            *[str(item) for item in schema_hints if str(item).strip()],
        ],
        limit=32,
    )
    digest = hashlib.sha256(
        "\n".join(
            [
                SCHEMA,
                normalized_source,
                source_ref,
                normalized_intent,
                normalized_code,
            ]
        ).encode("utf-8")
    ).hexdigest()[:16]
    return RecipeCard(
        id=f"recipe-{digest}",
        intent=redact_recipe_text(normalized_intent),
        code=normalized_code,
        summary=redact_recipe_text(_clean_text(summary)),
        dependencies=tuple(dependencies),
        output_columns=tuple(output_columns),
        schema_hints=tuple(hints),
        operations=tuple(operations),
        validation_status=_normalize_status(validation_status),
        validation_summary=redact_recipe_text(_clean_text(validation_summary)),
        source_kind=source_kind,
        source_path=normalized_source,
        source_ref=source_ref,
        model=redact_recipe_text(str(model or "")),
    )


def load_recipe_cards_from_lab_steps(path: Path) -> list[RecipeCard]:
    try:
        payload = tomllib.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeError):
        return []
    cards: list[RecipeCard] = []
    for module_name, entries in payload.items():
        if str(module_name).startswith("__") or not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            code = str(entry.get("C", "") or "")
            intent = str(entry.get("Q", "") or entry.get("D", "") or "")
            status, status_summary = _status_from_mapping(entry)
            card = build_recipe_card(
                intent=intent,
                code=code,
                summary=str(entry.get("D", "") or ""),
                validation_status=status,
                validation_summary=status_summary,
                source_kind="lab_steps",
                source_path=path,
                source_ref=f"{module_name}[{index}]",
                model=str(entry.get("M", "") or ""),
            )
            if card is not None:
                cards.append(card)
    return cards


def load_recipe_cards_from_notebook(path: Path) -> list[RecipeCard]:
    try:
        notebook = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(notebook, dict):
        return []
    metadata = notebook.get("metadata", {})
    agilab_payload = metadata.get("agilab", {}) if isinstance(metadata, dict) else {}
    supervisor_steps = agilab_payload.get("steps", []) if isinstance(agilab_payload, dict) else []
    if isinstance(supervisor_steps, list) and supervisor_steps:
        return _cards_from_supervisor_steps(path, supervisor_steps)
    return _cards_from_notebook_cells(path, notebook.get("cells", []))


def load_recipe_cards_from_memory(path: Path) -> list[RecipeCard]:
    try:
        lines = path.expanduser().read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    cards: list[RecipeCard] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        card = _card_from_payload(payload)
        if card is not None:
            cards.append(card)
    return cards


def discover_recipe_sources(roots: Sequence[Path | str], *, max_files: int = MAX_RECIPE_SOURCES) -> list[Path]:
    sources: list[Path] = []
    seen: set[Path] = set()
    for raw_root in roots:
        if raw_root is None:
            continue
        root = Path(str(raw_root)).expanduser()
        if not str(root):
            continue
        candidates: Iterable[Path]
        if root.is_file():
            candidates = [root]
        elif root.is_dir():
            candidates = [
                *sorted(root.rglob("lab_steps*.toml")),
                *sorted(root.rglob("*.ipynb")),
                *sorted(root.rglob("cards.jsonl")),
            ]
        else:
            continue
        for candidate in candidates:
            suffix = candidate.suffix.lower()
            if suffix not in {".toml", ".ipynb", ".jsonl"}:
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            sources.append(candidate)
            if len(sources) >= max_files:
                return sources
    return sources


def load_recipe_cards(
    roots: Sequence[Path | str],
    *,
    memory_path: Path | None = None,
    include_candidates: bool = False,
    max_cards: int = MAX_RECIPE_CARDS,
) -> list[RecipeCard]:
    cards: list[RecipeCard] = []
    if memory_path is not None:
        cards.extend(load_recipe_cards_from_memory(memory_path))
    for source in discover_recipe_sources(roots):
        suffix = source.suffix.lower()
        if suffix == ".toml":
            cards.extend(load_recipe_cards_from_lab_steps(source))
        elif suffix == ".ipynb":
            cards.extend(load_recipe_cards_from_notebook(source))
        elif suffix == ".jsonl":
            cards.extend(load_recipe_cards_from_memory(source))
        if len(cards) >= max_cards:
            break
    deduped = _dedupe_cards(cards)
    if include_candidates:
        return deduped[:max_cards]
    return [card for card in deduped if _is_eligible(card)][:max_cards]


def search_recipe_cards(
    query: str,
    cards: Sequence[RecipeCard],
    *,
    limit: int = 3,
    include_candidates: bool = False,
) -> list[RecipeCard]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    scored: list[tuple[float, str, RecipeCard]] = []
    for card in cards:
        if not include_candidates and not _is_eligible(card):
            continue
        card_tokens = _tokens(
            " ".join(
                [
                    card.intent,
                    card.summary,
                    " ".join(card.schema_hints),
                    " ".join(card.operations),
                    " ".join(card.output_columns),
                    card.code,
                ]
            )
        )
        overlap = query_tokens & card_tokens
        if not overlap:
            continue
        intent_bonus = len(query_tokens & _tokens(card.intent)) * 2.0
        operation_bonus = len(query_tokens & set(card.operations)) * 1.5
        output_bonus = len(query_tokens & set(card.output_columns))
        score = len(overlap) + intent_bonus + operation_bonus + output_bonus
        scored.append((score, card.id, card))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [card for _score, _id, card in scored[:limit]]


def build_recipe_context(
    query: str,
    cards: Sequence[RecipeCard],
    *,
    limit: int = 3,
    max_code_chars: int = 1400,
) -> str:
    matches = search_recipe_cards(query, cards, limit=limit)
    if not matches:
        return ""
    blocks = [
        "Relevant validated AGILAB recipe memory follows. Use these as implementation patterns only; "
        "do not copy paths, credentials, or prose. Keep the final answer as Python code only."
    ]
    for index, card in enumerate(matches, start=1):
        code = card.code.strip()
        if len(code) > max_code_chars:
            code = code[:max_code_chars].rstrip() + "\n# ... clipped ..."
        blocks.append(
            "\n".join(
                [
                    f"Recipe {index}: {card.intent}",
                    f"status: {card.validation_status}",
                    f"source: {card.source_kind} {card.source_ref}",
                    f"operations: {', '.join(card.operations) if card.operations else 'none'}",
                    f"output columns: {', '.join(card.output_columns) if card.output_columns else 'unknown'}",
                    "code:",
                    "```python",
                    code,
                    "```",
                ]
            )
        )
    return "\n\n".join(blocks)


def augment_question_with_recipe_memory(
    question: str,
    *,
    session_state: Mapping[str, Any] | None = None,
    envars: Mapping[str, str] | None = None,
    df_file: Path | str | None = None,
    cwd: Path | None = None,
    limit: int = 3,
) -> str:
    if not recipe_memory_enabled(envars) or not _should_augment(question):
        return question
    state = session_state or {}
    include_candidates = _truthy(_lookup_setting(RECIPE_MEMORY_INCLUDE_CANDIDATES_ENV, envars, default=""))
    roots = _recipe_roots(state, envars, df_file=df_file, cwd=cwd)
    cards = load_recipe_cards(
        roots,
        memory_path=recipe_memory_path(envars),
        include_candidates=include_candidates,
    )
    context = build_recipe_context(question, cards, limit=limit)
    if not context:
        return question
    return f"{question.strip()}\n\n{context}".strip()


def append_recipe_card(memory_path: Path, card: RecipeCard) -> bool:
    memory_path = memory_path.expanduser()
    existing_ids = {item.id for item in load_recipe_cards_from_memory(memory_path)}
    if card.id in existing_ids:
        return False
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    with memory_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(card.as_dict(), sort_keys=True, separators=(",", ":")) + "\n")
    return True


def promote_validated_recipe(
    *,
    question: str,
    code: str,
    model: str = "",
    df_columns: Sequence[str] = (),
    source_path: Path | str = "",
    source_ref: str = "",
    validation_summary: str = "validated by AGILAB pipeline execution",
    envars: Mapping[str, str] | None = None,
) -> RecipeCard | None:
    card = build_recipe_card(
        intent=question,
        code=code,
        summary=validation_summary,
        validation_status="validated",
        validation_summary=validation_summary,
        source_kind="validated_runtime",
        source_path=str(source_path or recipe_memory_path(envars)),
        source_ref=source_ref or "pipeline",
        model=model,
        schema_hints=df_columns,
    )
    if card is None:
        return None
    try:
        append_recipe_card(recipe_memory_path(envars), card)
    except (OSError, TypeError, ValueError):
        return None
    return card


def _lookup_setting(name: str, envars: Mapping[str, str] | None, *, default: str) -> str:
    if envars and envars.get(name) is not None:
        return str(envars.get(name) or "")
    return os.getenv(name, default)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _dedupe_sorted(values: Iterable[str], *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in sorted(str(item).strip() for item in values):
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if limit is not None and len(result) >= limit:
            break
    return result


def _string_hints(text: str) -> list[str]:
    hints: list[str] = []
    for token in _TOKEN_RE.findall(str(text or "")):
        normalized = token.lower()
        if len(normalized) < 3 or normalized in _STOP_WORDS:
            continue
        if "_" in normalized or normalized in _OPERATION_METHODS:
            hints.append(normalized)
    return hints


def _extract_imports(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return _dedupe_sorted(_imports_from_lines(code))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".", 1)[0])
    return _dedupe_sorted(imports)


def _imports_from_lines(code: str) -> list[str]:
    imports: list[str] = []
    for line in code.splitlines():
        import_match = re.match(r"\s*import\s+([A-Za-z_][\w.]*)", line)
        from_match = re.match(r"\s*from\s+([A-Za-z_][\w.]*)\s+import\s+", line)
        if import_match:
            imports.append(import_match.group(1).split(".", 1)[0])
        elif from_match:
            imports.append(from_match.group(1).split(".", 1)[0])
    return imports


def _extract_dataframe_outputs(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    outputs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                outputs.extend(_dataframe_target_columns(target))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "assign":
                outputs.extend(keyword.arg for keyword in node.keywords if keyword.arg)
    return _dedupe_sorted(outputs)


def _dataframe_target_columns(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Subscript) and _node_name(target.value) == "df":
        column = _constant_string(target.slice)
        return [column] if column else []
    if isinstance(target, (ast.Tuple, ast.List)):
        columns: list[str] = []
        for item in target.elts:
            columns.extend(_dataframe_target_columns(item))
        return columns
    return []


def _extract_operations(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    operations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _OPERATION_METHODS:
                operations.append(node.func.attr)
    return _dedupe_sorted(operations)


def _node_name(node: ast.AST) -> str:
    return node.id if isinstance(node, ast.Name) else ""


def _constant_string(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Index):  # pragma: no cover - Python <3.9 compatibility
        return _constant_string(node.value)
    return ""


def _status_from_mapping(entry: Mapping[str, Any]) -> tuple[str, str]:
    for key in ("validation_status", "status", "run_status", "V"):
        value = entry.get(key)
        if value:
            return _normalize_status(str(value)), str(value)
    if entry.get("validated") is True:
        return "validated", "validated"
    return "candidate", ""


def _normalize_status(status: str) -> str:
    normalized = str(status or "").strip().lower().replace("_", "-")
    if normalized in FAILED_STATUSES:
        return "failed"
    if normalized in ELIGIBLE_STATUSES:
        return "validated" if normalized in {"pass", "passed", "success", "succeeded"} else normalized
    return normalized or "candidate"


def _cards_from_supervisor_steps(path: Path, steps: Sequence[Any]) -> list[RecipeCard]:
    cards: list[RecipeCard] = []
    for index, step in enumerate(steps):
        if not isinstance(step, Mapping):
            continue
        status, status_summary = _status_from_mapping(step)
        card = build_recipe_card(
            intent=str(step.get("question", "") or step.get("description", "") or ""),
            code=str(step.get("code", "") or ""),
            summary=str(step.get("description", "") or ""),
            validation_status=status,
            validation_summary=status_summary,
            source_kind="notebook",
            source_path=path,
            source_ref=f"metadata.steps[{index}]",
            model=str(step.get("model", "") or ""),
        )
        if card is not None:
            cards.append(card)
    return cards


def _cards_from_notebook_cells(path: Path, cells: Any) -> list[RecipeCard]:
    if not isinstance(cells, list):
        return []
    cards: list[RecipeCard] = []
    pending_context = ""
    for index, cell in enumerate(cells):
        if not isinstance(cell, Mapping):
            continue
        source = _cell_source_text(cell.get("source", ""))
        if str(cell.get("cell_type", "")) == "markdown":
            pending_context = _clean_text(source)
            continue
        if str(cell.get("cell_type", "")) != "code" or not source.strip():
            continue
        status = _notebook_cell_status(cell)
        card = build_recipe_card(
            intent=pending_context or f"Notebook code cell {index + 1}",
            code=source,
            summary=pending_context,
            validation_status=status,
            validation_summary=status,
            source_kind="notebook",
            source_path=path,
            source_ref=f"cells[{index}]",
            model="",
        )
        if card is not None:
            cards.append(card)
        pending_context = ""
    return cards


def _cell_source_text(source: Any) -> str:
    if isinstance(source, str):
        return source
    if isinstance(source, Iterable):
        return "".join(str(line) for line in source)
    return str(source or "")


def _notebook_cell_status(cell: Mapping[str, Any]) -> str:
    outputs = cell.get("outputs", [])
    if isinstance(outputs, list) and any(isinstance(item, Mapping) and item.get("output_type") == "error" for item in outputs):
        return "failed"
    return "executed" if cell.get("execution_count") is not None else "candidate"


def _card_from_payload(payload: Mapping[str, Any]) -> RecipeCard | None:
    if payload.get("schema") != SCHEMA:
        return None
    required = ["id", "intent", "code", "source_kind", "source_path", "source_ref"]
    if any(not str(payload.get(key, "")).strip() for key in required):
        return None
    return RecipeCard(
        id=str(payload.get("id")),
        intent=str(payload.get("intent", "")),
        code=str(payload.get("code", "")),
        summary=str(payload.get("summary", "")),
        dependencies=tuple(str(item) for item in payload.get("dependencies", []) if str(item).strip()),
        output_columns=tuple(str(item) for item in payload.get("output_columns", []) if str(item).strip()),
        schema_hints=tuple(str(item) for item in payload.get("schema_hints", []) if str(item).strip()),
        operations=tuple(str(item) for item in payload.get("operations", []) if str(item).strip()),
        validation_status=_normalize_status(str(payload.get("validation_status", ""))),
        validation_summary=str(payload.get("validation_summary", "")),
        source_kind=str(payload.get("source_kind", "")),
        source_path=str(payload.get("source_path", "")),
        source_ref=str(payload.get("source_ref", "")),
        model=str(payload.get("model", "")),
    )


def _dedupe_cards(cards: Sequence[RecipeCard]) -> list[RecipeCard]:
    deduped: list[RecipeCard] = []
    seen: set[str] = set()
    for card in cards:
        if card.id in seen:
            continue
        seen.add(card.id)
        deduped.append(card)
    return deduped


def _is_eligible(card: RecipeCard) -> bool:
    return _normalize_status(card.validation_status) in ELIGIBLE_STATUSES


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(str(text or ""))
        if len(token) >= 3 and token.lower() not in _STOP_WORDS
    }


def _should_augment(question: str) -> bool:
    text = str(question or "")
    if not text.strip():
        return False
    lowered = text.lower()
    return "traceback:" not in lowered and "failing code:" not in lowered


def _recipe_roots(
    session_state: Mapping[str, Any],
    envars: Mapping[str, str] | None,
    *,
    df_file: Path | str | None,
    cwd: Path | None,
) -> list[Path | str]:
    roots: list[Path | str] = []
    raw_roots = _lookup_setting(RECIPE_MEMORY_ROOTS_ENV, envars, default="")
    if raw_roots:
        roots.extend(item for item in raw_roots.split(os.pathsep) if item.strip())
    for key in ("steps_file", "recipe_memory_roots"):
        value = session_state.get(key) if hasattr(session_state, "get") else None
        if isinstance(value, (list, tuple, set)):
            roots.extend(value)
        elif value:
            roots.append(value)
    env = session_state.get("env") if hasattr(session_state, "get") else None
    active_app = getattr(env, "active_app", None)
    if active_app:
        roots.append(active_app)
    if df_file:
        try:
            df_path = Path(str(df_file)).expanduser()
            if df_path.parent != Path("."):
                roots.append(df_path.parent)
        except (OSError, TypeError, ValueError):
            pass
    repo_root = cwd or Path.cwd()
    builtin_apps = repo_root / "src" / "agilab" / "apps" / "builtin"
    if builtin_apps.is_dir():
        roots.append(builtin_apps)
    return roots
