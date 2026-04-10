# Session Fix Quality Checklist

Use this when you need the shortest operational form of the skill.

## Ordered Checklist

1. Freeze the current bug.
2. Name the primary failing layer.
3. Ask where the bad value first enters the system.
4. Require two competing theories.
5. Reset after a real pivot.
6. Require extra justification before changing shared core.
7. Ask for the minimal retained fix.

## Reset Triggers

Reset the session when:

- one blocker was resolved and a new one appeared
- the subsystem changed
- the model already proposed one broad rejected fix
- the thread became long, compacted, or multi-topic

## Prompt Template

> Ignore previously resolved blockers. Analyze only the current failure. Classify
> it as symptom, visible mechanism, and bug origin. Identify the first file or
> step that introduces the bad value. Give two competing theories, the evidence
> that would discriminate between them, and the smallest retained fix we should
> keep in main if the leading theory is confirmed.
