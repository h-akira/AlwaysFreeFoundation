# Run from this directory, e.g. inside the config repository's platform/ submodule.
# Values are read from AFP_CONFIG_DIR (default: the parent of this directory).

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
AFP_CONFIG_DIR ?= $(abspath $(ROOT)/..)
export AFP_CONFIG_DIR

PYTHON ?= $(ROOT)/env/bin/python

.PHONY: help plan apply destroy outputs base-plan base-apply base-outputs db-tunnel ssh platform command-result lint test test39 env

help: ## Show targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

plan: ## Main stack: upload terraform/ at HEAD and run a Resource Manager plan job
	@$(ROOT)/scripts/stack.sh main plan

apply: ## Main stack: apply the latest plan job (must be a plan of HEAD)
	@$(ROOT)/scripts/stack.sh main apply

destroy: ## Main stack: destroy all its resources (asks for confirmation)
	@$(ROOT)/scripts/stack.sh main destroy

outputs: ## Main stack: print the outputs
	@$(ROOT)/scripts/stack.sh main outputs

base-plan: ## Base stack (never destroyed): run a plan job
	@$(ROOT)/scripts/stack.sh base plan

base-apply: ## Base stack: apply the latest plan job
	@$(ROOT)/scripts/stack.sh base apply

base-outputs: ## Base stack: print the outputs
	@$(ROOT)/scripts/stack.sh base outputs

# TAG and ID, like CMD, go through the environment unexpanded.
platform: export AFP_TAG = $(value TAG)
platform: ## Point the VM at TAG of the platform code (pushed to GitHub) and wait for it to apply
	@[ -n "$$AFP_TAG" ] || { echo "usage: make platform TAG=<tag>" >&2; exit 2; }
	@$(ROOT)/scripts/platform.sh "$$AFP_TAG"

command-result: export AFP_COMMAND_ID = $(value ID)
command-result: ## Wait for a Run Command sent by make (ID=<command OCID>) and show its output
	@[ -n "$$AFP_COMMAND_ID" ] || { echo "usage: make command-result ID=<command OCID>" >&2; exit 2; }
	@$(ROOT)/scripts/run-command.sh result "$$AFP_COMMAND_ID" --wait

db-tunnel: ## Open a Bastion tunnel to the DB (foreground; Ctrl-C to close)
	@$(ROOT)/scripts/db-tunnel.sh

# CMD goes through the environment unexpanded, never through the recipe's shell.
ssh: export AFP_SSH_COMMAND = $(value CMD)
ssh: ## ssh into the VM through the Bastion; CMD='...' runs a command instead of a shell
	@$(ROOT)/scripts/vm-ssh.sh

lint: ## Check formatting and validate terraform/; shellcheck if installed
	terraform -chdir=$(ROOT)/terraform fmt -recursive -check
	for d in base main; do \
	  terraform -chdir=$(ROOT)/terraform/$$d init -backend=false -input=false > /dev/null && \
	  terraform -chdir=$(ROOT)/terraform/$$d validate || exit 1; \
	done
	@if command -v shellcheck > /dev/null; then shellcheck $(ROOT)/scripts/*.sh; \
	else echo "shellcheck not installed; skipped"; fi

test: ## Run unit tests
	$(PYTHON) -m pytest -q $(ROOT)/tests

test39: ## Run the tests of afp on Python 3.9, the VM's python3 (needs Docker)
	docker run --rm -v $(ROOT):/src:ro -w /src -e PYTHONDONTWRITEBYTECODE=1 python:3.9-slim \
	  sh -c 'pip install -q --root-user-action=ignore pytest && python -m pytest -q -p no:cacheprovider tests/test_afp.py'

env: ## Create env/ with test dependencies
	python3 -m venv $(ROOT)/env
	$(ROOT)/env/bin/pip install -q pytest
