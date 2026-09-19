# Agent experiment pilot

## Example Class

**Executable agent experiment.** Runs the packaged trusted Python fixture and
independent grader through the lean runtime, without an apps workspace.

Compare two implementations of an experiment against an independent acceptance
check. The baseline treats missing measurements as zero; the candidate excludes
them. Both commands exit successfully. Their acceptance outcomes differ.

```bash
uv --preview-features extra-build-dependencies run python -m agilab.agent_runtime.experiment_demo --output /tmp/agilab-agent-pilot
uv --preview-features extra-build-dependencies run python -m agilab.agent_runtime.experiment verify /tmp/agilab-agent-pilot/candidate attempts/pilot/receipt.json
```

Choose a new output directory for each pilot. Inputs are the packaged
`resources/agent_experiment/inputs.json` cohort and explicitly selected Python
files. Each variant writes `plan.json`, `snapshot/`, native command/grader evidence,
launch and output checkpoints, `attempts/pilot/workspace/result.json`, and
`attempts/pilot/receipt.json`. The paired `comparison.json` retains both attempts,
including the failed baseline. Receipt integrity and acceptance are separate.

To adapt one thing, copy the four packaged files to a local directory and change
one measurement in `inputs.json`. Prepare a new plan for each entrypoint with
`python -m agilab.agent_runtime.experiment prepare --help`. The grader still uses
the frozen cohort; a changed plan needs new execution evidence.

This is an executable deterministic fixture, not a live model evaluation. No model
tokens are observed; missing usage is null, never zero. The comparison API can
read one terminal Codex JSONL usage report from a registered output artifact.
Multiple or incomplete reports remain unmeasured. This is provider-reported local
evidence, not billing attestation.

The pilot uses the lean agent runtime rather than cluster workers, so it needs
neither `AGI.run` nor an initialized apps workspace. It executes trusted Python
in copied directories using the current interpreter. It does not sandbox code,
freeze installed dependencies, restrict networking, or prove producer identity.
Complete bundles can be relocated on the same operating system; cross-OS path
translation is not supported. Original source availability is reported separately.
