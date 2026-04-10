---
name: agilab-coding-agent-postmortem
description: Investigate AGILAB coding-agent incidents, separate symptom from mechanism, export a reusable case-study corpus, and draft a publishable article when the evidence supports a broader lesson about session quality, abstraction level, or debugging trajectory.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-10
---

# Coding-Agent Postmortem Skill (AGILAB)

Use this skill when the user wants to:

- understand why one coding-agent session produced a weaker fix than another
- compare two rollouts or chat traces for the same bug
- turn an AGILAB debugging incident into a reusable “cas d’ecole”
- export the incident into a folder with raw artifacts, copied source, patches, and analysis
- draft a publishable article from the incident

This skill is for postmortem and publication work around coding-agent behavior, not
for fixing the bug itself.

If the user wants to improve a live debugging session before the fix is found,
use `agilab-session-fix-quality` instead.

## Core Rule

Do not collapse the story into “the model is bad” or “the plan tier is better”
unless the evidence really supports that claim.

Prefer this sequence:

1. identify the exact failing layer
2. separate sequential bugs
3. compare wrong diagnosis vs retained diagnosis
4. only then discuss model/session factors

## Incident Workflow

### 1. Freeze the scope

Start by naming the exact incident under study:

- the app or workflow
- the first visible failure
- the later visible failure if the bug chain changed
- the sessions or rollouts being compared

If the incident has multiple failures in sequence, split them explicitly. Treat
“the error after the first fix” as a new analysis object.

### 2. Collect the minimum useful corpus

Prefer a compact, reviewable artifact set:

- rollout JSONL or exported chat transcript
- raw chat export if available
- final retained commits or patches
- the source files actually touched by the retained fix
- any runbook/skill/docs changes that encode the lesson afterward

Do not dump the whole repo into the case-study folder.

### 3. Compare diagnosis layers

For each important session, extract:

- what the session thought the current blocker was
- which mechanism it blamed first
- which fix it proposed
- whether that fix was a workaround, a retained fix, or a dead end

The most important question is:

- did the session stay at the right abstraction level?

Typical bad drift patterns:

- symptom-level patching instead of mechanism-level diagnosis
- treating a second bug as if it were still the first one
- redesigning shared core before proving the leak point
- overfitting to the visible failing command instead of the first source of the bad value

### 4. Distinguish three outcome classes

- `Correct retained fix`: the fix that should stay in main
- `Operational workaround`: makes the local case pass but is broader than needed
- `Wrong diagnosis`: attacks the wrong layer entirely

Do not merge those classes in the write-up.

### 5. Evaluate the session, not only the model

When comparing two sessions, check:

- how long the session had already run
- how many topic pivots happened before the bug
- whether compaction occurred repeatedly
- whether the session started from a clean problem statement
- whether the comparison run is truly comparable or only a later review session

If the evidence only shows “different session quality”, say that. Do not
overclaim “Plus vs Pro” or similar plan effects without a true apples-to-apples
comparison.

## Export Package

When the user wants a reusable case-study folder, create:

- `README.md`: what the package is and how to read it
- `analysis/<name>.md`: mechanism-level analysis
- `patches/`: final retained patches
- `source/`: copied source files relevant to the incident
- `source_manifest.txt`
- `patch_manifest.txt`

Keep the package navigable. The package should be readable without reopening the
entire repository history.

## Article Workflow

When the user wants a public-facing article, first decide whether the incident
supports a broader lesson. Good public angles include:

- same model, different fix quality
- symptom vs mechanism
- abstraction level drift
- long-session degradation
- why a passing workaround is not the same as a good retained fix

If the broader lesson is weak, say so and keep the output as an internal memo.

For article writing:

1. Start with the concrete bug, not with generic AI claims.
2. Make the setup self-contained for an external reader:
   - what AGILAB is in one sentence
   - what the relevant workflow terms mean
   - what the two bug phases were
   - what a central tool or command means when the article depends on it
     (`uv`, `uv --project`, `uv pip install -e`, etc.)
3. State the real agent/runtime metadata whenever the corpus supports it:
   - coding-agent runtime or CLI version
   - model version
   - reasoning depth / effort
