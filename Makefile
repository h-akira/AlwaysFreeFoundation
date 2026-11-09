# Run from this directory, e.g. inside the config repository's platform/ submodule.
# Values are read from AFP_CONFIG_DIR (default: the parent of this directory).

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
AFP_CONFIG_DIR ?= $(abspath $(ROOT)/..)
export AFP_CONFIG_DIR

PYTHON ?= $(ROOT)/env/bin/python

.PHONY: help plan apply destroy outputs db-tunnel lint test env

help: ## Show targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

plan: ## Upload terraform/ at HEAD and run a Resource Manager plan job
	@$(ROOT)/scripts/stack.sh plan

apply: ## Apply the latest plan job (must be a plan of HEAD)
	@$(ROOT)/scripts/stack.sh apply

destroy: ## Destroy all resources of the stack (asks for confirmation)
	@$(ROOT)/scripts/stack.sh destroy

outputs: ## Print the stack outputs
	@$(ROOT)/scripts/stack.sh outputs

db-tunnel: ## Open a Bastion tunnel to the DB (foreground; Ctrl-C to close)
	@$(ROOT)/scripts/db-tunnel.sh

lint: ## Check formatting and validate terraform/; shellcheck if installed
	terraform -chdir=$(ROOT)/terraform fmt -recursive -check
	terraform -chdir=$(ROOT)/terraform init -backend=false -input=false > /dev/null
	terraform -chdir=$(ROOT)/terraform validate
	@if command -v shellcheck > /dev/null; then shellcheck $(ROOT)/scripts/*.sh; \
	else echo "shellcheck not installed; skipped"; fi

test: ## Run unit tests
	$(PYTHON) -m pytest -q $(ROOT)/tests

env: ## Create env/ with test dependencies
	python3 -m venv $(ROOT)/env
	$(ROOT)/env/bin/pip install -q pytest
