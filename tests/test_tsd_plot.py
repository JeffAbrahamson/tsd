"""Tests for the :mod:`tsd_plot` package."""

import datetime as dt

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pytest

matplotlib.use("Agg")

from tsd_plot import cli, main
from tsd_plot.series import (
    UsageInterval,
    automatic_smoothing_days,
    ewma_points,
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


@pytest.mark.parametrize(
    "options, days",
    [
        ([], [1, 2, 3, 4]),
        (["--start", "2024-01-02"], [2, 3, 4]),
        (["--end", "2024-01-03"], [1, 2, 3]),
        (["--start", "2024-01-02", "--end", "2024-01-03"], [2, 3]),
        (["--start", "2024-01-02", "--duration-days", "2"], [2, 3]),
        (["--end", "2024-01-03", "--duration-days", "2"], [2, 3]),
        (["--start", "2024-01-02", "--duration-days", "1"], [2]),
        (["--end", "2024-01-03", "--duration-days", "1"], [3]),
        (["--start", "2025-01-01"], []),
    ],
)
def test_date_range_selects_plotted_values(
    tmp_path, monkeypatch, options, days
):
    (tmp_path / "values").write_text(
        "2024-01-04 4\n2024-01-01 1\n2024-01-03 3\n2024-01-02 2\n"
    )
    monkeypatch.setenv("TSD", str(tmp_path))

    cli.main(["values", "--format", "line", *options])

    figure = plt.gcf()
    try:
        line = figure.axes[0].lines[0]
        assert list(line.get_xdata()) == [
            dt.date(2024, 1, day) for day in days
        ]
        assert list(line.get_ydata()) == days
    finally:
        plt.close(figure)


@pytest.mark.parametrize(
    "options, message",
    [
        (["--start", "2024-02-30"], "valid YYYY-MM-DD"),
        (["--end", "yesterday"], "valid YYYY-MM-DD"),
        (["--duration-days", "2"], "requires --start or --end"),
        (["--start", "2024-01-01", "--duration-days", "0"], "positive"),
        (["--end", "2024-01-01", "--duration-days", "-1"], "positive"),
        (["--end", "2024-01-01", "--duration-days", "1.5"], "invalid int"),
        (
            ["--start", "2024-01-02", "--end", "2024-01-01"],
            "on or before",
        ),
        (
            [
                "--start",
                "2024-01-01",
                "--end",
                "2024-01-02",
                "--duration-days",
                "2",
            ],
            "at most two",
        ),
        (["--start", "9999-12-31", "--duration-days", "2"], "supported dates"),
        (["--end", "0001-01-01", "--duration-days", "2"], "supported dates"),
    ],
)
def test_invalid_date_ranges(options, message, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["unused", *options])
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_date_range_crosses_leap_day():
    assert cli.resolve_date_range(dt.date(2024, 2, 28), None, 3) == (
        dt.date(2024, 2, 28),
        dt.date(2024, 3, 1),
    )


def test_date_range_precedes_sum_bins_and_statistics(
    tmp_path, monkeypatch, capsys
):
    for name in ("first", "second"):
        (tmp_path / name).write_text(
            "2024-01-01 100\n2024-01-02 2\n2024-01-03 3\n2024-01-04 4\n"
        )
    monkeypatch.setenv("TSD", str(tmp_path))
    cli.main(
        [
            "first",
            "second",
            "--start",
            "2024-01-02",
            "--duration-days",
            "3",
            "--sum",
            "--bin-width",
            "2",
            "--bin-function",
            "sum",
            "--std",
        ]
    )
    figure = plt.gcf()
    try:
        assert [p.get_height() for p in figure.axes[0].patches] == [10, 8]
        assert float(capsys.readouterr().out.split(":")[-1]) == pytest.approx(
            2**0.5
        )
    finally:
        plt.close(figure)


@pytest.mark.parametrize("view", ["usage", "both", "readings"])
def test_date_range_clips_usage_without_inventing_readings(
    tmp_path, monkeypatch, view
):
    (tmp_path / "meter").write_text("2024-01-01 10\n2024-01-11 30\n")
    monkeypatch.setenv("TSD", str(tmp_path))
    cli.main(
        [
            "meter",
            "--diff",
            "--view",
            view,
            "--no-smooth",
            "--start",
            "2024-01-04",
            "--end",
            "2024-01-06",
        ]
    )
    figure = plt.gcf()
    try:
        if view in {"readings", "both"}:
            assert all(
                not len(line.get_xdata()) for line in figure.axes[0].lines
            )
        if view in {"usage", "both"}:
            patch = figure.axes[-1].patches[0]
            assert patch.get_height() == 2
            assert patch.get_width() == 3
            assert patch.get_x() == matplotlib.dates.date2num(
                dt.date(2024, 1, 4)
            )
    finally:
        plt.close(figure)


def test_date_range_clipped_usage_amount_and_reset(tmp_path):
    (tmp_path / "meter").write_text(
        "2024-01-01 10\n2024-01-05 18\n2024-01-09 1\n"
    )
    series = load_plot_series("meter", "Meter", tmp_path, True)
    cli.restrict_date_range(series, dt.date(2024, 1, 3), dt.date(2024, 1, 6))
    assert series.usage_intervals == [
        UsageInterval(dt.date(2024, 1, 3), dt.date(2024, 1, 5), 4, 2, False),
        UsageInterval(dt.date(2024, 1, 5), dt.date(2024, 1, 7), 0, 0, True),
    ]
    assert series.raw_points == [(dt.date(2024, 1, 5), 18)]


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


@pytest.mark.parametrize(
    "plot_format, series_count",
    [("auto", 1), ("bar", 1), ("bar", 2), ("stacked", 2)],
)
def test_dense_bars_remain_visible(plot_format, series_count):
    """Subpixel bars must retain their colour when rendered."""
    points = [
        (dt.date(2020, 1, 1) + dt.timedelta(days=day), 70.0)
        for day in range(1000)
    ]
    series = [
        cli.SeriesData(label=str(index), filename=str(index), points=points)
        for index in range(series_count)
    ]
    with plt.rc_context({"figure.figsize": (6.4, 4.8), "figure.dpi": 100}):
        figure = cli.plot_series(series, plot_format, "Value", "Dense bars")
        try:
            figure.canvas.draw()
            pixels = np.asarray(figure.canvas.buffer_rgba())[:, :, :3]
            colour = np.array(figure.axes[0].patches[0].get_facecolor()[:3])
            matches = np.all(abs(pixels.astype(float) - colour * 255) < 2, 2)
            assert np.count_nonzero(matches) > 1000
        finally:
            plt.close(figure)


@pytest.fixture
def y_axis_data(tmp_path, monkeypatch):
    (tmp_path / "mass").write_text("2024-01-01 60\n2024-01-02 70\n")
    monkeypatch.setenv("TSD", str(tmp_path))
    yield tmp_path
    plt.close("all")


def test_ewma_uses_elapsed_days_and_initialises_from_first_reading():
    points = [
        (dt.date(2024, 1, 4), 8),
        (dt.date(2024, 1, 1), 0),
        (dt.date(2024, 1, 2), 8),
    ]

    smoothed = ewma_points(points, 1)

    assert [date.day for date, _ in smoothed] == [1, 2, 4]
    assert [value for _, value in smoothed] == pytest.approx([0, 4, 7])


def test_ewma_handles_fractional_days_missing_values_and_empty_input():
    points = [
        (dt.datetime(2024, 1, 1), 10),
        (dt.datetime(2024, 1, 1, 6), float("nan")),
        (dt.datetime(2024, 1, 1, 12), 20),
    ]

    assert [value for _, value in ewma_points(points, 0.5)] == [10, 15]
    assert ewma_points([], 1) == []


@pytest.mark.parametrize("halflife", [0, -1, float("inf"), float("nan")])
def test_ewma_rejects_invalid_halflife(halflife):
    with pytest.raises(ValueError, match="finite and positive"):
        ewma_points([], halflife)


def test_sidecar_selects_scatter_and_ewma(y_axis_data):
    (y_axis_data / "mass.cfg").write_text(
        "format=scatter\newma=true\newma_halflife_days=1\ny_range=data\n"
    )

    main(["mass"])

    axis = plt.gca()
    assert not axis.patches
    assert len(axis.collections) == 1
    assert axis.collections[0].get_offsets()[:, 1].tolist() == [60, 70]
    assert len(axis.lines) == 1
    assert axis.lines[0].get_ydata().tolist() == [60, 65]
    assert "EWMA (1 day half-life)" in axis.lines[0].get_label()
    assert axis.get_ylim() == pytest.approx((59.5, 70.5))


@pytest.mark.parametrize("plot_format", ["scatter", "line"])
@pytest.mark.parametrize(
    "options", [["--ewma"], [], ["--ewma", "--no-smooth"]]
)
def test_threshold_colours_boundaries_and_ewma(
    tmp_path, monkeypatch, plot_format, options
):
    (tmp_path / "mass").write_text(
        "2024-01-01 64\n2024-01-02 65\n2024-01-03 66\n"
        "2024-01-04 67\n2024-01-05 68\n"
    )
    monkeypatch.setenv("TSD", str(tmp_path))
    main(
        [
            "mass",
            "--format",
            plot_format,
            "--colour-below",
            "65",
            "--colour-above",
            "67",
            *options,
        ]
    )
    axis = plt.gca()
    low, high = axis.collections[-2:]
    assert low.get_offsets()[:, 1].tolist() == [64]
    assert high.get_offsets()[:, 1].tolist() == [68]
    alpha = 0.35 if plot_format == "scatter" and options == ["--ewma"] else 1
    assert low.get_facecolors()[0] == pytest.approx(
        matplotlib.colors.to_rgba("#009E73", alpha)
    )
    assert high.get_facecolors()[0] == pytest.approx(
        matplotlib.colors.to_rgba("#D55E00", alpha)
    )
    assert low.get_alpha() == high.get_alpha() == alpha
    assert "Below 65" in axis.get_legend_handles_labels()[1]
    assert "Above 67" in axis.get_legend_handles_labels()[1]
    if plot_format == "scatter":
        assert axis.collections[0].get_alpha() == alpha
        assert axis.collections[0].get_offsets()[:, 1].tolist() == [65, 66, 67]
    else:
        assert axis.lines[0].get_ydata().tolist() == [64, 65, 66, 67, 68]
        assert axis.lines[0].get_markevery() == [1, 2, 3]
    if options == ["--ewma"]:
        assert "EWMA" in axis.lines[-1].get_label()
    plt.close("all")


def test_threshold_sidecar_and_cli_override(y_axis_data):
    (y_axis_data / "mass.cfg").write_text(
        "format=scatter\ncolour_below=65\ncolour_above=67\n"
        "below_colour=purple\nabove_colour=orange\n"
    )
    main(["mass", "--colour-above", "75", "--below-colour", "cyan"])
    axis = plt.gca()
    assert len(axis.collections) == 2
    assert axis.collections[-1].get_facecolors()[0] == pytest.approx(
        matplotlib.colors.to_rgba("cyan")
    )
    assert "Above 75" not in axis.get_legend_handles_labels()[1]
    plt.close("all")
    main(["mass", "--no-threshold-colours", "--format", "bar"])
    assert len(plt.gca().patches) == 2
    assert not plt.gca().collections


@pytest.mark.parametrize(
    "options, message",
    [
        (["--colour-below", "nan"], "finite"),
        (["--colour-above", "inf"], "finite"),
        (["--colour-above", "oops"], "finite"),
        (["--below-colour", "not-a-colour"], "Invalid point colour"),
        (["--colour-below", "67", "--colour-above", "65"], "less than"),
        (["--colour-below", "65", "--colour-above", "65"], "less than"),
        (["--colour-below", "65"], "require --format"),
        (
            ["--colour-below", "65", "--diff", "--view", "readings"],
            "do not apply",
        ),
    ],
)
def test_invalid_threshold_options(y_axis_data, capsys, options, message):
    with pytest.raises(SystemExit):
        main(["mass", *options])
    assert message in capsys.readouterr().err


def test_threshold_sidecar_conflicts_and_disable(y_axis_data, capsys):
    (y_axis_data / "other").write_text("2024-01-01 64\n")
    (y_axis_data / "mass.cfg").write_text("colour_below=65\n")
    (y_axis_data / "other.cfg").write_text("colour_below=66\n")
    with pytest.raises(SystemExit):
        main(["mass", "other", "--format", "scatter"])
    assert "Conflicting colour_below" in capsys.readouterr().err
    main(["mass", "other", "--format", "scatter", "--colour-below", "61"])
    assert plt.gca().collections[-1].get_offsets()[:, 1].tolist() == [60]
    plt.close("all")
    (y_axis_data / "mass.cfg").write_text("colour_below=invalid\n")
    with pytest.raises(SystemExit):
        main(["mass"])
    assert "mass.cfg" in capsys.readouterr().err
    main(["mass", "other", "--no-threshold-colours"])


def test_thresholds_follow_aggregation(y_axis_data):
    (y_axis_data / "other").write_text("2024-01-01 10\n2024-01-02 30\n")
    main(
        [
            "mass",
            "other",
            "--sum",
            "--bin",
            "--bin-width",
            "week",
            "--format",
            "scatter",
            "--colour-above",
            "80",
        ]
    )
    assert plt.gca().collections[-1].get_offsets()[:, 1].tolist() == [85]


def test_thresholds_in_both_view_apply_to_usage(y_axis_data):
    main(
        [
            "mass",
            "--diff",
            "--view",
            "both",
            "--format",
            "scatter",
            "--colour-above",
            "9",
        ]
    )
    readings, usage = plt.gcf().axes
    assert "Above 9" not in readings.get_legend_handles_labels()[1]
    assert usage.collections[-1].get_offsets()[:, 1].tolist() == [10]


def test_data_y_range_defaults_to_scatter(y_axis_data):
    (y_axis_data / "mass.cfg").write_text("y_range=data\n")

    main(["mass"])

    assert len(plt.gca().collections) == 1
    assert not plt.gca().patches


@pytest.mark.parametrize(
    "options", [[], ["--format", "bar"], ["--format", "auto"]]
)
def test_explicit_format_overrides_data_range_scatter_default(
    y_axis_data, options
):
    (y_axis_data / "mass.cfg").write_text("y_range=data\nformat=bar\n")

    main(["mass", *options])

    assert len(plt.gca().patches) == 2
    assert not plt.gca().collections


def test_data_range_keeps_fixed_readings_style(y_axis_data):
    main(["mass", "--diff", "--view", "readings", "--y-range", "data"])

    assert len(plt.gca().lines) == 1
    assert plt.gca().lines[0].get_drawstyle() == "steps-post"


@pytest.mark.parametrize("option", ["--no-ewma", "--no-smooth"])
def test_cli_can_disable_sidecar_ewma(y_axis_data, option):
    (y_axis_data / "mass.cfg").write_text("format=scatter\newma=true\n")

    main(["mass", option, "--format", "bar"])

    assert len(plt.gca().patches) == 2
    assert not plt.gca().lines


def test_cli_can_enable_ewma_and_override_halflife(y_axis_data):
    (y_axis_data / "mass.cfg").write_text(
        "format=bar\newma=false\newma_halflife_days=30\n"
    )

    main(["mass", "--ewma", "--ewma-halflife-days", "1"])

    assert plt.gca().lines[0].get_ydata().tolist() == [60, 65]


def test_ewma_is_applied_after_sum_and_binning(y_axis_data):
    (y_axis_data / "other").write_text("2024-01-01 10\n2024-01-02 30\n")

    main(["mass", "other", "--sum", "--ewma", "--ewma-halflife-days", "1"])
    assert plt.gca().lines[0].get_ydata().tolist() == [70, 85]
    plt.close("all")
    main(["mass", "--bin", "--bin-width", "week", "--ewma"])
    assert plt.gca().lines[0].get_ydata().tolist() == [65]


def test_ewma_replaces_gaussian_and_uses_interval_midpoints(y_axis_data):
    (y_axis_data / "meter").write_text(
        "2024-01-01 10\n2024-01-03 30\n2024-01-05 70\n"
    )

    main(
        [
            "meter",
            "--diff",
            "--view",
            "both",
            "--ewma",
            "--ewma-halflife-days",
            "2",
        ]
    )

    readings, usage = plt.gcf().axes
    assert len(readings.lines) == 2
    assert readings.lines[-1].get_ydata().tolist() == [10, 20, 45]
    assert len(usage.lines) == 1
    assert usage.lines[0].get_ydata().tolist() == [10, 15]
    assert [date.day for date in usage.lines[0].get_xdata()] == [2, 4]


@pytest.mark.parametrize("view", ["readings", "both"])
def test_no_smooth_hides_ewma_on_both_panels(y_axis_data, view):
    main(["mass", "--diff", "--view", view, "--ewma", "--no-smooth"])
    assert all(
        "EWMA" not in line.get_label()
        for axis in plt.gcf().axes
        for line in axis.lines
    )


@pytest.mark.parametrize(
    "key, value",
    [
        ("format", "invalid"),
        ("ewma", "invalid"),
        ("ewma_halflife_days", "0"),
        ("ewma_halflife_days", "nan"),
    ],
)
def test_invalid_style_settings_report_the_sidecar(
    y_axis_data, capsys, key, value
):
    (y_axis_data / "mass.cfg").write_text(f"{key}={value}\n")
    with pytest.raises(SystemExit):
        main(["mass"])
    message = capsys.readouterr().err
    assert f"Invalid {key}" in message
    assert "mass.cfg" in message


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_invalid_cli_ewma_halflife(y_axis_data, capsys, value):
    with pytest.raises(SystemExit):
        main(["mass", "--ewma-halflife-days", value])
    assert "finite and positive" in capsys.readouterr().err


@pytest.mark.parametrize(
    "key, first, second, override",
    [
        ("format", "bar", "line", ["--format", "scatter"]),
        ("ewma", "true", "false", ["--ewma"]),
        ("ewma_halflife_days", "1", "2", ["--ewma-halflife-days", "3"]),
    ],
)
def test_style_conflicts_have_cli_overrides(
    y_axis_data, capsys, key, first, second, override
):
    (y_axis_data / "other").write_text("2024-01-01 10\n2024-01-02 30\n")
    (y_axis_data / "mass.cfg").write_text(f"{key}={first}\n")
    (y_axis_data / "other.cfg").write_text(f"{key}={second}\n")
    with pytest.raises(SystemExit):
        main(["mass", "other"])
    assert f"Conflicting {key}" in capsys.readouterr().err
    main(["mass", "other", *override])


@pytest.mark.parametrize(
    "options, limits",
    [
        ([], (59.5, 70.5)),
        (["--y-margin", "0.1"], (59, 71)),
        (["--y-margin", "0"], (60, 70)),
    ],
)
def test_y_range_from_sidecar(y_axis_data, options, limits):
    (y_axis_data / "mass.cfg").write_text("y_range=data\n")

    main(["mass", *options])

    assert plt.gca().get_ylim() == pytest.approx(limits)


@pytest.mark.parametrize("config", ["", "y_margin=0.1\n", "y_range=data\n"])
def test_y_range_auto_preserves_bar_baseline(y_axis_data, config):
    (y_axis_data / "mass.cfg").write_text(config)
    options = ["--y-range", "auto"] if "y_range" in config else []

    main(["mass", *options])

    assert plt.gca().get_ylim()[0] == 0


@pytest.mark.parametrize(
    "plot_format", ["auto", "bar", "line", "scatter", "interval"]
)
def test_y_range_combines_series_without_missing_zeroes(
    y_axis_data, plot_format
):
    (y_axis_data / "other").write_text("2024-01-03 80\n2024-01-04 100\n")
    (y_axis_data / "mass.cfg").write_text("y_range=data\ny_margin=0.1\n")

    main(["mass", "other", "--format", plot_format])

    assert plt.gca().get_ylim() == pytest.approx((56, 104))


def test_y_range_uses_stacked_endpoints(y_axis_data):
    (y_axis_data / "other").write_text("2024-01-01 80\n2024-01-02 100\n")

    main(["mass", "other", "--format", "stacked", "--y-range", "data"])

    assert plt.gca().get_ylim() == pytest.approx((54.5, 175.5))


def test_y_range_stacked_missing_values_do_not_add_zero(y_axis_data):
    (y_axis_data / "other").write_text("2024-01-03 80\n2024-01-04 100\n")

    main(["mass", "other", "--format", "stacked", "--y-range", "data"])

    assert plt.gca().get_ylim() == pytest.approx((58, 102))


@pytest.mark.parametrize(
    "options, limits",
    [
        (["--sum"], (68.5, 101.5)),
        (["--bin", "--bin-width", "week"], (61.75, 68.25)),
        (
            ["--bin", "--bin-width", "week", "--bin-function", "sum"],
            (123.5, 136.5),
        ),
    ],
)
def test_y_range_follows_aggregation(y_axis_data, options, limits):
    (y_axis_data / "other").write_text("2024-01-01 10\n2024-01-02 30\n")
    files = ["mass", "other"] if "--sum" in options else ["mass"]

    main([*files, *options, "--y-range", "data"])

    assert plt.gca().get_ylim() == pytest.approx(limits)


def test_y_range_fits_both_cumulative_panels(y_axis_data):
    (y_axis_data / "meter").write_text(
        "2024-01-01 10\n2024-01-03 30\n2024-01-05 70\n"
    )
    (y_axis_data / "meter.cfg").write_text("diff_type=1\ny_range=data\n")

    main(["meter", "--view", "both"])

    readings, usage = plt.gcf().axes
    assert readings.get_ylim() == pytest.approx((7, 73))
    assert usage.get_ylim() == pytest.approx((9.5, 20.5))


@pytest.mark.parametrize("value, padding", [(0, 0.05), (70, 3.5), (-70, 3.5)])
def test_y_range_constant_values_have_nonzero_span(
    y_axis_data, value, padding
):
    (y_axis_data / "constant").write_text(f"2024-01-01 {value}\n")

    main(["constant", "--y-range", "data", "--y-margin", "0"])

    assert plt.gca().get_ylim() == pytest.approx(
        (value - padding, value + padding)
    )


@pytest.mark.parametrize("values", [[], [float("nan"), float("inf")]])
def test_y_range_empty_or_nonfinite_values_keep_limits(values):
    figure, axis = plt.subplots()
    try:
        axis.plot(values)
        before = axis.get_ylim()
        cli.fit_y_axis_to_data(axis, 0.05)
        assert axis.get_ylim() == before
    finally:
        plt.close(figure)


@pytest.mark.parametrize(
    "key, first, second, override, expected",
    [
        ("y_range", "data", "auto", "data", (59.5, 70.5)),
        ("y_margin", "0.1", "0.2", "0.05", (59.5, 70.5)),
    ],
)
def test_y_settings_conflicts_require_cli_override(
    y_axis_data, capsys, key, first, second, override, expected
):
    (y_axis_data / "other").write_text("2024-01-01 60\n2024-01-02 70\n")
    (y_axis_data / "mass.cfg").write_text(f"{key}={first}\n")
    (y_axis_data / "other.cfg").write_text(f"{key}={second}\n")
    options = ["--y-range", "data"] if key == "y_margin" else []
    with pytest.raises(SystemExit):
        main(["mass", "other", *options])
    assert f"Conflicting {key}" in capsys.readouterr().err

    main(["mass", "other", *options, "--" + key.replace("_", "-"), override])

    assert plt.gca().get_ylim() == pytest.approx(expected)


@pytest.mark.parametrize(
    "key, value",
    [
        ("y_range", "invalid"),
        ("y_margin", "-1"),
        ("y_margin", "nan"),
        ("y_margin", "inf"),
        ("y_margin", "invalid"),
    ],
)
def test_invalid_sidecar_y_settings(y_axis_data, capsys, key, value):
    (y_axis_data / "mass.cfg").write_text(f"{key}={value}\n")

    with pytest.raises(SystemExit):
        main(["mass"])

    assert f"Invalid {key}" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "invalid"])
