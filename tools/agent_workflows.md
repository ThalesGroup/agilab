# Agent Workflows for AGILAB

This repository is prepared for four executable agent paths, plus one catalog-compatible path:

- **Claude**: repo skills under [`.claude/skills`](../.claude/skills/README.md)
- **Codex**: repo skills under [`.codex/skills`](../.codex/skills/README.md) and the wrapper in [codex_workflow.sh](codex_workflow.sh)
- **Aider**: repo config in [`.aider.conf.yml`](../.aider.conf.yml) and the wrapper in [aider_workflow.sh](aider_workflow.sh)
- **OpenCode**: project config in [opencode.json](../opencode.json), agents under [`.opencode/agents`](../.opencode/agents), and the wrapper in [opencode_workflow.sh](opencode_workflow.sh)
- **Continue**: catalog-compatible through AGENT_SKILLS.md / `llms.txt`; AGILAB does not ship a Continue wrapper or project config yet

The public agent surface is summarized in [AGENT_SKILLS.md](../AGENT_SKILLS.md)
and mirrored for scraper/LLM discovery through [llms.txt](../llms.txt) and
[llms-full.txt](../llms-full.txt). The README badge contract is:

- **Skills**: the reviewed skill count
- **Standard**: Agent Skills style `SKILL.md` runbooks
- **Works with**: Codex, Claude Code, Aider, and OpenCode

Use the short repo contract in [AGENT_CONVENTIONS.md](../AGENT_CONVENTIONS.md)
for local coding agents with smaller context windows. Use [AGENTS.md](../AGENTS.md)
for the full AGILAB runbook when the task touches risky surfaces.

## Resource preflight

Before heavy agent-assisted analysis, model training, large data work, or cluster
experiments, write a resource snapshot:

```bash
python tools/resource_snapshot.py --output resource_snapshot.json --json
```

The JSON uses schema `agilab.resource_snapshot.v1` and records CPU, memory,
disk, GPU backends, and execution recommendations. Attach it to run evidence
when resource constraints explain scheduler, autoscale, or model choices.

## Skill security scan

Changed repo-managed skills are scanned locally. Run the local check before
pushing skill changes:

```bash
python tools/skill_security_scan.py --changed-only --fail-on critical
```

For a full local pass:

```bash
python tools/skill_security_scan.py --roots .claude/skills .codex/skills --fail-on critical
```

The scanner is a review aid. It flags literal secrets, private absolute paths,
powerful tool grants, network access, and environment-variable usage; findings
should be reviewed in context before changing a skill.

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
```

The read-only MCP bridge exposes the same agent-run evidence to external
coding agents without enabling shell execution:

```bash
agilab-mcp list-tools --json
agilab-mcp call-tool list_agent_runs --arguments '{"agent":"codex","tag":"review","metadata":{"branch":"main"},"limit":5}' --json
agilab-mcp call-tool summarize_agent_run --arguments '{"manifest_path":"~/log/agents/codex/<run-id>/agent_run_manifest.json"}' --json
agilab-mcp call-tool agent_handoff --arguments '{"manifest_path":"~/log/agents/codex/<run-id>"}' --json
agilab-mcp call-tool agent_next_actions --arguments '{"manifest_path":"~/log/agents/codex/<run-id>"}' --json
agilab-mcp call-tool agent_context --arguments '{"agent":"codex","tag":"review","metadata":{"branch":"main"},"limit":5}' --json
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
