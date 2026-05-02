PYTHON ?= python3
PIPX ?= pipx
PREFIX ?= $(HOME)
PIPX_HOME ?= $(HOME)/.local/pipx
PIPX_BIN_DIR ?= $(HOME)/.local/bin
PIPX_STATE_HOME ?= $(HOME)/.local/state
SHELL_HELPER_DEST ?= $(PREFIX)/.dotfiles/bash/rc_post/tsd
export PYTHONPATH := src

.PHONY: all install lint test clean TAGS

all: test

TAGS:
	etags tests/test_tsd.py src/tsd/cli.py > TAGS

install:
	# Reuses the existing venv when already installed to avoid rebuilding
	# heavy dependencies (matplotlib, seaborn) on every run.  If
	# pyproject.toml dependencies change, run: pipx reinstall tsd
	PIPX_HOME="$(PIPX_HOME)" \
	PIPX_BIN_DIR="$(PIPX_BIN_DIR)" \
	XDG_STATE_HOME="$(PIPX_STATE_HOME)" \
	$(PIPX) install --editable . || $(PIPX) install --force --editable .
	install -Dm644 shell/tsd.bash "$(SHELL_HELPER_DEST)"

lint:
	pylint src/tsd/cli.py || true
	pylint tests/test_tsd.py || true

test:
	$(PYTHON) -m black --check --line-length 79 .
	./cflake src tests scripts
	pytest

clean:
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