def test_invalid_cli_y_margin(y_axis_data, capsys, value):
    with pytest.raises(SystemExit):
        main(["mass", "--y-margin", value])
    assert "finite, non-negative" in capsys.readouterr().err


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


def test_single_cumulative_reading_only_supports_readings_view(
    tmp_path, monkeypatch, capsys
):
    """One reading is displayable but cannot define a usage interval."""
    (tmp_path / "water").write_text("2024-01-01 100\n", encoding="utf8")
    monkeypatch.setenv("TSD", str(tmp_path))

    cli.main(["water", "--diff", "--view", "readings"])
    with pytest.raises(SystemExit):
        cli.main(["water", "--diff", "--view", "usage"])

    assert "need at least two readings" in capsys.readouterr().err


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


def test_readings_view_shows_raw_markers_and_step_line(tmp_path):
    """Reading views should retain measurements and identify carried values."""
    (tmp_path / "meter").write_text(
        "2024-01-01 10\n2024-01-03 14\n2024-01-07 18\n", encoding="utf8"
    )
    series = [load_plot_series("meter", "meter", tmp_path, True)]

    figure = cli.plot_readings(series, "Reading", "Meter readings")

    axis = figure.axes[0]
    assert axis.lines[0].get_drawstyle() == "steps-post"
    assert list(axis.lines[0].get_ydata()) == [10.0, 14.0, 18.0]
    assert len(axis.collections) == 1


