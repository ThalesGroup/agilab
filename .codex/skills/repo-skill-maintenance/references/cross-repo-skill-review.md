# Cross-Repository Skill Review

A useful exchange closes a gap in the destination workflow. Adding more skill
directories is not itself an improvement. Screen names and descriptions first,
then read the selected instructions, references, helper dependencies, and
destination guidance before changing anything. Distinguish catalog screening
from a detailed content review in the report.

## Decisions from the AGILAB / Tokki exchange

| Practice | Destination owner | Benefit and adaptation |
| --- | --- | --- |
| Evidence that survives a review handoff | `agilab-deep-audit` | Bind the reviewed revision and artifacts, independently verify incoming claims, and report unfinished review coverage. Use ordinary reports and existing tests. |
| Learning a procedure from completed work | `codex-session-learning` | Separate useful failure cases, unvalidated proposals, and procedures backed by completed checks. Generalize across coding agents. |
| Benchmark boundaries and generated input domains | Tokki's regression skill | Distinguish fixed-workload timing from scaling, and review callers when fixture defaults broaden. Adapt examples to Tokki's native runtime and wrapper tests. |
| SVG delivery surface and embedded-size review | Tokki's SVG skill | Choose the intended presentation surface first and inspect the composed export, while preserving Tokki's own SVG tooling and size constraints. |

These changes improve existing skills. They do not import another repository's
release commands, private execution helpers, product claims, or provider-specific
orchestration. AGILAB application, Streamlit, cluster, and PyPI instructions stay
with the repository that owns those workflows.

## Ownership and licensing

- Identify the real skill directory before editing. AGILAB uses
  `.claude/skills` as canonical and generates its `.codex/skills` mirror. Tokki
  uses `.codex/skills` as canonical, with provider aliases. Do not copy one
  repository's layout assumptions into the other.
- For copied or adapted material, record the upstream URL, exact revision,
  reviewed file paths, applicable license, and required notices. Preserve the
  original license for imported material; the destination license is not a
  substitute. Retain any upstream provenance notes carried by the source.
- For proprietary material without redistribution permission, keep source
  text, schemas, scripts, and private evidence out of a public destination.
  Independently written guidance for general practices can still be useful;
  clearly state that no executable integration or source import was made.
- Keep generated mirrors under their existing synchronizer. Do not create a
  new `.tokki/skills` tree in AGILAB or overwrite installer-managed home skills.

## Acceptance check

1. Name a concrete task where the new guidance changes what the agent verifies.
2. Test the guidance against a counterexample: a stale review, interrupted run,
   misleading benchmark, or readable SVG that becomes illegible in its export.
3. Check every referenced file and command against the destination repository.
   A source helper that is unavailable there must not become a required step.
4. Run the destination's skill validation, discovery, mirror, and privacy checks.
   Run targeted code tests only when a helper or behavioral contract changes.
5. Report what was adopted, already covered, or left repository-specific, and
   distinguish validated instructions from measured productivity gains. This
   exchange does not establish a token-saving or execution-speed percentage.
