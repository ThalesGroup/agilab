# Codex Power Improvements

## Top Impact Improvements

1. Ask for an outcome, not only an explanation.
   Use prompts like: "Inspect the code and artifacts, explain the real behavior, patch if needed, then verify."

2. Ask for reusable artifacts.
   Request a `.md`, JSON config, validation script, comparison table, or UI text instead of stopping at a chat answer.

3. Batch related questions into one structured request.
   Instead of many small follow-ups, ask for one audit covering behavior, parameters, tradeoffs, and recommended settings.

## Best Prompt Upgrades

- Replace "what does this mean?" with:
  "Inspect it in the codebase, explain the actual behavior, and tell me whether it is a docs issue, naming issue, or real bug."

- Replace "give me parameters" with:
  "Create matched configs for fair comparison, separate output dirs, and a short protocol to compare results."

- Replace "why are these files different?" with:
  "Compare the artifacts, trace the export code paths, identify the root cause, and patch it if the mismatch is semantic."

## Most Useful Default Prompt

Use this as a general high-leverage prompt:

> Inspect the code and current artifacts first, explain the real behavior, identify any mismatch, then produce either a patch, a reusable config/doc, or a validation script.

## One Extra Lever You Are Not Using Much

If you want maximum throughput, explicitly ask for parallel investigation:

> Use sub-agents: one checks the artifact, one checks the exporter code, one checks the pipeline config, then merge the findings.
