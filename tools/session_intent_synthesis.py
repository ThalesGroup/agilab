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
RULE_PROPOSAL_SCHEMA = "agilab.session_rule_proposals.v1"
DEFAULT_OUTPUT = Path("test-results/session_intents.json")
DEFAULT_RULE_PROPOSALS_OUTPUT = Path("test-results/session_rule_proposals.json")
DEFAULT_RULE_PROPOSALS_MARKDOWN = Path("test-results/session_rule_proposals.md")
MAX_EXAMPLES_PER_INTENT = 5
MAX_EXAMPLES_PER_PROPOSAL = 5
DEFAULT_RULE_PROPOSAL_MIN_OBSERVATIONS = 2
DEFAULT_RULE_SURFACES = (
    "AGENTS.md",
    "AGENT_CONVENTIONS.md",
    "AGENT_LEARNINGS.md",
    "tools/agent_workflows.md",
    ".claude/skills/agilab-intent-router/SKILL.md",
    ".claude/skills/agilab-testing/SKILL.md",
    ".claude/skills/codex-session-learning/SKILL.md",
)
SYSTEMISH_PREFIXES = (
    "# agents.md instructions",
    "<instructions>",
    "<permissions instructions>",
    "<environment_context>",
    "fed-back from claude:",
    "feedback from claude:",
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


@dataclass(frozen=True)
class RuleProposalPattern:
    id: str
    triggers: tuple[str, ...]
    target: str
    proposed_rule: str
    rationale: str
    duplicate_terms: tuple[str, ...]


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

RULE_PROPOSAL_PATTERNS = (
    RuleProposalPattern(
        "combined_execution_followup",
        (
            "do it; then next move",
            "do it + next move",
            "do it then next move",
            "do it; validate; push",
            "do it; validate; push if clean; merge it",
            "merge it; then next move",
            "merge it then next move",
            "then suggest next move",
            "then next move",
        ),
        ".claude/skills/agilab-intent-router/SKILL.md",
        (
            "When a user combines execution, validation, publish, merge, and "
            "follow-up planning in one message, treat it as an ordered single "
            "turn: execute each explicit step after its safety gate, report the "
            "result, then provide the next recommendation unless a blocker needs input."
        ),
        "Combining explicit safe steps avoids extra prompt round trips.",
        (
            "combines execution, validation, publish, merge",
            "single ordered turn",
            "do it; validate; push if clean; merge it",
            "second `merge it` or `next move` turn",
        ),
    ),
    RuleProposalPattern(
        "explicit_rule_request",
        (
            "add it as a rule",
            "add this as a rule",
            "make it a rule",
            "next time i ask",
            "future agents",
        ),
        "AGENT_LEARNINGS.md or the narrowest matching repo skill",
        (
            "When the user asks to make a behavior durable, update the narrowest "
            "existing agent-rule surface instead of relying on hidden memory or a "
            "one-off final-answer note."
        ),
        "Explicit rule requests are high-signal corrections that should become reviewable repo guidance.",
        (
            "make a behavior durable",
            "narrowest existing agent-rule surface",
            "agent correction ledger",
        ),
    ),
    RuleProposalPattern(
        "missed_surface_correction",
        (
            "you miss the",
            "you missed the",
            "you forgot the",
            "you didn't check",
            "you did not check",
        ),
        "AGENT_LEARNINGS.md or the domain skill that owns the missed path",
        (
            "When corrected for missing a concrete path, repo, or generated surface, "
            "add that surface to the relevant checklist before repeating the same "
            "workflow."
        ),
        "Missed-path corrections usually identify checklist gaps that are cheaper to encode than rediscover.",
        (
            "corrected for missing",
            "concrete path",
            "relevant checklist",
        ),
    ),
    RuleProposalPattern(
        "pre_push_scope_friction",
        (
            "pre-push guard",
            "mixed-scope",
            "mixed scope",
            "agilab_allow_mixed_scope_push",
        ),
        "tools/worktree_scope_guard.py, tools/pre_push_changed_files.py, or AGENT_LEARNINGS.md",
        (
            "When a generated artifact family repeatedly forces a mixed-scope push "
            "override, fix the classifier or document the exact unrelated guard "
            "failure before bypassing."
        ),
        "Repeated guard bypasses are usually tooling friction, not something to normalize silently.",
        (
            "pre-push guard fails",
            "mixed-scope push override",
            "fix the classifier",
            "document the exact unrelated failure",
        ),
    ),
    RuleProposalPattern(
        "session_history_learning",
        (
            "learn from the session history",
            "learn from history",
            "session history",
            "session learning",
        ),
        "tools/session_intent_synthesis.py or .claude/skills/codex-session-learning/SKILL.md",
        (
            "When session history reveals repeated corrections, generate a redacted "
            "rule proposal for human review instead of auto-editing durable agent "
            "instructions from raw transcripts."
        ),
        "Session history is useful evidence, but raw transcripts are noisy and should not directly edit rules.",
        (
            "redacted rule proposal",
            "human review",
            "raw transcripts",
        ),
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


def _normalized_contains(text: str, triggers: Sequence[str]) -> bool:
    lowered = " ".join(text.lower().split())
    return any(trigger in lowered for trigger in triggers)


def _append_limited_unique(values: dict[str, list[str]], key: str, value: str, *, limit: int) -> None:
    bucket = values[key]
    if value in bucket or len(bucket) >= limit:
        return
    bucket.append(value)


def load_rule_surface_texts(root: Path) -> dict[str, str]:
    surfaces: dict[str, str] = {}
    base = root.expanduser().resolve()
    for relative in DEFAULT_RULE_SURFACES:
        path = base / relative
        try:
            surfaces[relative] = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    return surfaces


def _duplicate_paths(pattern: RuleProposalPattern, rule_surface_texts: Mapping[str, str]) -> list[str]:
    matches: list[str] = []
    terms = tuple(term.lower() for term in pattern.duplicate_terms)
    for path, text in sorted(rule_surface_texts.items()):
        lowered = text.lower()
        if any(term in lowered for term in terms):
            matches.append(path)
    return matches


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
            _append_limited_unique(examples, rule.intent, redact(message), limit=MAX_EXAMPLES_PER_INTENT)

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
                _append_limited_unique(examples, rule.intent, f"memory:{path.name}", limit=MAX_EXAMPLES_PER_INTENT)
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


def build_rule_proposals(
    *,
    session_paths: Sequence[Path],
    memory_paths: Sequence[Path],
    rule_surface_texts: Mapping[str, str] | None = None,
    min_observations: int = DEFAULT_RULE_PROPOSAL_MIN_OBSERVATIONS,
) -> dict[str, Any]:
    examples: dict[str, list[str]] = defaultdict(list)
    counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    user_message_count = 0
    memory_files = 0

    for path, message in iter_session_messages(session_paths):
        user_message_count += 1
        for pattern in RULE_PROPOSAL_PATTERNS:
            if _normalized_contains(message, pattern.triggers):
                counts[pattern.id] += 1
                source_counts[path.name] += 1
                _append_limited_unique(examples, pattern.id, redact(message), limit=MAX_EXAMPLES_PER_PROPOSAL)

    for path in memory_paths:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        memory_files += 1
        for pattern in RULE_PROPOSAL_PATTERNS:
            if _normalized_contains(text, pattern.triggers):
                counts[pattern.id] += 1
                source_counts[path.name] += 1
                _append_limited_unique(examples, pattern.id, f"memory:{path.name}", limit=MAX_EXAMPLES_PER_PROPOSAL)

    rule_texts = rule_surface_texts or {}
    threshold = max(1, int(min_observations))
    proposals: list[dict[str, Any]] = []
    for pattern in RULE_PROPOSAL_PATTERNS:
        observations = counts[pattern.id]
        if observations < threshold:
            continue
        duplicate_paths = _duplicate_paths(pattern, rule_texts)
        proposals.append(
            {
                "id": pattern.id,
                "observations": observations,
                "status": "already-covered" if duplicate_paths else "candidate",
                "target": pattern.target,
                "proposed_rule": pattern.proposed_rule,
                "rationale": pattern.rationale,
                "duplicate_paths": duplicate_paths,
                "redacted_examples": examples.get(pattern.id, []),
            }
        )

    return {
        "schema": RULE_PROPOSAL_SCHEMA,
        "generated_at": _utc_now(),
        "kind": "agilab.session_rule_proposals",
        "summary": {
            "session_files": len(session_paths),
            "memory_files": memory_files,
            "user_messages": user_message_count,
            "min_observations": threshold,
            "proposal_count": len(proposals),
            "candidate_count": sum(1 for proposal in proposals if proposal["status"] == "candidate"),
            "already_covered_count": sum(1 for proposal in proposals if proposal["status"] == "already-covered"),
            "note": "Review proposals before editing durable agent instructions; examples are redacted and truncated.",
        },
        "proposals": proposals,
        "source_counts": dict(sorted(source_counts.items())),
    }


def render_rule_proposals_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary", {})
    lines = [
        "# Session Rule Proposals",
        "",
        f"Generated: {payload.get('generated_at', '')}",
        "",
        (
            "Summary: "
            f"{summary.get('proposal_count', 0)} proposal(s), "
            f"{summary.get('candidate_count', 0)} candidate(s), "
            f"{summary.get('already_covered_count', 0)} already covered."
        ),
        "",
        "Review these proposals before editing durable AGILAB agent instructions.",
        "",
    ]
    proposals = payload.get("proposals", [])
    if not isinstance(proposals, list) or not proposals:
        lines.extend(["No rule proposals met the observation threshold.", ""])
        return "\n".join(lines)

    for proposal in proposals:
        if not isinstance(proposal, Mapping):
            continue
        lines.extend(
            [
                f"## {proposal.get('id', 'unknown')}",
                "",
                f"- status: {proposal.get('status', '')}",
                f"- observations: {proposal.get('observations', 0)}",
                f"- target: `{proposal.get('target', '')}`",
                f"- rationale: {proposal.get('rationale', '')}",
                "",
                "Proposed rule:",
                "",
                f"> {proposal.get('proposed_rule', '')}",
                "",
            ]
        )
        duplicate_paths = proposal.get("duplicate_paths", [])
        if isinstance(duplicate_paths, list) and duplicate_paths:
            lines.append("Duplicate evidence:")
            for path in duplicate_paths:
                lines.append(f"- `{path}`")
            lines.append("")
        examples = proposal.get("redacted_examples", [])
        if isinstance(examples, list) and examples:
            lines.append("Redacted examples:")
            for example in examples:
                lines.append(f"- {example}")
            lines.append("")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-root", type=Path, default=Path.home() / ".codex" / "sessions")
    parser.add_argument("--memory-root", type=Path, default=Path.home() / ".codex" / "memories" / "rollout_summaries")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--propose-rules", action="store_true", help="Also write redacted rule proposals for review.")
    parser.add_argument("--rule-output", type=Path, default=DEFAULT_RULE_PROPOSALS_OUTPUT)
    parser.add_argument("--rule-markdown-output", type=Path, default=DEFAULT_RULE_PROPOSALS_MARKDOWN)
    parser.add_argument("--rules-root", type=Path, default=Path("."), help="Repository root containing current rule surfaces.")
    parser.add_argument(
        "--min-rule-observations",
        type=int,
        default=DEFAULT_RULE_PROPOSAL_MIN_OBSERVATIONS,
        help="Minimum observations required before a rule proposal is emitted.",
    )
    parser.add_argument("--json", action="store_true", help="Print the synthesis JSON to stdout.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    session_paths = _session_paths(args.sessions_root)
    memory_paths = _memory_paths(args.memory_root)
    payload = build_synthesis(
        session_paths=session_paths,
        memory_paths=memory_paths,
    )
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rule_payload: dict[str, Any] | None = None
    if args.propose_rules:
        rule_payload = build_rule_proposals(
            session_paths=session_paths,
            memory_paths=memory_paths,
            rule_surface_texts=load_rule_surface_texts(args.rules_root),
            min_observations=args.min_rule_observations,
        )
        rule_output = args.rule_output.expanduser()
        rule_output.parent.mkdir(parents=True, exist_ok=True)
        rule_output.write_text(json.dumps(rule_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        rule_markdown_output = args.rule_markdown_output.expanduser()
        rule_markdown_output.parent.mkdir(parents=True, exist_ok=True)
        rule_markdown_output.write_text(render_rule_proposals_markdown(rule_payload), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        summary = payload["summary"]
        print(
            f"session intent synthesis: {output} "
            f"sessions={summary['session_files']} messages={summary['user_messages']} "
            f"matches={summary['matched_observations']}"
        )
        if rule_payload is not None:
            rule_summary = rule_payload["summary"]
            print(
                f"session rule proposals: {args.rule_output.expanduser()} "
                f"proposals={rule_summary['proposal_count']} "
                f"candidates={rule_summary['candidate_count']} "
                f"already_covered={rule_summary['already_covered_count']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
