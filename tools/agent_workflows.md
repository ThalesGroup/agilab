# Agent Workflows for AGILAB

This repository is prepared for five executable agent paths, plus one catalog-compatible path:

- **Claude**: repo skills under [`.claude/skills`](../.claude/skills/README.md)
- **Codex**: repo skills under [`.codex/skills`](../.codex/skills/README.md) and the wrapper in [codex_workflow.sh](codex_workflow.sh)
- **Aider**: repo config in [`.aider.conf.yml`](../.aider.conf.yml) and the wrapper in [aider_workflow.sh](aider_workflow.sh)
- **OpenCode**: project config in [opencode.json](../opencode.json), agents under [`.opencode/agents`](../.opencode/agents), and the wrapper in [opencode_workflow.sh](opencode_workflow.sh)
- **Mistral Vibe**: repo wrapper in [vibe_workflow.sh](vibe_workflow.sh), with model/provider selection kept in Vibe's own config
- **Continue**: catalog-compatible through AGENT_SKILLS.md / `llms.txt`; AGILAB does not ship a Continue wrapper or project config yet

The public agent surface is summarized in [AGENT_SKILLS.md](../AGENT_SKILLS.md)
and mirrored for scraper/LLM discovery through [llms.txt](../llms.txt) and
[llms-full.txt](../llms-full.txt). The shipped product surface is also indexed
for agents in [agilab-capabilities.json](../agilab-capabilities.json), which is
regenerated with `python3 tools/agilab_capabilities_manifest.py --apply` and
checked against [agilab-capabilities.schema.json](../agilab-capabilities.schema.json)
with `python3 tools/agilab_capabilities_lint.py --check`. The semantic lint
rules are declared in [agilab-capability-rules.yml](../agilab-capability-rules.yml)
so severity, category, and rationale are reviewable without reading Python.
The compact agentic-web discovery file is [agenticweb.md](../agenticweb.md);
generate it with `python3 tools/agenticweb_manifest.py --apply` and check it
with `python3 tools/agenticweb_manifest.py --check`.

Root agent instructions are checked as their own contract. Run:

```bash
python3 tools/agent_instruction_contract.py --check
```

The output uses schema `agilab.agent_instruction_contract.v1` and verifies that
[AGENTS.md](../AGENTS.md), [AGENT_CONVENTIONS.md](../AGENT_CONVENTIONS.md),
[AGENT_LEARNINGS.md](../AGENT_LEARNINGS.md), this workflow guide, public agent
docs, `agilab-capabilities.json`, and `agenticweb.md` still describe the same
executable agent-facing contract. The report also includes a deterministic file
evidence snapshot with line counts, heading counts, required-marker coverage,
and SHA-256 hashes for the checked runbook files. This guards the runbook and
discovery layer only; it does not execute agents, generate instructions with an
LLM, or replace skill quality, security, or capability-manifest checks.

Agent commit provenance is checked separately:

```bash
python3 tools/agent_commit_provenance_guard.py --check-config
python3 tools/agent_commit_provenance_guard.py --inventory-github --repo ThalesGroup/agilab --json
```

The output uses schema `agilab.agent_commit_provenance.v1`. On agent-prefixed
branches such as `codex/*`, `codex-*`, `claude/*`, `aider/*`, `opencode/*`,
and `agent/*`, the guard requires explicit agent or bot author and committer
display names. The confirmed operator's verified email and matching signing key
may be used with those names. Never invent a bot noreply address: it may belong
to a different GitHub account. The offline guard checks attribution conventions;
email ownership and remote signature verification are separate checks.
The config check reads effective Git identities, including author/committer
configuration and environment overrides. The repo hooks run the config check
before commits and the pushed-commit check before pushes, so agent-authored PRs
cannot silently appear as human-authored work.

PR Agent Metadata records the confirmed operator/approver separately from the
agent and its technical settings. In Jean-Pierre MORARD's confirmed sessions,
the operator is `jpmorard`; verify the publishing GitHub actor. Other operators
must supply their own identity. When model/runtime details are unavailable,
write `not exposed by the runtime`; a person's name does not fill those fields.

The README badge contract is:

- **Skills**: the reviewed skill count
- **Standard**: Agent Skills style `SKILL.md` runbooks
- **Works with**: Codex, Claude Code, Aider, OpenCode, and Mistral Vibe

