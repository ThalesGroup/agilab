SHELL := /bin/bash

# Path to the private agilab-apps repo (override on invocation if needed)
THALES_DIR ?= ../agilab-apps
# Path to this repo (agilab)
AGILAB_DIR ?= $(CURDIR)

.PHONY: docs-help docs-build docs-sync docs-publish docs-all

docs-help:
	@echo "Docs targets:"
	@echo "  make docs-build    # Build Sphinx site in agilab-apps (uses uv group=sphinx)"
	@echo "  make docs-sync     # Sync built site into agilab/docs/html"
	@echo "  make docs-publish  # Commit + push docs/html to origin"
	@echo "  make docs-all      # Build → Sync → Publish"
	@echo ""
	@echo "Overrides: make docs-all THALES_DIR=/path/to/agilab-apps"

docs-build:
	@[ -d "$(THALES_DIR)" ] || (echo "[docs] THALES_DIR not found: $(THALES_DIR)" >&2; exit 1)
	cd "$(THALES_DIR)" && uv run --group sphinx --dev docs/gen-docs.py

docs-sync:
	@[ -d "$(THALES_DIR)/docs/html" ] || (echo "[docs] Sphinx output not found in $(THALES_DIR)/docs/html. Run 'make docs-build' first." >&2; exit 1)
	@rsync -a --delete "$(THALES_DIR)/docs/html/" "$(AGILAB_DIR)/docs/html/"

docs-publish:
	@git -C "$(AGILAB_DIR)" add docs/html
	@GIT_AUTHOR_DATE="$$(date -u +"%Y-%m-%dT%H:%M:%SZ")" GIT_COMMITTER_DATE="$$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
		git -C "$(AGILAB_DIR)" commit -m "docs: sync Sphinx site from agilab-apps" || true
	@git -C "$(AGILAB_DIR)" push

docs-all: docs-build docs-sync docs-publish

