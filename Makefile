PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
VENV_PYTHON ?= python3
PIPX ?= pipx
PREFIX ?= $(HOME)
PIPX_HOME ?= $(HOME)/.local/pipx
PIPX_BIN_DIR ?= $(HOME)/.local/bin
PIPX_STATE_HOME ?= $(HOME)/.local/state
SHELL_HELPER_DEST ?= $(PREFIX)/.dotfiles/bash/rc_post/tsd
export PYTHONPATH := src

.PHONY: all install venv lint test clean TAGS

all: test

TAGS:
	etags tests/test_tsd.py src/tsd/cli.py > TAGS

venv:
	$(VENV_PYTHON) -m venv .venv
	.venv/bin/python -m pip install --editable '.[dev]'

install: venv
	PIPX_HOME="$(PIPX_HOME)" \
	PIPX_BIN_DIR="$(PIPX_BIN_DIR)" \
	XDG_STATE_HOME="$(PIPX_STATE_HOME)" \
	$(PIPX) install --force --editable .
	install -Dm644 shell/tsd.bash "$(SHELL_HELPER_DEST)"

lint:
	pylint src/tsd/cli.py || true
	pylint tests/test_tsd.py || true

test:
	$(PYTHON) -m black --check --line-length 79 .
	$(PYTHON) ./cflake src tests scripts
	$(PYTHON) -m pytest

clean:
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