Use the short repo contract in [AGENT_CONVENTIONS.md](../AGENT_CONVENTIONS.md)
for local coding agents with smaller context windows. Use [AGENTS.md](../AGENTS.md)
for the full AGILAB runbook when the task touches risky surfaces.
When validation succeeds, keep close-outs compact: write `Validation passed.`
without listing every command unless the evidence details are explicitly needed.

When coding through a terminal agent, AGILAB recommends launching that agent
through Tokki when it is available. Tokki keeps context compact, digests noisy
terminal output, records session metadata, and exposes token-savings evidence.
For ad-hoc terminal checks inside an agent session, prefer
`tokki run -- <command>` when it can execute the command faithfully.
It is an efficiency and observability layer for agent sessions; the AGILAB
validation source of truth remains `tools/impact_validate.py`, `./dev`, and the
workflow-parity profiles.

`AGENTS.md` is intentionally the compact rule index. Keep long operational
recipes here or in focused skills, then link to them from `AGENTS.md` instead of
expanding the main runbook. This keeps small-context agents on
`AGENT_CONVENTIONS.md` while preserving deeper workflows for tasks that need
them.

Use [AGENT_LEARNINGS.md](../AGENT_LEARNINGS.md) only for reusable corrections:
when a user, reviewer, or failed validation exposes a repeated agent behavior
not already covered by the runbooks, add one concrete rule or tighten an
existing one. Do not use it as a session transcript, brainstorming log, or
replacement for tests.

## Resource preflight

Before heavy agent-assisted analysis, model training, large data work, or cluster
experiments, write a resource snapshot:

```bash
python tools/resource_snapshot.py --output resource_snapshot.json --json
```

The JSON uses schema `agilab.resource_snapshot.v1` and records CPU, memory,
disk, GPU backends, and execution recommendations. Attach it to run evidence
when resource constraints explain scheduler, autoscale, or model choices.

## Context routing

Before starting an ambiguous repo task, ask the local router which AGILAB
runbooks and skills apply:

```bash
python tools/agent_context_router.py \
  --files docs/source/agent-workflows.rst src/agilab/agent_run.py \
  --prompt "update agent evidence docs" \
  --json
```

The output uses schema `agilab.agent_context_recommendation.v1` and is produced
from the reviewed rules in `agent-context-rules.json`. It is a contract proof
for agent context selection only: it does not execute agents, run tests, or
override the validation gates reported by `tools/impact_validate.py`.

For AGILAB development, use the scoped profile that starts from the current
project/framework and then expands into builtin projects, all projects, and
the whole repo only when needed:

```bash
python tools/agent_context_router.py \
  --profile agilab \
  --files src/agilab/pages/4_ANALYSIS.py src/agilab/notebooks/notebook_export_support.py \
  --prompt "fix notebook sync in the analysis page" \
  --json
```

For Tokki or another token-saving wrapper, request the compact profile:

```bash
python tools/agent_context_router.py \
  --profile tokki \
  --files src/agilab/pages/4_ANALYSIS.py src/agilab/notebooks/notebook_export_support.py \
  --prompt "fix notebook sync in the analysis page" \
  --json
```

The `context_profile` block returns baseline files, matched context packs,
configured token allowances, and follow-up validation commands. The legacy
`estimated_token_budget` field sums reservations; `budget_kind` explicitly marks
that it is not a measurement of file contents. The profile is advisory, while
`tools/impact_validate.py` remains the validation source of truth. Run its compact
output instead of routinely reading the validation tool's implementation.

Whole-repo context requires an explicit phrase such as `whole repo` or
`repo-wide`. A single built-in file stays in its project scope; multiple project
owners or explicit `all projects` requests expand that scope. Applicable
evidence and safety rules remain independent of this narrowing. Canonical
`agent_runtime` and `evidence` paths retain dedicated evidence context.

For measured source context, use the existing router's materialization mode:

```bash
uv --preview-features extra-build-dependencies run --with tiktoken \
  python tools/agent_context_router.py --profile tokki --materialize \
  --excerpt src/agilab/agent_runtime/verification.py::validate_agent_run \
  --context-tokens 24000 --reserve-tokens 2000 --json
```

