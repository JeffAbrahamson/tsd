"""Tests for :mod:`tsd.today`."""

from datetime import date

import pytest

from tsd import today


def write_series(series_dir, name, days):
    """Write a series with value 1 on each supplied day."""

    text = "".join(f"{day}\t1\n" for day in days)
    (series_dir / name).write_text(text, encoding="utf-8")


def configure(monkeypatch, tmp_path, prefixes=""):
    """Configure an isolated series directory and XDG config."""

    series_dir = tmp_path / "series"
    series_dir.mkdir()
    config_home = tmp_path / "config"
    config_dir = config_home / "tsd"
    config_dir.mkdir(parents=True)
    config = f"series_dir={series_dir}\n"
    if prefixes:
        config += f"habit_equivalence_prefixes={prefixes}\n"
    (config_dir / "config").write_text(config, encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.delenv("TSD_DIR", raising=False)
    return series_dir


def test_lists_selected_day_and_warns_for_missing_habit(
    monkeypatch, tmp_path, capsys
):
    series_dir = configure(monkeypatch, tmp_path)
    write_series(
        series_dir,
        "daily",
        [f"2026-08-{day:02d}" for day in range(3, 8)],
    )
    write_series(series_dir, "present", ["2026-08-08"])

    assert today.main(["2026-08-08"]) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        "present                         2026-08-08       1.0\n"
    )
    assert captured.err.startswith("\n  -> Warning: habitual entry 'daily'")
    assert "habitual entry 'daily' is absent" in captured.err
    assert "present on 5 of the preceding 5 days" in captured.err


def test_threshold_is_strictly_more_than_k(monkeypatch, tmp_path, capsys):
    series_dir = configure(monkeypatch, tmp_path)
    write_series(
        series_dir,
        "four-of-five",
        [f"2026-08-{day:02d}" for day in range(4, 8)],
    )

    assert today.main(["2026-08-08"]) == 0
    assert capsys.readouterr().err == ""

    assert today.main(["-k", "3", "2026-08-08"]) == 0
    assert capsys.readouterr().err.startswith(
        "\n  -> Warning: habitual entry 'four-of-five'"
    )


def test_prefixes_combine_series_and_longest_prefix_wins(
    monkeypatch, tmp_path, capsys
):
    series_dir = configure(monkeypatch, tmp_path, "foo-,foo-special-")
    names = ["foo-bar", "foo-baz", "foo-buz", "foo-bar", "foo-baz"]
    for offset, name in enumerate(names, start=3):
        path = series_dir / name
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(old + f"2026-08-{offset:02d}\t1\n", encoding="utf-8")
    write_series(
        series_dir,
        "foo-special-item",
        [f"2026-08-{day:02d}" for day in range(3, 8)],
    )

    assert today.main(["2026-08-08"]) == 0

    error = capsys.readouterr().err
    assert error.startswith("\n  -> Warning: habitual entry 'foo-*'")
    assert "\n  -> Warning: habitual entry 'foo-special-*'" in error


def test_equivalent_entry_today_satisfies_habit(monkeypatch, tmp_path, capsys):
    series_dir = configure(monkeypatch, tmp_path, "foo-")
    write_series(
        series_dir,
        "foo-old",
        [f"2026-08-{day:02d}" for day in range(3, 8)],
    )
    write_series(series_dir, "foo-new", ["2026-08-08"])

    assert today.main(["2026-08-08"]) == 0
    assert capsys.readouterr().err == ""


def test_no_check_and_verbose(monkeypatch, tmp_path, capsys):
    series_dir = configure(monkeypatch, tmp_path)
    write_series(
        series_dir,
        "daily",
        [f"2026-08-{day:02d}" for day in range(3, 8)],
    )

    assert (
        today.main(["--no-habit-threshold-check", "--verbose", "2026-08-08"])
        == 0
    )
    assert capsys.readouterr().err == "Habit threshold check disabled.\n"

    assert today.main(["--verbose", "2026-08-08"]) == 0
    error = capsys.readouterr().err
    assert "history=2026-08-03..2026-08-07" in error
    assert "prefixes=(none)" in error


def test_tsd_dir_overrides_config(monkeypatch, tmp_path, capsys):
    configure(monkeypatch, tmp_path)
    override = tmp_path / "override"
    override.mkdir()
    write_series(override, "from-environment", ["2026-08-08"])
    monkeypatch.setenv("TSD_DIR", str(override))

    assert today.main(["2026-08-08"]) == 0
    assert capsys.readouterr().out.startswith("from-environment")


@pytest.mark.parametrize(
    "args,message",
    [
        (["-n", "0"], "must be greater than zero"),
        (["-k", "5", "-n", "5"], "must be non-negative and less than"),
        (["not-a-day"], "use YYYY-MM-DD or an integer offset"),
    ],
)
def test_invalid_arguments(args, message, capsys):
    with pytest.raises(SystemExit) as exc_info:
        today.main(args)
    assert exc_info.value.code == 2
    assert message in capsys.readouterr().err


def test_relative_day():
    assert today.parse_day("-4", today=date(2026, 8, 8)) == date(2026, 8, 4)


def test_help_names_habit_options(capsys):
    with pytest.raises(SystemExit) as exc_info:
        today.main(["--help"])
    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert output.startswith("usage: tsd-today")
    assert "--habit-history-days" in output
    assert "--habit-threshold-days" in output
    assert "--no-habit-threshold-check" in output