4. Explain why the wrong fix was plausible.
5. Show the concrete wrong fix and the retained fix, ideally with short diffs.
6. Show what changed when the retained diagnosis became better.
7. End with operational guidance the reader can apply with the same model.

Keep the model/session claims proportionate to the evidence.

Read `references/article-checklist.md` when drafting a public article.

If the article is comparative, include a short methodology or bias-control
section explaining:

- which artifacts were used
- what was truly held constant
- what was not fully controlled
- why the result is an engineering postmortem rather than a strict scientific benchmark

If the article relies on Python packaging or install-tool details that a general
reader may not know, add one short explainer section before the deep dive:

- define the one or two commands that keep appearing in the logs
- explain why the visible command is not automatically the owning layer
- if relevant, contrast the retained command path with the rejected workaround
  path

## Recommended Framing

Strong framing patterns:

- `same error log, same model, one good fix and one bad one`
- `the wrong fix was plausible but at the wrong abstraction level`
- `session quality mattered more than nominal model capability`
- `the better fix was narrower, not just smarter`

Weak framing patterns:

- `AI failed`
- `Pro is better than Plus`
- `the model hallucinated`

Use the weak patterns only if the corpus really proves them.

## Figure Guidance

When the article aims to be memorable or broadly readable, add at least one
figure. Prefer repo-native SVG.

Default figure choices:

- `comparison figure`
  - same inputs at the top
  - weaker path on the left
  - better path on the right
  - concrete bad fix vs retained fix
- `timeline figure`
  - first failure
  - second visible failure
  - wrong proposal
  - retained diagnosis
  - retained fix

Semantic rule:

- the figure must explain something the prose alone makes harder to scan
- do not add decorative architecture art
- label the abstraction change explicitly:
  - `symptom`
  - `mechanism`
  - `owning layer`

Browser-safe rule:

- prefer browser-safe fonts (`Arial`, `Helvetica`, sans-serif`) for publication
  figures unless there is a strong reason not to
- do not pack boxed figure text with the same density you would accept in prose
- if a figure starts relying on many code pills, shorten the copy or split the
  explanation across prose plus figure instead
- route arrows through gutters, not through text corridors or card interiors
- validate SVG readability with at least two renderers when possible
  (`rsvg-convert` plus Quick Look or browser-adjacent rendering)
- treat full-width top banners and bottom takeaway bars as high-risk blocks and
  give them more vertical slack than ordinary cards
- treat title-plus-pill-plus-body cards as high-risk stacks too; reserve explicit
  zones for each layer before adjusting copy
- keep annotation labels such as `visible error line` in whitespace lanes rather
  than touching the explanatory cards
- if an annotation label sits between a right-side explainer card and a lower panel,
  rebalance that whole corridor rather than nudging only the label or only the arrow
- if a figure still crowds after one cleanup pass, stop doing local nudges and
  rebalance the whole figure region or split the figure

If a diagram is needed, also use `svg-diagrams`.

## AGILAB-Specific Guardrails

- If the incident touches shared core, explain why the retained fix is better
  scoped than the workaround.
- If the case involves installer behavior, preserve the distinction between:
  - app dependency contract issues
  - shared installer/path handling issues
  - broader source-mode workflow redesign
- If the public article mentions AGILAB, include a link to the public docs or
  repo when appropriate:
  - `https://thalesgroup.github.io/agilab/`
  - `https://github.com/ThalesGroup/agilab`

## Output Quality Bar

- The analysis must say what the wrong session got wrong.
- The article must not read like a chat reply or an internal ticket comment.
- The article should be self-contained for a reader who does not know the repo.
- The article should mention the real coding-agent stack when the corpus supports it.
- The article should show the concrete wrong fix, not only describe it abstractly.
- The article should include at least one high-signal figure when readability would benefit.
- If the article depends on `uv` or similar tooling details, it should briefly explain them for non-specialists.
- If a figure is revised to reduce one block, the sibling blocks and callout bars
  should be rechecked so the fix does not simply move the crowding elsewhere.
- If a figure has already triggered repeated readability complaints, a rendered-image
  inspection should happen before saying the SVG is fixed.
- If the evidence does not support a comparative claim, downgrade the claim.
- Prefer one sharp lesson over a broad but weak taxonomy.