Selectors accept a file, `path::symbol` (including nested definitions), or
`path#L20-L40`. `materialized_context` contains the measured `context_text`,
source SHA-256 values, selected line ranges, and an omission ledger. Directories
are never recursively read. Duplicate content is included once. Mandatory
policy is collected before optional pack limits. With explicit files/excerpts,
other pack sources remain deferred pointers instead of filling the spare budget.
Mandatory
baseline and applicable skill files are included intact or the command exits
with `context-blocked`; increase the allowance or separately inspect required
policy rather than treating an incomplete packet as sufficient authorization.
The counter is the `o200k_base` reference encoding, excluding protocol framing,
task text, already-loaded instructions and actual model billing. The reserve
leaves capacity for those external inputs and the answer; callers must choose
it for their own model and workflow. This does not waive `AGENTS.md` or any
approval, validation, or evidence requirement.

Validate the rule file with:

```bash
python tools/agent_context_router.py --check
```

To repeat the fixed retrieval-context benchmark with verified local experiment
receipts (five tasks, three baseline/candidate observations):

```bash
uv --preview-features extra-build-dependencies run --with tiktoken==0.12.0 \
  python -m tools.agent_context.benchmark \
  --output reports/context-benchmark --repeats 3 --context-budget 24000
```

It compares full owner files with explicit excerpts from the same source bytes,
keeps required policy intact, recounts token measurements in the grader, and
rejects source drift between reads. The common budget covers source/policy
context only; reserve task, tool and response space separately. Results include
source hashes, acceptance receipts and a summary. Existing output directories
are refused. A nonzero result preserves evidence of incomplete or oversized
context. A project-local `worker` reference alone does not imply deployment;
explicit operations, unknown worker scope and shared runtime paths retain
installer guidance.

This is a source retrieval microbenchmark. It does not solve the five coding
tasks, establish model quality, measure provider cache behavior, or claim billed
token savings. Actual model usage stays `not observed`; the experiment comparison
contract can attach a registered usage artifact when one exists. The tokenizer
is pinned, while its local cache is unmanaged; counting timings exclude initial
tokenizer loading and should not be treated as agent latency.

## Demo an agentic workflow

For a live demo, run the provider-neutral AGILAB workflow helper from the
repository root:

```bash
tools/demo_agentic_agilab_workflow.sh --agent codex
```

The demo is intentionally local-first. It does not need to call a hosted LLM to
prove the workflow. It shows an agentic coding use case where an agent first
captures the repo scope, routes the task through AGILAB's context router,
computes the impact-validation plan, records the validation as an
`agilab.agent_run.v1` evidence manifest, then renders handoff, next-action,
validation, and context cards that another agent can consume.

Use a custom prompt or agent label when presenting another path:

```bash
tools/demo_agentic_agilab_workflow.sh \
  --agent claude \
  --prompt "review the current app changes and route the proof"
```

Generated evidence is written under
`artifacts/demo_media/agentic-workflow/evidence/`, which is ignored by Git.
The command uses staged, unstaged, and untracked working-tree changes when
there are local changes; if the tree is clean, it falls back to the diff
against `origin/main` for impact validation and uses the agent workflow docs as
the context-routing example.

## Shared skill trees and Tokki visibility

Repo-managed skills are canonical under `.claude/skills` and mirrored into
`.codex/skills`. The Tokki agent reads the canonical tree directly, so no
third repo mirror exists:

```bash
tokki skills list --skills-dir .claude/skills --json
```

Update a shared skill with the targeted sync, then verify tree drift and
Tokki skill visibility with the read-only check:

```bash
python3 tools/sync_agent_skills.py --skills <skill-name>
python3 tools/sync_agent_skills.py --check
```

The sync also refreshes the Codex skill index, badges, catalog, capability
manifest, and agenticweb surfaces. The `--check` mode compares the canonical
and mirror trees file by file, then confirms Tokki enumerates every canonical
skill; it skips the Tokki step with a notice when the `tokki` CLI is not
installed. The check is registered as a Tokki model-free validation route in
`.tokki/model-free-commands`; confirm the route with:

```bash
tokki learn model-free check --root . -- python3 tools/sync_agent_skills.py --check
```

## Skill quality and security scans

Changed repo-managed skills are scanned locally. `AGENT_SKILLS.md` lists the
reviewed skill catalog and maintenance contract, while this workflow guide owns
the executable scan commands. Run the changed-only local check before pushing
skill changes:

