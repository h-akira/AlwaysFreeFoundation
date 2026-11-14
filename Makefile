# Run from this directory, e.g. inside the config repository's platform/ submodule.
# Values are read from AFP_CONFIG_DIR (default: the parent of this directory).

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
AFP_CONFIG_DIR ?= $(abspath $(ROOT)/..)
export AFP_CONFIG_DIR

PYTHON ?= $(ROOT)/env/bin/python

.PHONY: help plan apply destroy outputs base-plan base-apply base-outputs db-tunnel ssh platform command-result deploy rollback backup lint test test39 env

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

# PROJECT and DIR, like CMD, go through the environment unexpanded.
deploy: export AFP_PROJECT_NAME = $(value PROJECT)
deploy: export AFP_PROJECT_DIR = $(value DIR)
deploy: ## Build the tagged HEAD of DIR for the VM, push it and deploy it as PROJECT (waits)
	@[ -n "$$AFP_PROJECT_NAME" ] && [ -n "$$AFP_PROJECT_DIR" ] || { echo "usage: make deploy PROJECT=<name> DIR=<repository>" >&2; exit 2; }
	@$(ROOT)/scripts/project.sh deploy "$$AFP_PROJECT_NAME" "$$AFP_PROJECT_DIR"

rollback: export AFP_PROJECT_NAME = $(value PROJECT)
rollback: ## Deploy the previous version of PROJECT again (images and compose; not the DB)
	@[ -n "$$AFP_PROJECT_NAME" ] || { echo "usage: make rollback PROJECT=<name>" >&2; exit 2; }
	@$(ROOT)/scripts/project.sh rollback "$$AFP_PROJECT_NAME"

backup: export AFP_PROJECT_NAME = $(value PROJECT)
backup: ## Dump the DB of PROJECT (or of every project without PROJECT) to the bucket (waits)
	@if [ -n "$$AFP_PROJECT_NAME" ]; then $(ROOT)/scripts/project.sh backup "$$AFP_PROJECT_NAME"; \
	else $(ROOT)/scripts/project.sh backup; fi

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
	  sh -c 'pip install -q --root-user-action=ignore pytest && python -m pytest -q -p no:cacheprovider tests/test_afp.py tests/test_afp_project.py'

env: ## Create env/ with test dependencies
	python3 -m venv $(ROOT)/env
	$(ROOT)/env/bin/pip install -q pytest
