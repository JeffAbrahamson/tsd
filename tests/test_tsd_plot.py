"""Tests for the :mod:`tsd_plot` package."""

import datetime as dt

import matplotlib
import matplotlib.pyplot as plt
import pytest

matplotlib.use("Agg")

from tsd_plot import cli, main
from tsd_plot.series import (
    UsageInterval,
    automatic_smoothing_days,
    load_plot_series,
    read_series,
    smoothed_usage,
)


@pytest.fixture(autouse=True)
def _no_show(monkeypatch):
    """Prevent matplotlib from opening GUI windows during tests."""

    monkeypatch.setattr(plt, "show", lambda: None)


def test_parse_bin_width_keywords():
    assert cli.parse_bin_width("week") == 7
    assert cli.parse_bin_width("mo") == 30
    assert cli.parse_bin_width("year") == 365


def test_resolve_prefix_errors():
    with pytest.raises(cli.PrefixMatchError):
        cli.resolve_prefix("x", {"bar", "line"})
    with pytest.raises(cli.PrefixMatchError):
        cli.resolve_prefix("s", {"sum", "scatter"})


def test_sum_and_bin_series(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "tsd"
    data_dir.mkdir()
    (data_dir / "reading").write_text(
        "\n".join(
            [
                "2024-01-01\t1",
                "2024-01-02\t2",
                "2024-01-08\t3",
            ]
        ),
        encoding="utf8",
    )
    (data_dir / "exercise").write_text(
        "\n".join(
            [
                "2024-01-01\t4",
                "2024-01-03\t5",
                "2024-01-08\t6",
            ]
        ),
        encoding="utf8",
    )

    monkeypatch.setenv("TSD", str(data_dir))
    monkeypatch.delenv("TSD_DIR", raising=False)

    main(
        [
            "reading",
            "exercise:fitness",
            "--sum",
            "--bin",
            "--bin-width",
            "week",
            "--bin-function",
            "su",
            "--std",
            "--format",
            "bar",
            "--verbose",
        ]
    )

    captured = capsys.readouterr()
    assert "Loaded 2 series containing 6 points in total." in captured.out
    assert "Summing series across files by date." in captured.out
    assert (
        "Binning data with width 7 days using sum aggregation." in captured.out
    )
    assert "Total bins produced: 2" in captured.out
    std_lines = [
        line for line in captured.out.splitlines() if line.startswith("sum:")
    ]
    assert std_lines
    std_value = float(std_lines[0].split(":", 1)[1].strip())
    assert std_value == pytest.approx(2.12132034)


def test_plot_series_formats(tmp_path, monkeypatch):
    base_dir = tmp_path / "tsd"
    base_dir.mkdir()
    file_path = base_dir / "data"
    file_path.write_text("2024-05-01\t5\n2024-05-02\t7\n", encoding="utf8")
    monkeypatch.setattr(cli.Path, "home", lambda: tmp_path)

    series = [
        read_series("data", "data", base_dir),
    ]
    bar_fig = cli.plot_series(series, "bar", "Value", "Title")
    assert bar_fig.axes[0].get_ylabel() == "Value"

    line_fig = cli.plot_series(series, "line", "Label", "Line Title")
    assert line_fig.axes[0].get_title() == "Line Title"

    scatter_fig = cli.plot_series(series, "scatter", "Y", "Scatter")
    assert scatter_fig.axes[0].has_data()


def test_load_plot_series_uses_config_and_interval_midpoints(tmp_path):
    """Configured cumulative readings should become measurement intervals."""
    (tmp_path / "water").write_text(
        "2024-01-01 100\n2024-01-05 112\n2024-01-09 3\n",
        encoding="utf8",
    )
    (tmp_path / "water.cfg").write_text("diff_type=1\n", encoding="utf8")

    series = load_plot_series("water", "water", tmp_path, None)

    assert series.diff_enabled
    assert [item.rate for item in series.usage_intervals] == [3.0, 0.0]
    assert series.usage_intervals[1].reset
    assert series.points[0][0] == dt.datetime(2024, 1, 3)


def test_cumulative_series_requires_two_readings(tmp_path):
    """A single cumulative reading cannot define a usage interval."""
    (tmp_path / "water").write_text("2024-01-01 100\n", encoding="utf8")

    with pytest.raises(ValueError, match="needs at least two readings"):
        load_plot_series("water", "water", tmp_path, True)


def test_command_line_diff_overrides_series_config(tmp_path):
    """The explicit CLI choice should win in both directions."""
    (tmp_path / "meter").write_text(
        "2024-01-01 10\n2024-01-03 14\n", encoding="utf8"
    )
    (tmp_path / "meter.cfg").write_text("diff_type=1\n", encoding="utf8")

    raw = load_plot_series("meter", "meter", tmp_path, False)
    forced = load_plot_series("meter", "meter", tmp_path, True)

    assert not raw.diff_enabled
    assert len(raw.points) == 2
    assert forced.diff_enabled
    assert forced.points == [(dt.datetime(2024, 1, 2), 2.0)]


def test_main_honors_diff_config_and_uses_usage_label(
    tmp_path, monkeypatch, capsys
):
    """The chronological CLI should apply sidecar semantics by default."""
    (tmp_path / "meter").write_text(
        "2024-01-01 10\n2024-01-03 14\n", encoding="utf8"
    )
    (tmp_path / "meter.cfg").write_text("diff_type=1\n", encoding="utf8")
    monkeypatch.setenv("TSD", str(tmp_path))

    cli.main(["meter", "--verbose"])

    output = capsys.readouterr().out
    assert "differencing enabled (meter.cfg)" in output
    assert "Y-axis label: Usage per day" in output


def test_invalid_diff_config_is_reported(tmp_path):
    """Unknown diff types should fail instead of being treated as truthy."""
    (tmp_path / "meter").write_text(
        "2024-01-01 10\n2024-01-03 14\n", encoding="utf8"
    )
    (tmp_path / "meter.cfg").write_text("diff_type=maybe\n", encoding="utf8")

    with pytest.raises(ValueError, match="Invalid diff_type"):
        load_plot_series("meter", "meter", tmp_path, None)


def test_adaptive_smoothing_tracks_reading_density():
    """Sparse readings should select a wider trend than dense readings."""
    weekly = [
        UsageInterval(dt.date(2024, 1, 1), dt.date(2024, 1, 8), 7, 1, False),
        UsageInterval(dt.date(2024, 1, 8), dt.date(2024, 1, 15), 14, 2, False),
    ]
    sparse = [
        UsageInterval(dt.date(2024, 1, 1), dt.date(2024, 5, 1), 121, 1, False),
        UsageInterval(dt.date(2024, 5, 1), dt.date(2024, 9, 1), 246, 2, False),
    ]

    assert automatic_smoothing_days(weekly) == 7
    assert automatic_smoothing_days(sparse) == 122


def test_smoothing_ignores_reset_zero():
    """A meter replacement should not pull the inferred trend toward zero."""
    intervals = [
        UsageInterval(dt.date(2024, 1, 1), dt.date(2024, 1, 4), 9, 3, False),
        UsageInterval(dt.date(2024, 1, 4), dt.date(2024, 1, 7), 0, 0, True),
        UsageInterval(dt.date(2024, 1, 7), dt.date(2024, 1, 10), 9, 3, False),
    ]

    dates, values = smoothed_usage(intervals, 2)

    assert len(dates) == 9
    assert values == pytest.approx([3.0] * 9)


def test_auto_plot_shows_interval_observations_and_trend(tmp_path):
    """Automatic cumulative plots should retain intervals and observations."""
    (tmp_path / "meter").write_text(
        "2024-01-01 10\n2024-01-03 14\n2024-01-07 18\n", encoding="utf8"
    )
    series = [load_plot_series("meter", "meter", tmp_path, True)]

    figure = cli.plot_series(series, "auto", "Usage", "Meter")

    axis = figure.axes[0]
    assert len(axis.patches) == 2
    assert len(axis.collections) == 1
    assert len(axis.lines) == 1


def test_grouped_cumulative_bars_align_on_inferred_days(tmp_path):
    """Different reading schedules should share a daily grouped-bar grid."""
    (tmp_path / "first").write_text(
        "2024-01-01 10\n2024-01-05 18\n", encoding="utf8"
    )
    (tmp_path / "second").write_text(
        "2024-01-01 20\n2024-01-03 26\n2024-01-05 34\n",
        encoding="utf8",
    )
    series = [
        load_plot_series("first", "first", tmp_path, True),
        load_plot_series("second", "second", tmp_path, True),
    ]

    dates, value_map = cli.prepare_plot_data(series)
    figure = cli.plot_series(series, "bar", "Usage", "Grouped usage")

    assert dates == [dt.date(2024, 1, day) for day in range(1, 5)]
    assert value_map == {
        "first": {dt.date(2024, 1, day): 2.0 for day in range(1, 5)},
        "second": {
            dt.date(2024, 1, 1): 3.0,
            dt.date(2024, 1, 2): 3.0,
            dt.date(2024, 1, 3): 4.0,
            dt.date(2024, 1, 4): 4.0,
        },
    }
    assert [patch.get_height() for patch in figure.axes[0].patches] == [
        2.0,
        2.0,
        2.0,
        2.0,
        3.0,
        3.0,
        4.0,
        4.0,
    ]


def test_sum_and_bin_expand_usage_across_covered_days(tmp_path):
    """Chronological aggregation should use inferred daily rates."""
    (tmp_path / "first").write_text(
        "2024-01-01 10\n2024-01-05 18\n", encoding="utf8"
    )
    (tmp_path / "second").write_text(
        "2024-01-01 20\n2024-01-05 24\n", encoding="utf8"
    )
    series = [
        load_plot_series("first", "first", tmp_path, True),
        load_plot_series("second", "second", tmp_path, True),
    ]

    total = cli.sum_series(series)
    binned = cli.bin_series(series[0], 7, sum)

    assert total.points == [
        (dt.date(2024, 1, day), 3.0) for day in range(1, 5)
    ]
    assert binned.points == [
        (dt.date(2023, 12, 28), 6.0),
        (dt.date(2024, 1, 4), 2.0),
    ]


def test_compute_std_nan():
    assert str(cli.compute_std([1.0])) == "nan"
    assert cli.compute_std([1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_bin_series_reducer():
    series = cli.SeriesData(
        label="demo",
        filename="demo",
        points=[
            (dt.date(2024, 1, 1), 1.0),
            (dt.date(2024, 1, 2), 2.0),
            (dt.date(2024, 1, 8), 4.0),
        ],
    )
    binned = cli.bin_series(series, 7, cli.BIN_FUNCTIONS["mean"])
    assert len(binned.points) == 2
    assert binned.points[0][1] == pytest.approx(1.5)
    assert binned.points[1][1] == pytest.approx(4.0)


def test_help_mentions_overview_groups_and_defaults(capsys):
    """Help output should summarize intent, groups, and defaults."""

    with pytest.raises(SystemExit):
        cli.main(["--help"])

    captured = capsys.readouterr()
    assert (
        "Plot TSD time series as ordinary date-based charts." in captured.out
    )
    assert "input and grouping:" in captured.out
    assert "plot appearance:" in captured.out
    assert "statistics:" in captured.out
    assert "diagnostics:" in captured.out
    assert "(default: mean)" in captured.out
    assert "(default: auto)" in captured.out
    assert "--diff" in captured.out
    assert "--no-diff" in captured.out
    assert "Defaults to 'Usage per day'" in captured.out
