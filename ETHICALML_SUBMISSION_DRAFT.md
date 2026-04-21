# EthicalML Submission Draft

This file is the working draft for a future submission to:

- `awesome-production-machine-learning`
- URL: https://github.com/EthicalML/awesome-production-machine-learning

## Gate check

Do **not** submit yet unless all of these are true:

- AGILAB has at least **500 GitHub stars**
- the repo has been actively maintained in the last 12 months
- the project fits **one** section only
- the one-line description is crisp and specific

Reference:

- EthicalML contributing guide:
  https://raw.githubusercontent.com/EthicalML/awesome-production-machine-learning/master/CONTRIBUTING.md

## Recommended section

Best fit today:

- **Model Training and Orchestration**

Why:

- AGILAB's clearest differentiator is workflow orchestration from local execution to distributed workers.
- It also has service features, but the strongest primary category is orchestration.
- EthicalML asks contributors not to list tools in more than one section.

## Candidate list entry

`AGILAB` - Open-source platform for reproducible AI/ML workflows, from Streamlit or CLI entrypoints to isolated local and distributed workers, with orchestration, service mode, and health gates.

Keep the final wording short. The maintainers prefer concise descriptions.

## Pre-submission checklist

- [ ] 500+ GitHub stars
- [ ] active commits/releases in the last 12 months
- [ ] README clearly explains the tool in under one minute
- [ ] one polished demo exists
- [ ] docs include a "start here" path
- [ ] the project still fits one section better than any other
- [ ] alphabetical placement checked in the target section

## Draft PR body

Title:

`Add AGILAB to Model Training and Orchestration`

Body:

```md
Hi maintainers,

I'd like to propose adding **AGILAB** to the **Model Training and Orchestration** section.

Repository:
- https://github.com/ThalesGroup/agilab

Suggested entry:
- `AGILAB` - Open-source platform for reproducible AI/ML workflows, from Streamlit or CLI entrypoints to isolated local and distributed workers, with orchestration, service mode, and health gates.

Why this section:
- AGILAB's main value is orchestrating reproducible AI/ML workflows from local development to distributed worker execution.
- It also includes service mode and health checks, but orchestration is the clearest primary category.

The repository is actively maintained and meets the contribution requirements.

Thank you for reviewing.
```

## Draft issue note if section fit is unclear

Use this only if AGILAB evolves enough that `Deployment and Serving` becomes a better fit.

```md
Hi maintainers,

Before opening a PR, I'd like to confirm the best section for **AGILAB**:
https://github.com/ThalesGroup/agilab

It provides reproducible AI/ML workflows from local and Streamlit-driven development to distributed execution, plus service mode and health gates for long-lived workers.

My current guess is **Model Training and Orchestration**, but I wanted to confirm the best fit before preparing the PR.

Thanks.
```

## What to avoid in the submission

- do not oversell AGILAB as solving every MLOps category
- do not propose multiple sections
- do not open a long debate about taxonomy
- do not submit before the star threshold is met
