# Versioned skill evaluation receipts

Use this workflow when comparing a skill revision against an explicit fixture
cohort. It extends AGILAB agent-run evidence without adding a model service or
automatically executing a downloaded skill.

## Freeze the inputs

Choose one declared root containing the skill snapshot, fixture JSON, grader
file, plan, run output, and receipt. Put outputs outside the skill directory so
they do not change its frozen inventory. Snapshot every dependency needed to
interpret the evaluation; a single grader file does not fingerprint its imported
libraries. Record runtime versions and model names honestly (`unknown` or
`not_used` when appropriate). These values are declared, not host measurements.

Fixtures contain a nonempty `cases` list with unique ids and planned checks.
Each case can include additional prompts, inputs, and expected decisions; the
entire fixture file is hashed. For example:

```json
{"cases":[
  {"id":"in-scope","checks":["installation","routing","task","persistence"],"prompt":"An in-scope request","expected_skill":"your-skill"},
  {"id":"nearby","checks":["routing"],"prompt":"A nearby out-of-scope request","expected_skill":null}
]}
```

Implement a grader that checks real observations against those expectations.
Its stdout must contain exactly one JSON object using
`agilab.skill_evaluation_results.v1`, the plan's `sha256` as `plan_sha256`, and
case observations in this form:

```json
{"schema":"agilab.skill_evaluation_results.v1","plan_sha256":"<frozen plan digest>","cases":[
  {"id":"in-scope","checks":{"routing":{"status":"not_checked","evidence":"No host routing trace was captured."}}}
]}
```

Allowed statuses are `passed`, `failed`, `not_checked`, and
`insufficient_evidence`. Each reported check needs a short evidence description.
Keep diagnostic logs on stderr. Do not synthesize passing observations from
expected values alone. Installation checks need installation observations,
routing checks need host selection evidence, task checks need observed results,
and persistence checks need a saved result read back successfully.

## Produce and verify

From an AGILAB source environment, save a driver alongside the inputs and run it
with `uv --preview-features extra-build-dependencies run python driver.py`.
Adapt the grader command to its documented interface; this example assumes it
accepts the plan path and reads fixture expectations from that plan.

```python
from pathlib import Path
import sys

from agilab.agent_runtime.agent_run import trace_agent_run
from agilab.evidence.skill_evaluation import (
    create_evaluation_plan, create_evaluation_receipt,
    persist_evaluation, verify_evaluation_receipt,
)

root = Path(__file__).resolve().parent
plan = create_evaluation_plan(
    root=root, skill="skill", fixtures="fixtures.json", grader="grader.py",
    evaluator={
        "mode": "deterministic_fixture", "runtime": "python",
        "runtime_version": sys.version.split()[0], "model": "not_used",
    },
)
persist_evaluation(root, "plan.json", plan)
trace_agent_run(
    [sys.executable, "grader.py", "plan.json"], cwd=root,
    output_dir=root / "run", run_id="skill-evaluation",
    agent="deterministic-fixture", permission_level="standard",
    metadata={"skill_evaluation_plan_sha256": plan["sha256"]},
)
# Record failures too; do not return early on a nonzero agent return code.
receipt = create_evaluation_receipt(
    root=root, plan_path="plan.json", agent_run="run/agent_run_manifest.json",
)
persist_evaluation(root, "receipt.json", receipt)
print(verify_evaluation_receipt(root=root, receipt_path="receipt.json"))
```

Use `native_agent` and the actual declared runtime/model configuration for an
explicitly authorized host evaluation. This setting does not perform host
capability discovery or prove a native skill was selected. Capture that evidence
in the grader's observations. The helper uses the existing agent permission and
redaction behavior; no live model call is added to default tests.

For separate command invocations:

```bash
uv --preview-features extra-build-dependencies run python -m agilab.evidence.skill_evaluation --root /path/to/bundle plan --skill skill --fixtures fixtures.json --grader grader.py --mode deterministic_fixture --runtime python --runtime-version unknown --model not_used --output plan.json
# Execute the grader with trace_agent_run and the returned plan digest in metadata.
uv --preview-features extra-build-dependencies run python -m agilab.evidence.skill_evaluation --root /path/to/bundle record --plan plan.json --agent-run run/agent_run_manifest.json --output receipt.json
uv --preview-features extra-build-dependencies run python -m agilab.evidence.skill_evaluation --root /path/to/bundle verify receipt.json
```

`record` exits 0 for a passing evaluation, 1 for a persisted nonpassing evaluation,
and 2 for invalid inputs or publication failure. `verify` exits 0 for consistent
evidence even when the evaluation failed; inspect `evaluation_status`. Existing
plan and receipt paths are never overwritten. Use a new bundle for a new trial.

## Interpret the evidence

The plan freezes skill file inventory, fixtures, grader, declared evaluator
configuration, and the requested cohort. The receipt binds the unchanged plan
to terminal agent metadata and hashed stdout/stderr. Missing cases or checks stay
in the denominator as `not_checked`; malformed grader output is retained as a
failed receipt with insufficient observations. Invalid or changed source inputs,
missing artifact hashes, and unbound runs fail before receipt publication.

Verification re-reads the frozen files and reconstructs observations. Moving the
complete bundle preserves verification without rewriting native manifest bytes;
the receipt resolves its own relative artifact mapping against native hashes.
Native run manifests still contain local paths and command metadata, so review
their contents before sharing. A receipt is not an independent signature or a
proof that the frozen grader/skill executed: the plan digest associates the run
with a declared plan, while source execution and host routing require additional
observed evidence. Repository regressions validate the protocol with synthetic
fixtures; they do not establish model or skill quality.

The pattern adapts version-bound validation and separate observed outcomes from
[Pascal's skill validation](https://github.com/pascalorg/editor/blob/main/skills/VALIDATION.md).
The implementation and schemas are native AGILAB contracts.
