---
agenticweb: "1"
description: "AGILAB is an open-source AI/ML workbench for reproducible experiments, notebook-to-app workflows, run evidence, proof capsules, and local agent evidence review."
updated: "2026-06-01"
organization:
  name: "AGILAB"
  website: "https://thalesgroup.github.io/agilab"
contacts:
  support: "https://github.com/ThalesGroup/agilab/issues"
  security: "https://github.com/ThalesGroup/agilab/security/policy"
links:
  - name: "docs"
    url: "https://thalesgroup.github.io/agilab"
    description: "Public documentation."
  - name: "github"
    url: "https://github.com/ThalesGroup/agilab"
    description: "Source repository and issue tracker."
  - name: "pypi"
    url: "https://pypi.org/project/agilab/"
    description: "Installable Python package."
  - name: "llms"
    url: "https://raw.githubusercontent.com/ThalesGroup/agilab/main/llms.txt"
    description: "Compact LLM/scraper discovery index."
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: false
  - name: "llms-full"
    url: "https://raw.githubusercontent.com/ThalesGroup/agilab/main/llms-full.txt"
    description: "Expanded LLM/scraper skill index."
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: false
trust:
  allowed_origins:
    - "https://thalesgroup.github.io/agilab"
    - "https://github.com/ThalesGroup/agilab"
    - "https://raw.githubusercontent.com/ThalesGroup/agilab/main"
    - "https://pypi.org"
    - "https://huggingface.co"
  marketplaces:
    - platform: "github"
      url: "https://github.com/ThalesGroup/agilab"
      listing_type: "organization"
    - platform: "pypi"
      url: "https://pypi.org/project/agilab/"
      listing_type: "api"
    - platform: "huggingface"
      url: "https://huggingface.co/spaces/jpmorard/agilab"
      listing_type: "agent"
capabilities:
  - kind: "docs"
    id: "quick-start"
    description: "Local install and first proof path for AGILAB."
    url: "https://thalesgroup.github.io/agilab/quick-start.html"
    status: "active"
    pricing_model: "free"
    auth_required: false
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: false
  - kind: "docs"
    id: "capability-map"
    description: "Job-to-route map with evidence and maturity boundaries."
    url: "https://thalesgroup.github.io/agilab/capability-map.html"
    status: "active"
    pricing_model: "free"
    auth_required: false
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: false
  - kind: "docs"
    id: "release-proof"
    description: "Public release evidence for package, docs, CI, coverage, and demo proof."
    url: "https://thalesgroup.github.io/agilab/release-proof.html"
    status: "active"
    pricing_model: "free"
    auth_required: false
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: false
  - kind: "docs"
    id: "agent-skills"
    description: "Repo-managed agent skills catalog and maintenance contract."
    url: "https://raw.githubusercontent.com/ThalesGroup/agilab/main/AGENT_SKILLS.md"
    status: "active"
    pricing_model: "free"
    auth_required: false
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: false
    format: "markdown"
  - kind: "data"
    id: "capability-manifest"
    description: "Machine-readable inventory of shipped public AGILAB surfaces."
    url: "https://raw.githubusercontent.com/ThalesGroup/agilab/main/agilab-capabilities.json"
    status: "active"
    pricing_model: "free"
    auth_required: false
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: false
    format: "json"
    schema: "https://raw.githubusercontent.com/ThalesGroup/agilab/main/agilab-capabilities.schema.json"
    license: "BSD-3-Clause"
  - kind: "data"
    id: "capability-rules"
    description: "Declarative semantic lint-rule metadata for AGILAB capabilities."
    url: "https://raw.githubusercontent.com/ThalesGroup/agilab/main/agilab-capability-rules.yml"
    status: "active"
    pricing_model: "free"
    auth_required: false
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: false
    format: "yaml"
    license: "BSD-3-Clause"
  - kind: "api"
    id: "first-proof-cli"
    description: "Run the packaged first proof and emit install/run evidence."
    url: "https://pypi.org/project/agilab/"
    status: "active"
    pricing_model: "free"
    auth_required: false
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: true
    schema: "https://raw.githubusercontent.com/ThalesGroup/agilab/main/agilab-capabilities.schema.json"
  - kind: "api"
    id: "workflow-validate-cli"
    description: "Validate stage, dependency, role, artifact-flow, and app-reference contracts without executing user code."
    url: "https://thalesgroup.github.io/agilab/capability-map.html"
    status: "active"
    pricing_model: "free"
    auth_required: false
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: false
  - kind: "mcp"
    id: "read-only-evidence"
    description: "Read-only MCP bridge for AGILAB run and agent-run evidence."
    url: "mcp://agilab/read-only-evidence"
    status: "active"
    pricing_model: "free"
    auth_required: false
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: false
    transport: "stdio"
  - kind: "api"
    id: "agent-run-evidence"
    description: "Wrap coding-agent actions with redacted manifests, traces, and local artifact pointers."
    url: "https://thalesgroup.github.io/agilab/agent-workflows.html"
    status: "active"
    pricing_model: "free"
    auth_required: false
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: true
  - kind: "ui"
    id: "streamlit-demo"
    description: "Hosted AGILAB Streamlit demo for the public workbench path."
    url: "https://huggingface.co/spaces/jpmorard/agilab"
    status: "beta"
    pricing_model: "free"
    auth_required: false
    permissions:
      read: true
      cite: true
      summarize: true
      train: false
      cache: true
      execute: true
x_generated_by:
  schema: "agilab.agenticweb_discovery.v1"
  tool: "tools/agenticweb_manifest.py"
  command: "python3 tools/agenticweb_manifest.py --apply"
  source_manifest: "agilab-capabilities.json"
  source_schema: "agilab.capabilities.v1"
  source_version: "2026.05.31.post1"
  boundary: "Discovery only: this file does not prove runtime success, external service reachability, security certification, or production readiness."
---

# AGILAB agentic web discovery

This file is generated from `agilab-capabilities.json`.
Use the capability manifest for the complete machine-readable AGILAB surface.

Validation:

```bash
python3 tools/agenticweb_manifest.py --check
```
