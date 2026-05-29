---
name: agilab-intent-router
description: Route terse AGILAB operator requests such as "do it", "review AGILAB", "next move", "update repos", "merge it", "check again", "release", and "cluster validation" into the right repo skills, safety mode, validation depth, and output contract using session-derived policy.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-29
---

# AGILAB Intent Router

Use this skill first when a user request is short, ambiguous, or operational.
The goal is to classify the request before acting, so terse commands map to the
right AGILAB workflow instead of defaulting to a shallow answer or wrong repo
operation.

## Grammar

```ebnf
request      ::= intent target? depth? scope? output? mode? constraint?
intent       ::= review | implement | validate | release | sync | publish | explain | continue
review       ::= "review" | "audit" | "inspect" | "assess" | "analyze"
implement    ::= "fix" | "implement" | "add" | "address" | "improve" | "clean"
validate     ::= "check" | "test" | "validate" | "verify" | "prove"
release      ::= "release" | "ready for release" | "prepare release" | "publish"
sync         ::= "update repos" | "sync repos" | "merge" | "push"
publish      ::= "linkedin" | "youtube" | "teaser" | "thumbnail" | "article"
explain      ::= "why" | "what next" | "where" | "explain"
continue     ::= "do it" | "go on" | "next move" | "check again"
target       ::= "agilab" | "docs" | "skills" | "examples" | "release" | "cluster" | "ui" | "video" | "repo"
depth        ::= "quick" | "targeted" | "deep" | "full" | "detailed"
output       ::= "summary" | "review doc" | "patch" | "PR" | "commit" | "copy/paste"
mode         ::= "do not fix" | "fix it" | "push it" | "merge it" | "only report"
constraint   ::= "only agilab" | "no tests" | "from current repo" | "from another machine"
```

## Precedence

1. Explicit user constraint wins over default routing.
2. Destructive, publish, merge, and push intents require current repo state
   inspection before action.
3. Review/audit defaults to report-first, not patch-first.
4. Fix/implement defaults to smallest patch plus targeted validation.
5. Release readiness requires authoritative workflow/tooling inspection.
6. Docs edits use canonical `../thales_agilab/docs/source` then AGILAB mirror sync.
7. Cluster work must rediscover remote workers; never reuse a remembered IP.
8. If the previous turn established scope, `do it`, `go on`, and `check again`
   inherit that scope; otherwise inspect current repo state and ask only if
   action would be risky.

## Session-Derived Routes

Route these patterns before choosing tools:

| User phrase family | Intent | Mode | Skills |
|---|---|---|---|
| `review AGILAB`, `audit AGILAB`, `deep review`, `address this audit` | deep audit | report-first; architecture-readiness gate before final audit; patch only if `fix it` follows | `agilab-deep-audit`, then `agilab-testing` if patching |
| `do it`, `go on`, `fix it`, `next move` | continue current objective | inherit previous scope | previous active skill plus `plan-before-code` for code changes |
| `update repos`, `sync repos` | safe repo sync | show command plan first | `agilab-runbook` |
| `update skill`, `sync skills`, `make future agents do X` | repo skill update | edit `.claude`, sync `.codex`, regenerate index | `skill-creator`, `repo-skill-maintenance` |
| `ready for release`, `release it`, `badge`, `proof`, `PyPI` | release verification | inspect release workflow/tooling first | `agilab-release-verification` |
| `docs aligned`, `screenshot docs`, `link added`, `published docs` | docs workflow | canonical docs then mirror | `agilab-docs` |
| `cluster`, `remote worker`, `validate cluster` | cluster validation | rediscover worker, split SSH/share/compute | `agilab-testing`, `agilab-installer`, `agilab-runbook` |
| `teaser`, `youtube`, `thumbnail`, `linkedin` | content packaging | no repo edit unless asked | `agilab-product-reels` for video assets |

## Behavior Contract

- For `review AGILAB`, always load `agilab-deep-audit` and define a review
  scope before reading code. If architecture context is not crystal clear, load
  `ARCHITECTURE_FOUNDATIONS.md` and run the deep-audit preflight before writing
  final findings.
- For `fix it` after an audit, convert prioritized findings into a patch plan;
  do not silently patch unrelated findings.
- For `update repos`, never touch repos outside the current allowlist unless
  the user names them. Show concrete `git -C` commands before execution.
- For `do it` after a proposal, execute the proposed action if repo state is
  safe. If state changed unexpectedly, report the changed branch/files first.
- For `check again`, verify the authoritative source for the prior claim:
  current repo state, workflow status, docs mirror, PyPI/GitHub release, or
  cluster discovery as appropriate.
- For `next move`, inspect current repo state and relevant workflow/tooling;
  do not answer only from memory.

## Regenerating The Policy From Sessions

Use the synthesis tool to mine local sessions and rollout summaries into a
redacted local artifact:

```bash
uv --preview-features extra-build-dependencies run python tools/session_intent_synthesis.py \
  --sessions-root "$HOME/.codex/sessions" \
  --memory-root "$HOME/.codex/memories/rollout_summaries" \
  --output test-results/session_intents.json
```

The output is evidence for updating this skill. Do not commit raw session
transcripts or unreviewed local synthesis artifacts.
