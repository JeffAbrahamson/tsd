VENV_BIN_PYTHON := .venv/bin/python
PYTHON ?= $(VENV_BIN_PYTHON)
VENV_PYTHON ?= python3
VENV_STAMP := .venv/.installed
# Importing the tools also catches a Python upgrade, which leaves
# .venv/bin/python running while the packages stay behind in the old
# version's directory.
VENV_WORKS := $(shell PYTHONPATH=src $(VENV_BIN_PYTHON) \
	-c 'import black, pyflakes, pytest' 2>/dev/null && echo yes)
PIPX ?= pipx
PREFIX ?= $(HOME)
PIPX_HOME ?= $(HOME)/.local/pipx
PIPX_BIN_DIR ?= $(HOME)/.local/bin
PIPX_STATE_HOME ?= $(HOME)/.local/state
SHELL_HELPER_DEST ?= $(PREFIX)/.dotfiles/bash/rc_post/tsd
export PYTHONPATH := src

.PHONY: all install venv lint test clean TAGS FORCE

all: test

TAGS:
	etags tests/test_tsd.py src/tsd/cli.py > TAGS

venv: $(VENV_STAMP)

# Keep a working environment when only pyproject.toml changed, so that a
# failed installation cannot cost us dependencies that are still valid.
$(VENV_STAMP): pyproject.toml $(if $(VENV_WORKS),,FORCE) \
		$(if $(filter venv install,$(MAKECMDGOALS)),FORCE)
	$(if $(VENV_WORKS),,$(VENV_PYTHON) -m venv --clear --upgrade-deps .venv)
	$(VENV_BIN_PYTHON) -m pip install --editable '.[dev]'
	touch $@

FORCE:

install: venv
	PIPX_HOME="$(PIPX_HOME)" \
	PIPX_BIN_DIR="$(PIPX_BIN_DIR)" \
	XDG_STATE_HOME="$(PIPX_STATE_HOME)" \
	$(PIPX) install --force --editable .
	install -Dm644 shell/tsd.bash "$(SHELL_HELPER_DEST)"

lint:
	pylint src/tsd/cli.py || true
	pylint tests/test_tsd.py || true

# An explicit PYTHON selects an environment the caller manages.
test: $(if $(filter file,$(origin PYTHON)),$(VENV_STAMP))
	$(PYTHON) -m black --check --line-length 79 .
	$(PYTHON) ./cflake src tests scripts
	$(PYTHON) -m pytest

clean:
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
