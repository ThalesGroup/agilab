#!/usr/bin/env python3
"""Synthesize a redacted AGILAB intent-routing report from local Codex sessions."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "agilab.session_intent_synthesis.v1"
DEFAULT_OUTPUT = Path("test-results/session_intents.json")
MAX_EXAMPLES_PER_INTENT = 5
SYSTEMISH_PREFIXES = (
    "# agents.md instructions",
    "<instructions>",
    "<permissions instructions>",
    "<environment_context>",
)
SYSTEMISH_CONTAINS = (
    "you are codex",
    "agilab agent runbook",
    "filesystem sandboxing defines",
    "collaboration mode:",
)
LONG_MESSAGE_ALLOW_PREFIXES = (
    "address this audit",
    "audit",
    "review",
    "fix",
    "do it",
    "go on",
    "check",
    "update",
    "release",
    "why",
)

SECRET_PATTERNS = (
    (
        re.compile(r"https://pypi\.org/account/confirm-login/\?token=\S+"),
        "https://pypi.org/account/confirm-login/?token=<redacted>",
    ),
    (
        re.compile(r"(?i)(--(?:password|openai-api-key|cluster-ssh-credentials)\s+)\S+"),
        r"\1<redacted>",
    ),
    (re.compile(r"(?i)(token=)[^&\s]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(password|secret|api[_-]?key|token)\s*[:=]\s*['\"]?[^'\"\s]{8,}"), r"\1=<redacted>"),
    (re.compile(r"sk-[A-Za-z0-9_-]{12,}"), "sk-<redacted>"),
)


@dataclass(frozen=True)
class IntentRule:
    intent: str
    triggers: tuple[str, ...]
    mode: str
    skills: tuple[str, ...]
    behavior: str


INTENT_RULES = (
    IntentRule(
        "deep_audit",
        ("review agilab", "audit agilab", "deep review", "architecture review", "security review", "address this audit"),
        "report_first",
        ("agilab-deep-audit", "agilab-testing"),
        "Define scope, inspect current code, produce evidence-backed findings, and patch only after explicit follow-up.",
    ),
    IntentRule(
        "safe_repo_sync",
        ("update repos", "sync repos"),
        "plan_then_fast_forward",
        ("agilab-runbook",),
        "Show concrete git command plan, check tracked dirtiness, fetch, compare ahead/behind, and fast-forward only safe repos.",
    ),
    IntentRule(
        "repo_skill_update",
        ("update skill", "sync skills", "skill trigger", "future agents", "next time i ask"),
        "edit_sync_validate",
        ("skill-creator", "repo-skill-maintenance"),
        "Edit .claude skill, sync one skill into .codex, regenerate indexes, and run the skills parity profile.",
    ),
    IntentRule(
        "release_verification",
        ("ready for release", "release it", "prepare release", "pypi", "badge", "release proof"),
        "inspect_authoritative_tooling",
        ("agilab-release-verification",),
        "Inspect release workflow/tooling and public evidence before sequencing release or publication steps.",
    ),
    IntentRule(
        "docs_alignment",
        ("doc aligned", "docs aligned", "screenshot", "link added", "published docs"),
        "canonical_docs_then_mirror",
        ("agilab-docs",),
        "Edit canonical thales_agilab docs first, sync AGILAB mirror, validate stamp/build, then publish if requested.",
    ),
    IntentRule(
        "cluster_validation",
        ("cluster", "remote worker", "worker ip", "sshfs", "validate cluster"),
        "discover_then_validate",
        ("agilab-testing", "agilab-installer", "agilab-runbook"),
        "Rediscover workers first, split SSH/share/compute checks, and never reuse remembered worker IPs.",
    ),
    IntentRule(
        "content_packaging",
        ("youtube", "linkedin", "teaser", "thumbnail", "article"),
        "package_content",
        ("agilab-product-reels",),
        "Prepare copy, links, thumbnails, or video metadata without repo edits unless explicitly requested.",
    ),
    IntentRule(
        "continue_current_scope",
        ("do it", "go on", "fix it", "next move", "check again", "merge it", "push it"),
        "inherit_context",
        ("agilab-intent-router",),
        "Inherit prior scope, inspect current state, and continue only if the action is safe for the current repo state.",
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def redact(text: str) -> str:
    redacted = text.replace("\n", " ").strip()
    for pattern, replacement in SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    redacted = re.sub(r"\s+", " ", redacted)
    if len(redacted) > 220:
        redacted = redacted[:217] + "..."
    return redacted


def _is_probable_operator_message(text: str) -> bool:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if lowered.startswith(SYSTEMISH_PREFIXES):
        return False
    if any(token in lowered[:1200] for token in SYSTEMISH_CONTAINS):
        return False
    if lowered.startswith("<html") or "<html" in lowered[:80]:
        return False
    if len(cleaned) > 4000 and not lowered.startswith(LONG_MESSAGE_ALLOW_PREFIXES):
        return False
    return True


def _content_text(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    texts.append(text)
        return texts
    return []


def _extract_user_messages_from_obj(obj: Mapping[str, Any]) -> list[str]:
    messages: list[str] = []
    if obj.get("type") == "response_item":
        payload = obj.get("payload")
        if isinstance(payload, Mapping) and payload.get("role") == "user":
            messages.extend(_content_text(payload.get("content")))
    if obj.get("type") == "compacted":
        payload = obj.get("payload")
        history = payload.get("replacement_history") if isinstance(payload, Mapping) else None
        if isinstance(history, list):
            for item in history:
                if isinstance(item, Mapping) and item.get("role") == "user":
                    messages.extend(_content_text(item.get("content")))
    if obj.get("role") == "user":
        messages.extend(_content_text(obj.get("content")))
    return [message for message in messages if _is_probable_operator_message(message)]


def iter_session_messages(paths: Iterable[Path]) -> Iterable[tuple[Path, str]]:
    for path in sorted(paths):
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, Mapping) or obj.get("type") == "session_meta":
                continue
            for message in _extract_user_messages_from_obj(obj):
                yield path, message


def _classify(text: str) -> list[IntentRule]:
    lowered = " ".join(text.lower().split())
    matches: list[IntentRule] = []
    for rule in INTENT_RULES:
        if any(trigger in lowered for trigger in rule.triggers):
            matches.append(rule)
    return matches


def _session_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.jsonl"))


def _memory_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix in {".md", ".jsonl", ".txt"})


def build_synthesis(
    *,
    session_paths: Sequence[Path],
    memory_paths: Sequence[Path],
) -> dict[str, Any]:
    examples: dict[str, list[str]] = defaultdict(list)
    counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    scanned_session_names: set[str] = set()
    scanned_memory = 0
    user_message_count = 0

    for path, message in iter_session_messages(session_paths):
        scanned_session_names.add(path.name)
        user_message_count += 1
        for rule in _classify(message):
            counts[rule.intent] += 1
            source_counts[path.name] += 1
            if len(examples[rule.intent]) < MAX_EXAMPLES_PER_INTENT:
                examples[rule.intent].append(redact(message))

    seen_memory: set[Path] = set()
    for path in memory_paths:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        seen_memory.add(path)
        for rule in INTENT_RULES:
            if any(trigger in text.lower() for trigger in rule.triggers):
                counts[rule.intent] += 1
                source_counts[path.name] += 1
                if len(examples[rule.intent]) < MAX_EXAMPLES_PER_INTENT:
                    examples[rule.intent].append(f"memory:{path.name}")
    scanned_memory = len(seen_memory)

    intents = []
    for rule in INTENT_RULES:
        intents.append(
            {
                "id": rule.intent,
                "observations": counts[rule.intent],
                "triggers": list(rule.triggers),
                "mode": rule.mode,
                "skills": list(rule.skills),
                "behavior": rule.behavior,
                "redacted_examples": examples.get(rule.intent, []),
            }
        )

    return {
        "schema": SCHEMA,
        "generated_at": _utc_now(),
        "kind": "agilab.session_intent_synthesis",
        "summary": {
            "session_files": len(session_paths),
            "memory_files": scanned_memory,
            "user_messages": user_message_count,
            "matched_observations": sum(counts.values()),
            "note": "Examples are redacted and truncated; do not commit raw session transcripts.",
        },
        "intents": intents,
        "source_counts": dict(sorted(source_counts.items())),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-root", type=Path, default=Path.home() / ".codex" / "sessions")
    parser.add_argument("--memory-root", type=Path, default=Path.home() / ".codex" / "memories" / "rollout_summaries")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--json", action="store_true", help="Print the synthesis JSON to stdout.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    payload = build_synthesis(
        session_paths=_session_paths(args.sessions_root),
        memory_paths=_memory_paths(args.memory_root),
    )
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        summary = payload["summary"]
        print(
            f"session intent synthesis: {output} "
            f"sessions={summary['session_files']} messages={summary['user_messages']} "
            f"matches={summary['matched_observations']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