def test_both_view_uses_aligned_reading_and_usage_panels(tmp_path):
    """The combined view should keep raw and inferred values on separate axes."""
    (tmp_path / "meter").write_text(
        "2024-01-01 10\n2024-01-03 14\n2024-01-07 18\n", encoding="utf8"
    )
    series = [load_plot_series("meter", "meter", tmp_path, True)]

    figure = cli.plot_readings_and_usage(
        series,
        "auto",
        "Usage per day",
        "Meter",
        smooth=True,
        smooth_days=None,
    )

    assert len(figure.axes) == 2
    assert figure.axes[0].get_ylabel() == "Reading"
    assert figure.axes[1].get_ylabel() == "Usage per day"
    assert (
        figure.axes[0]
        .get_shared_x_axes()
        .joined(figure.axes[0], figure.axes[1])
    )


def test_usage_view_requires_cumulative_semantics(
    tmp_path, monkeypatch, capsys
):
    """Presentation options should not silently change input semantics."""
    (tmp_path / "temperature").write_text(
        "2024-01-01 10\n2024-01-03 14\n", encoding="utf8"
    )
    monkeypatch.setenv("TSD", str(tmp_path))

    with pytest.raises(SystemExit):
        cli.main(["temperature", "--view", "usage"])

    error = capsys.readouterr().err
    assert "requires cumulative inputs" in error
    assert "use --diff" in error


