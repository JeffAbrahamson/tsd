"""Tests for how the Makefile decides to prepare the virtual environment.

These use dry runs with a stand-in interpreter, so they download nothing.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REBUILD = "-m venv --clear"
INSTALL = "-m pip install"
CHECKS = "-m black --check"

pytestmark = pytest.mark.skipif(
    shutil.which("make") is None, reason="make is not installed"
)


@pytest.fixture
def checkout(tmp_path):
    for name in ("Makefile", "pyproject.toml"):
        shutil.copy(REPO_ROOT / name, tmp_path / name)
    os.utime(tmp_path / "pyproject.toml", (1000, 1000))
    return tmp_path


def add_venv(checkout, tools_import=True):
    """Add an interpreter that runs, and may or may not find the tools."""
    bin_dir = checkout / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    status = 0 if tools_import else 1
    python.write_text(
        f'#!/bin/sh\ncase "$2" in *black*) exit {status};; esac\nexit 0\n'
    )
    python.chmod(0o755)


def add_stamp(checkout, mtime=2000):
    stamp = checkout / ".venv" / ".installed"
    stamp.touch()
    os.utime(stamp, (mtime, mtime))


def dry_run(checkout, *args):
    ignored = {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "PYTHON"}
    env = {k: v for k, v in os.environ.items() if k not in ignored}
    result = subprocess.run(
        ["make", "-n", *args],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_missing_venv_is_created_before_checks(checkout):
    output = dry_run(checkout, "test")
    assert output.index(REBUILD) < output.index(INSTALL)
    assert output.index(INSTALL) < output.index(CHECKS)


def test_default_goal_prepares_venv(checkout):
    assert REBUILD in dry_run(checkout)


def test_upgraded_python_is_rebuilt_despite_fresh_stamp(checkout):
    add_venv(checkout, tools_import=False)
    add_stamp(checkout)
    assert REBUILD in dry_run(checkout, "test")


def test_dangling_interpreter_is_rebuilt_despite_fresh_stamp(checkout):
    add_venv(checkout)
    add_stamp(checkout)
    python = checkout / ".venv" / "bin" / "python"
    python.unlink()
    python.symlink_to("/nonexistent/python")
    assert REBUILD in dry_run(checkout, "test")


def test_current_venv_is_left_alone(checkout):
    add_venv(checkout)
    add_stamp(checkout)
    output = dry_run(checkout, "test")
    assert INSTALL not in output
    assert REBUILD not in output
    assert CHECKS in output


def test_newer_pyproject_reinstalls_without_rebuilding(checkout):
    add_venv(checkout)
    add_stamp(checkout, mtime=500)
    output = dry_run(checkout, "test")
    assert INSTALL in output
    assert REBUILD not in output


def test_working_venv_without_stamp_is_not_cleared(checkout):
    add_venv(checkout)
    output = dry_run(checkout, "test")
    assert INSTALL in output
    assert REBUILD not in output


def test_venv_python_does_not_invalidate_working_venv(checkout):
    add_venv(checkout)
    add_stamp(checkout)
    output = dry_run(checkout, "test", "VENV_PYTHON=python3.other")
    assert INSTALL not in output
    assert REBUILD not in output


@pytest.mark.parametrize("python", [".venv/bin/python", "/other/python"])
def test_explicit_python_skips_preparation(checkout, python):
    output = dry_run(checkout, "test", f"PYTHON={python}")
    assert INSTALL not in output
    assert REBUILD not in output
    assert f"{python} {CHECKS}" in output


@pytest.mark.parametrize("goal", ["venv", "install"])
def test_explicit_goal_reinstalls_into_current_venv(checkout, goal):
    add_venv(checkout)
    add_stamp(checkout)
    output = dry_run(checkout, goal)
    assert INSTALL in output
    assert REBUILD not in output


def test_goals_sharing_a_run_prepare_venv_once(checkout):
    output = dry_run(checkout, "venv", "test")
    assert output.count(REBUILD) == 1
    assert output.count(INSTALL) == 1