```bash
python tools/agent_skill_quality_guard.py --changed-only --fail-on high
python tools/skill_security_scan.py --changed-only --fail-on critical
```

For a full local pass:

```bash
python tools/agent_skill_quality_guard.py --roots .claude/skills .codex/skills --fail-on high
python tools/skill_security_scan.py --roots .claude/skills .codex/skills --fail-on critical
```

The quality guard checks portable skill structure, local links, support-file
reachability, activation size, and optional external `skill-validator` output
when that CLI is installed. The security scanner flags literal secrets, private
absolute paths, powerful tool grants, network access, and environment-variable
usage. Findings should be reviewed in context before changing a skill.

## Trace an agent run

Use `agilab agent-run` when a coding-agent action should leave product-style
evidence instead of only a tool-specific log:

```bash
agilab agent-run --agent codex --permission-level standard --label "Review current diff" --tag review --metadata branch=main -- codex review
```

The command writes a redacted `agilab.agent_run.v1` manifest plus local
`stdout.txt` and `stderr.txt` artifacts under `~/log/agents/<agent>/<run-id>/`.
It also writes an append-only `agilab.agent_trace.v1` event stream in
`agent_events.ndjson` and reserves `tool-output/` for large or structured tool
payloads.
Command arguments are redacted by default and represented by an argv hash;
environment override values passed with `--env KEY=VALUE` are also redacted
from the manifest. Pass `--include-command-args` only when the prompt/arguments
are safe to store. Output artifact files redact obvious secret assignments,
supported secret refs, and common standalone API-token patterns by default; pass
`--include-raw-output` only for safe local diagnostics.

Use `--tag` and `--metadata KEY=VALUE` for structured, non-secret context that
other tools can query later. Use `--protocol-adapter` for metadata-only bridge
labels such as `mcp`, `a2a`, `ag-ui`, or `fastapi`, and `--capability` for the
agent capability exercised by the run. These fields make protocol or
agent-as-tool experiments reviewable without adding those protocol stacks to the
base package.

Each manifest also carries a compact `events` timeline. It records the planned
or started run, command completion or timeout, and artifact write event so later
adapters can map the same evidence into streaming protocols.

Read previous run evidence from the CLI:

```bash
agilab agent-run list --agent codex --json
agilab agent-run list --tag review --metadata branch=main --protocol-adapter mcp --capability evidence-review --json
agilab agent-run handoff ~/log/agents/codex/<run-id>
agilab agent-run next ~/log/agents/codex/<run-id> --json
agilab agent-run context --tag review --metadata branch=main --limit 5 --json
agilab agent-run lineage <run-id> --json
agilab agent-run compare ~/log/agents/codex/<failed-run> ~/log/agents/codex/<follow-up-run> --json
agilab agent-run validate ~/log/agents/codex/<run-id> --json
```

The default read-only MCP bridge exposes the same agent-run evidence to external
coding agents without enabling shell execution:

Handoffs include 20 bounded recent events and explicit omission counts. Use
`read_agent_trace` with a manifest path and continuation cursor for bounded pages;
an incomplete tail has `has_more=false` and a separate `resume_cursor`. Run lists
support `offset`/`next_offset`, with stable timestamp/path ordering. MCP negotiates
versions per connection and includes typed structured results for clients using
2025-06-18 or later, while retaining text content for older clients.

Real command capture stores redacted prefixes capped at 8 MiB per stream and
omits lines over 64 KiB. Check `output_capture` before treating a log as complete.
The capture timeout also covers inherited pipes. Incomplete capture is a failed
evidence outcome even when the direct process exits successfully; detached
descendants and external side effects are outside the lifetime guarantee.

```bash
agilab-mcp list-tools --json
agilab-mcp call-tool read_agent_trace --arguments '{"manifest_path":"~/log/agents/codex/<run-id>","limit":20,"max_bytes":8192}' --json
agilab-mcp call-tool list_agent_runs --arguments '{"agent":"codex","tag":"review","metadata":{"branch":"main"},"limit":5}' --json
agilab-mcp call-tool summarize_agent_run --arguments '{"manifest_path":"~/log/agents/codex/<run-id>/agent_run_manifest.json"}' --json
agilab-mcp call-tool agent_handoff --arguments '{"manifest_path":"~/log/agents/codex/<run-id>"}' --json
agilab-mcp call-tool agent_next_actions --arguments '{"manifest_path":"~/log/agents/codex/<run-id>"}' --json
agilab-mcp call-tool agent_context --arguments '{"agent":"codex","tag":"review","metadata":{"branch":"main"},"limit":5}' --json
agilab-mcp call-tool agent_lineage --arguments '{"run_id":"<run-id>"}' --json
agilab-mcp call-tool compare_agent_runs --arguments '{"left_manifest":"~/log/agents/codex/<failed-run>","right_manifest":"~/log/agents/codex/<follow-up-run>"}' --json
agilab-mcp call-tool validate_agent_run --arguments '{"manifest_path":"~/log/agents/codex/<run-id>"}' --json
```

