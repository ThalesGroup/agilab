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

# -------------------------
# PyPI publishing wrappers
# -------------------------
# Usage examples:
#   make publish REPO=pypi VERSION=0.8.23 LEAVE_MOST_RECENT=1 CLEANUP_USERNAME=alice CLEANUP_PASSWORD=***
#   make publish-test VERSION=0.8.23
#   make publish-dry REPO=testpypi

.PHONY: publish-help publish publish-pypi publish-test publish-testpypi publish-dry

REPO ?= pypi
VERSION ?=
LEAVE_MOST_RECENT ?= 1
SKIP_CLEANUP ?=
CLEANUP_TIMEOUT ?= 60
CLEANUP_USERNAME ?=
CLEANUP_PASSWORD ?=
TWINE_USER ?=
TWINE_PASS ?=
YANK_PREVIOUS ?=

publish-help:
	@echo "Publish to {testpypi,pypi} via tools/pypi_publish.py"
	@echo "Vars: REPO=pypi|testpypi VERSION=X.Y.Z[.postN] LEAVE_MOST_RECENT=1| (empty) SKIP_CLEANUP=1 CLEANUP_TIMEOUT=NN"
	@echo "      CLEANUP_USERNAME=acct CLEANUP_PASSWORD=pass TWINE_USER=__token__ TWINE_PASS=pypi-*** YANK_PREVIOUS=1"
	@echo "Examples:"
	@echo "  make publish VERSION=0.8.23 CLEANUP_USERNAME=acct CLEANUP_PASSWORD=pass"
	@echo "  make publish-test VERSION=0.8.23"
	@echo "  make publish-dry REPO=testpypi"

publish:
	@echo "> Publishing to $(REPO) …"
	@uv run python tools/pypi_publish.py --repo $(REPO) \
		$(if $(VERSION),--version $(VERSION),) \
		$(if $(LEAVE_MOST_RECENT),--leave-most-recent,) \
		$(if $(SKIP_CLEANUP),--skip-cleanup,) \
		$(if $(CLEANUP_TIMEOUT),--cleanup-timeout $(CLEANUP_TIMEOUT),) \
		$(if $(CLEANUP_USERNAME),--cleanup-username $(CLEANUP_USERNAME),) \
		$(if $(CLEANUP_PASSWORD),--cleanup-password $(CLEANUP_PASSWORD),) \
		$(if $(TWINE_USER),--twine-username $(TWINE_USER),) \
		$(if $(TWINE_PASS),--twine-password $(TWINE_PASS),) \
		$(if $(YANK_PREVIOUS),--yank-previous,)

publish-pypi: REPO=pypi
publish-pypi: publish

publish-test: REPO=testpypi
publish-test: publish

publish-testpypi: publish-test

publish-dry:
	@echo "> Dry run to $(REPO) …"
	@uv run python tools/pypi_publish.py --repo $(REPO) --dry-run \
		$(if $(VERSION),--version $(VERSION),)