def test_readings_view_requires_cumulative_semantics(
    tmp_path, monkeypatch, capsys
):
    """A reading step must not be implied for ordinary direct values."""
    (tmp_path / "temperature").write_text(
        "2024-01-01 10\n2024-01-03 14\n", encoding="utf8"
    )
    monkeypatch.setenv("TSD", str(tmp_path))

    with pytest.raises(SystemExit):
        cli.main(["temperature", "--view", "readings"])

    error = capsys.readouterr().err
    assert "requires cumulative inputs" in error
    assert "use --diff" in error


def test_verbose_readings_view_describes_raw_reading(
    tmp_path, monkeypatch, capsys
):
    """Reading diagnostics should report raw data, not absent intervals."""
    (tmp_path / "water").write_text("2024-01-01 100\n", encoding="utf8")
    monkeypatch.setenv("TSD", str(tmp_path))

    cli.main(["water", "--diff", "--view", "readings", "--verbose"])

    output = capsys.readouterr().out
    assert "Loaded 1 series containing 1 points in total." in output
    assert "water (water): 1 points" in output
    assert "Date range: 2024-01-01" in output
    assert "Preparing to plot 1 points across 1 series." in output
    assert "usage trend width" not in output


def test_verbose_both_view_describes_readings_and_intervals(
    tmp_path, monkeypatch, capsys
):
    """Combined diagnostics should name both rendered point populations."""
    (tmp_path / "water").write_text(
        "2024-01-01 100\n2024-01-03 104\n2024-01-06 110\n",
        encoding="utf8",
    )
    monkeypatch.setenv("TSD", str(tmp_path))

    cli.main(["water", "--diff", "--view", "both", "--verbose"])

    output = capsys.readouterr().out
    assert "containing 3 readings and 2 usage intervals" in output
    assert "water (water): 3 readings, 2 usage intervals" in output
    assert "plot 3 readings and 2 usage intervals" in output


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
    assert "(default: auto)" in " ".join(captured.out.split())
    assert "--diff" in captured.out
    assert "--no-diff" in captured.out
    assert "--view" in captured.out
    assert "control how input values are interpreted" in captured.out
    assert "controls which representation is displayed" in captured.out
    assert "for the readings view, 'Usage per day' for usage" in " ".join(
        captured.out.split()
    )