or from Python:

```python
from agilab.agent_run import list_agent_runs, trace_agent_run

result = trace_agent_run(
    ["codex", "review"],
    agent="codex",
    label="Review current diff",
    permission_level="standard",
    tags=("review",),
    metadata={"branch": "main"},
)

runs = list_agent_runs(agent="codex", limit=5)
```

Agent-run evidence now has a stable low-level contract:

- `agent_run_manifest.json` records command identity, redacted argv/env
  metadata, optional provider/model capability context, and artifact paths.
- `agent_trace_meta.json` describes the trace directory.
- `agent_events.ndjson` appends typed events such as `session_start`,
  `command_start`, `tool_start`, `tool_output`, `tool_done`,
  `permission_request`, `permission_resolved`, `compact`, `rewind`, and
  `session_end`.
- `agilab.agent_tool_safety` enforces permission tiers for command execution:
  `readonly`, `safe`, `standard`, and `operator`. Actual command execution is
  a `standard` action; destructive executable names and obvious destructive
  shell, Python, Git, Docker, Kubernetes, or package-manager command content are
  operator-gated and require an explicit confirmation token. This is an
  evidence and operator-confirmation guard, not a process sandbox.
- Agent provider defaults can be layered through `~/.agilab/agents/agents.json`
  and project-local `.agilab/agents.json` files. Use `--provider`, `--model`,
  and `--permission-level` for one-off CLI execution policy.

## CLI-first references

- [CLI-first workflow](../docs/CLI_FIRST_WORKFLOW.md)
- [Codex workflow](codex_workflow.md)
- [Aider workflow](aider_workflow.md)
- [OpenCode workflow](opencode_workflow.md)
- [Mistral Vibe workflow](vibe_workflow.md)

### Frozen agent experiments

Use `python -m agilab.agent_runtime.experiment prepare|run|verify` for explicitly
selected trusted Python inputs and a separate grader. Preparation freezes bytes;
execution binds the launched command, interpreter, checkpoints and outputs to
that plan. Give `run` an explicit `--attempt-id`; `--resume` only reuses matching
completed evidence and never replays an ambiguous native claim. See the public
agent-workflows page for the local-only scope and same-OS relocation limits.

Run `python -m agilab.agent_runtime.experiment_demo --output <new-directory>`
for the packaged baseline/candidate pilot. Both processes exit zero; independent
acceptance rejects the baseline. The comparison retains the failed attempt and
unknown model usage. Optional single-terminal Codex usage must come from a
verified registered output; missing cache counts remain unknown.

### Durable selected tasks

Prepare experiments under `<store>/experiments/<name>`, then use
`python -m agilab.agent_runtime.tasks register <store> <action> experiments/<name>`
and `submit <store> <action> <stable-request-key>`. Local `approve`/`deny` require
the exact `--plan-sha256` and observed `--attempt`; `start`/`cancel` bind that
attempt too. Read `status` without side effects. `reconcile` inspects retained
receipts after worker death; `resume` respects existing native claims, while
`retry` creates a fresh attempt requiring new approval. Both require `--attempt`.

Worker leases and immutable state revisions prevent competing workers from
replaying a claim. A released lease does not establish child termination;
missing termination evidence remains interrupted. Inspect external side effects
before explicit continuation. Approval records describe local operator actions,
not authenticated identities, and trusted Python is not sandboxed.

`agilab-mcp serve --task-root <store>` opts into registered task selection, status,
start and cancellation. Default tools stay read-only; MCP has no registration,
approval, arbitrary-command or retry tool. Start/cancel require the observed
attempt. `agent_quickstart` describes the enabled connection's exact boundary.
