"""Command line interface for plotting TSD data files."""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import statistics
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence, Tuple

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import seaborn as sns

from .series import (
    SeriesData,
    automatic_smoothing_days,
    daily_usage_points,
    load_plot_series,
    smoothed_usage,
)

BIN_KEYWORDS = {
    "week": 7,
    "month": 30,
    "year": 365,
}

BIN_FUNCTIONS: Dict[str, Callable[[Iterable[float]], float]] = {
    "mean": statistics.fmean,
    "median": statistics.median,
    "sum": sum,
}

PLOT_FORMATS = {"auto", "bar", "interval", "line", "scatter", "stacked"}
PLOT_VIEWS = {"auto", "both", "readings", "usage"}

EPOCH = _dt.date(1970, 1, 1)
HELP_OVERVIEW = """\
Plot TSD time series as ordinary date-based charts.

This command is for reading one or more TSD files and plotting them against
calendar time. It can show raw points directly or reduce them into bins before
plotting. Use it for general time-series inspection; use `tsd-season-plot`
when you want repeated-period views that emphasise seasonality.

`--diff` and `--no-diff` control how input values are interpreted: either as
cumulative readings whose changes imply usage, or as direct values. `--view`
controls which representation is displayed after that interpretation. For
example, a cumulative series can be shown as its raw readings, its inferred
usage intervals, or both.

Option groups:
  input and grouping   choose files, summation, and binning behaviour
  plot appearance      choose plot format, title, and axis labeling
  statistics           request derived numeric summaries
  diagnostics          print resolved settings and data summaries
"""


class PrefixMatchError(ValueError):
    """Raised when an argument does not match available prefixes."""


def resolve_prefix(value: str, options: Iterable[str]) -> str:
    """Resolve *value* against *options* treating prefixes as valid."""

    normalized = value.lower()
    matches = [option for option in options if option.startswith(normalized)]
    if not matches:
        raise PrefixMatchError(f"Unknown option: {value!r}")
    if len(matches) > 1:
        raise PrefixMatchError(
            f"Ambiguous option {value!r}; matches {', '.join(matches)}"
        )
    return matches[0]


def parse_bin_width(value: str) -> int:
    """Parse the ``--bin-width`` argument."""

    normalized = value.lower()
    for keyword, days in BIN_KEYWORDS.items():
        if keyword.startswith(normalized):
            return days
    try:
        width = int(value)
    except ValueError as exc:  # pragma: no cover - defensive branch
        raise argparse.ArgumentTypeError(
            "Bin width must be an integer or a known keyword"
        ) from exc
    if width <= 0:
        raise argparse.ArgumentTypeError("Bin width must be positive")
    return width


def parse_filespec(value: str) -> Tuple[str, str]:
    """Split *value* into filename and legend label."""

    if ":" in value:
        filename, label = value.split(":", 1)
        if not label:
            label = filename
        return filename, label
    return value, value


def resolve_tsd_dir() -> Path:
    """Return the directory holding TSD files."""

    for env_name in ("TSD", "TSD_DIR"):
        value = os.environ.get(env_name)
        if value:
            return Path(value).expanduser()
    return Path.home() / "tsd"


def sum_series(series: Sequence[SeriesData]) -> SeriesData:
    """Combine series by summing points with matching dates."""

    aggregated: Dict[_dt.date, float] = {}
    for entry in series:
        for date, value in daily_usage_points(entry):
            aggregated[date] = aggregated.get(date, 0.0) + value
    points = sorted(aggregated.items(), key=lambda item: item[0])
    return SeriesData(label="sum", filename="sum", points=points)


def bin_series(
    series: SeriesData,
    width: int,
    reducer: Callable[[Iterable[float]], float],
) -> SeriesData:
    """Bin series data using *width* days and *reducer* aggregation."""

    grouped: Dict[_dt.date, List[float]] = {}
    for date, value in daily_usage_points(series):
        offset = (date - EPOCH).days % width
        bucket = date - _dt.timedelta(days=offset)
        grouped.setdefault(bucket, []).append(value)
    binned_points = [
        (bucket, reducer(values)) for bucket, values in sorted(grouped.items())
    ]
    return SeriesData(
        label=series.label, filename=series.filename, points=binned_points
    )


def ensure_sorted(series: Sequence[SeriesData]) -> List[SeriesData]:
    """Return a new list of series with points sorted by date."""

    return [
        SeriesData(
            label=item.label,
            filename=item.filename,
            points=item.sorted_points(),
            raw_points=list(item.raw_points),
            usage_intervals=list(item.usage_intervals),
            diff_enabled=item.diff_enabled,
            diff_source=item.diff_source,
        )
        for item in series
    ]


def compute_std(values: Sequence[float]) -> float:
    """Return the sample standard deviation, ``nan`` if undefined."""

    if len(values) < 2:
        return float("nan")
    try:
        return statistics.stdev(values)
    except statistics.StatisticsError:  # pragma: no cover - defensive
        return float("nan")


def format_title(args: argparse.Namespace, filenames: Sequence[str]) -> str:
    """Determine plot title from arguments and filenames."""

    if args.title:
        return args.title
    return " ".join(filenames)


def prepare_plot_data(
    series_list: Sequence[SeriesData],
) -> Tuple[List[_dt.date], Dict[str, Dict[_dt.date, float]]]:
    """Create lookup tables for plotting grouped bar charts."""

    all_dates = sorted(
        {
            date
            for series in series_list
            for date, _ in daily_usage_points(series)
        }
    )
    value_map: Dict[str, Dict[_dt.date, float]] = {}
    for series in series_list:
        mapping = dict(daily_usage_points(series))
        value_map[series.label] = mapping
    return all_dates, value_map


def plot_series(
    series_list: Sequence[SeriesData],
    plot_format: str,
    y_label: str,
    title: str,
    *,
    smooth: bool = True,
    smooth_days: float | None = None,
    ax: plt.Axes | None = None,
    finalize: bool = True,
) -> plt.Figure:
    """Plot the prepared series using matplotlib and seaborn."""

    sns.set_theme(style="whitegrid")
    if ax is None:
        fig, ax = plt.subplots()
    else:
        fig = ax.figure

    if not series_list:
        ax.set_title(title)
        ax.set_ylabel(y_label)
        ax.set_xlabel("Date")
        if finalize:
            fig.autofmt_xdate()
            fig.tight_layout()
        return fig

    locator = mdates.AutoDateLocator()
    formatter = mdates.ConciseDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)

    effective_format = plot_format
    if plot_format == "auto":
        effective_format = (
            "interval"
            if any(item.diff_enabled for item in series_list)
            else "bar"
        )

    if effective_format == "stacked" or (
        effective_format == "bar" and len(series_list) > 1
    ):
        all_dates, value_map = prepare_plot_data(series_list)
        date_nums = mdates.date2num(all_dates)
        width = 0.8
        if effective_format == "stacked":
            bottoms = [0.0] * len(all_dates)
            for series in series_list:
                values = [
                    value_map[series.label].get(date, 0.0)
                    for date in all_dates
                ]
                ax.bar(
                    date_nums,
                    values,
                    width=width,
                    bottom=bottoms,
                    label=series.label,
                )
                bottoms = [b + v for b, v in zip(bottoms, values)]
        else:  # grouped bars
            count = len(series_list)
            offsets = [
                width * (idx - (count - 1) / 2) / max(count, 1)
                for idx in range(count)
            ]
            for offset, series in zip(offsets, series_list):
                values = [
                    value_map[series.label].get(date, 0.0)
                    for date in all_dates
                ]
                ax.bar(
                    date_nums + offset,
                    values,
                    width=width / max(count, 1.0),
                    label=series.label,
                )
    elif effective_format == "bar":
        for series in series_list:
            plot_points = daily_usage_points(series)
            dates = [date for date, _ in plot_points]
            date_nums = mdates.date2num(dates)
            values = [value for _, value in plot_points]
            ax.bar(date_nums, values, width=0.8, label=series.label)
    elif effective_format == "line":
        for series in series_list:
            dates = [date for date, _ in series.points]
            values = [value for _, value in series.points]
            ax.plot(dates, values, marker="o", label=series.label)
    elif effective_format == "scatter":
        for series in series_list:
            dates = [mdates.date2num(date) for date, _ in series.points]
            values = [value for _, value in series.points]
            ax.scatter(dates, values, label=series.label)
    elif effective_format == "interval":
        colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
        for index, series in enumerate(series_list):
            color = colors[index % len(colors)]
            if not series.diff_enabled:
                dates = [date for date, _ in series.points]
                values = [value for _, value in series.points]
                ax.scatter(dates, values, color=color, label=series.label)
                continue
            midpoints = [item.midpoint for item in series.usage_intervals]
            rates = [item.rate for item in series.usage_intervals]
            widths = [item.days for item in series.usage_intervals]
            ax.bar(
                midpoints,
                rates,
                width=widths,
                color=color,
                alpha=0.2,
                edgecolor=color,
                linewidth=0.8,
                label=f"{series.label} intervals",
            )
            ax.scatter(
                midpoints,
                rates,
                color=color,
                marker="o",
                s=18,
                zorder=3,
                label=f"{series.label} observations",
            )
            if smooth and series.usage_intervals:
                sigma = (
                    smooth_days
                    if smooth_days is not None
                    else automatic_smoothing_days(series.usage_intervals)
                )
                dates, values = smoothed_usage(series.usage_intervals, sigma)
                if dates:
                    ax.plot(
                        dates,
                        values,
                        color=color,
                        linewidth=2,
                        label=f"{series.label} trend ({sigma:g} days)",
                    )
    else:  # pragma: no cover - defensive branch
        raise ValueError(f"Unsupported plot format {plot_format!r}")

    if effective_format in {"bar", "stacked"}:
        colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
        for index, series in enumerate(series_list):
            if not series.diff_enabled:
                continue
            ax.scatter(
                [item.midpoint for item in series.usage_intervals],
                [item.rate for item in series.usage_intervals],
                facecolors="none",
                edgecolors=colors[index % len(colors)],
                s=28,
                linewidths=1.2,
                zorder=3,
                label=f"{series.label} observations",
            )

    ax.set_title(title)
    ax.set_ylabel(y_label)
    ax.set_xlabel("Date")
    ax.legend()
    if finalize:
        fig.autofmt_xdate()
        fig.tight_layout()
    return fig


def plot_readings(
    series_list: Sequence[SeriesData],
    y_label: str,
    title: str,
    *,
    ax: plt.Axes | None = None,
    finalize: bool = True,
) -> plt.Figure:
    """Plot raw measurements with markers and last-known-value steps."""
    sns.set_theme(style="whitegrid")
    if ax is None:
        fig, ax = plt.subplots()
    else:
        fig = ax.figure

    locator = mdates.AutoDateLocator()
    formatter = mdates.ConciseDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)

    for series in series_list:
        readings = sorted(series.raw_points, key=lambda item: item[0])
        dates = [date for date, _ in readings]
        values = [value for _, value in readings]
        (line,) = ax.step(
            dates,
            values,
            where="post",
            linewidth=1.4,
            alpha=0.7,
            label=series.label,
        )
        ax.scatter(
            dates,
            values,
            color=line.get_color(),
            s=24,
            zorder=3,
        )

    ax.set_title(title)
    ax.set_ylabel(y_label)
    ax.set_xlabel("Date")
    if series_list:
        ax.legend()
    if finalize:
        fig.autofmt_xdate()
        fig.tight_layout()
    return fig


def plot_readings_and_usage(
    series_list: Sequence[SeriesData],
    plot_format: str,
    usage_y_label: str,
    title: str,
    *,
    smooth: bool,
    smooth_days: float | None,
) -> plt.Figure:
    """Plot raw readings above their inferred usage on aligned axes."""
    fig, (readings_ax, usage_ax) = plt.subplots(
        2,
        1,
        figsize=(10, 8),
        sharex=True,
    )
    plot_readings(
        series_list,
        "Reading",
        "",
        ax=readings_ax,
        finalize=False,
    )
    plot_series(
        series_list,
        plot_format,
        usage_y_label,
        "",
        smooth=smooth,
        smooth_days=smooth_days,
        ax=usage_ax,
        finalize=False,
    )
    readings_ax.set_xlabel("")
    fig.suptitle(title)
    fig.autofmt_xdate()
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return fig


def create_parser() -> argparse.ArgumentParser:
    """Create the :mod:`argparse` parser for the CLI."""

    class HelpFormatter(
        argparse.ArgumentDefaultsHelpFormatter,
        argparse.RawDescriptionHelpFormatter,
    ):
        """Formatter combining defaults with wrapped overview text."""

    parser = argparse.ArgumentParser(
        description=HELP_OVERVIEW,
        formatter_class=HelpFormatter,
    )
    input_group = parser.add_argument_group("input and grouping")
    appearance_group = parser.add_argument_group("plot appearance")
    stats_group = parser.add_argument_group("statistics")
    diagnostics_group = parser.add_argument_group("diagnostics")

    input_group.add_argument(
        "files",
        nargs="+",
        metavar="FILE[:LABEL]",
        help=(
            "Input file names located in $TSD, $TSD_DIR, or $HOME/tsd. "
            "Append :LABEL to customise the legend entry."
        ),
    )
    input_group.add_argument(
        "--sum",
        action="store_true",
        help="Sum values from all files sharing the same date.",
    )
    diff_group = input_group.add_mutually_exclusive_group()
    diff_group.add_argument(
        "--diff",
        dest="diff",
        action="store_true",
        default=argparse.SUPPRESS,
        help=(
            "Interpret every input as cumulative readings. This controls "
            "data semantics; use --view to choose readings or usage output."
        ),
    )
    diff_group.add_argument(
        "--no-diff",
        dest="diff",
        action="store_false",
        default=argparse.SUPPRESS,
        help=(
            "Interpret every input as direct values, ignoring diff_type. "
            "This controls data semantics, not presentation."
        ),
    )
    input_group.add_argument(
        "--bin",
        action="store_true",
        help="Group dates into bins before plotting.",
    )
    input_group.add_argument(
        "--bin-width",
        type=parse_bin_width,
        help=(
            "Number of days per bin. Integers are accepted directly; "
            "unambiguous abbreviations of week, month, and year are "
            "also accepted."
        ),
    )
    input_group.add_argument(
        "--bin-function",
        default="mean",
        help=(
            "Aggregation used within each bin. Allowed values: mean, "
            "median, sum. Unambiguous abbreviations are accepted."
        ),
    )
    appearance_group.add_argument(
        "--view",
        default="auto",
        help=(
            "Representation to display after resolving --diff/--no-diff. "
            "Allowed values: auto, readings, usage, both. Auto shows usage "
            "for cumulative inputs and direct values otherwise. Readings "
            "shows raw cumulative measurements; usage and both also require "
            "cumulative inputs. Both uses aligned reading and usage panels. "
            "Unambiguous abbreviations are accepted."
        ),
    )
    appearance_group.add_argument(
        "--format",
        default="auto",
        help=(
            "Plot style. Allowed values: auto, bar, interval, line, "
            "stacked, scatter. Auto uses interval usage for cumulative "
            "series and bars otherwise. In readings view, raw measurements "
            "use markers and a last-known-value step line. "
            "Unambiguous abbreviations are accepted."
        ),
    )
    appearance_group.add_argument(
        "--smooth-days",
        type=float,
        help=(
            "Gaussian trend width in days for interval plots. By default "
            "it is inferred from the typical reading interval."
        ),
    )
    appearance_group.add_argument(
        "--no-smooth",
        action="store_true",
        help="Do not overlay an adaptive trend on interval usage plots.",
    )
    stats_group.add_argument(
        "--std",
        action="store_true",
        help="Print the sample standard deviation of each plotted series.",
    )
    appearance_group.add_argument(
        "-t",
        "--title",
        help="Title for the plot. Defaults to the space-separated filenames.",
    )
    appearance_group.add_argument(
        "-y",
        "--y-label",
        default=argparse.SUPPRESS,
        help=(
            "Label for the primary Y axis. Defaults to 'Reading' for the "
            "readings view, 'Usage per day' for usage, and 'Value' for "
            "direct values. In the both view it labels the usage panel."
        ),
    )
    diagnostics_group.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print additional information about the loaded and plotted data.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point for the ``tsd-plot`` command."""

    parser = create_parser()
    args = parser.parse_args(argv)

    def log(message: str) -> None:
        if args.verbose:
            print(message)

    try:
        plot_format = resolve_prefix(args.format, PLOT_FORMATS)
    except PrefixMatchError as exc:
        parser.error(str(exc))

    try:
        requested_view = resolve_prefix(args.view, PLOT_VIEWS)
    except PrefixMatchError as exc:
        parser.error(str(exc))

    try:
        reducer_name = resolve_prefix(args.bin_function, BIN_FUNCTIONS)
    except PrefixMatchError as exc:
        parser.error(str(exc))
    reducer = BIN_FUNCTIONS[reducer_name]
    if args.smooth_days is not None and args.smooth_days <= 0:
        parser.error("--smooth-days must be positive")
    log(f"Plot format resolved to: {plot_format}")
    log(f"Bin function resolved to: {reducer_name}")

    file_specs = [parse_filespec(value) for value in args.files]
    filenames = [name for name, _ in file_specs]
    base_dir = resolve_tsd_dir()
    log(f"Reading data from base directory: {base_dir}")

    try:
        diff_override = getattr(args, "diff", None)
        series = [
            load_plot_series(filename, label, base_dir, diff_override)
            for filename, label in file_specs
        ]
    except ValueError as exc:
        parser.error(str(exc))
    all_inputs_are_cumulative = bool(series) and all(
        item.diff_enabled for item in series
    )
    any_inputs_are_cumulative = any(item.diff_enabled for item in series)
    resolved_view = requested_view
    if requested_view == "auto":
        if all_inputs_are_cumulative:
            resolved_view = "usage"
        elif any_inputs_are_cumulative:
            resolved_view = "mixed"
        else:
            resolved_view = "values"
    insufficient_usage = [
        item.filename
        for item in series
        if item.diff_enabled and len(item.raw_points) < 2
    ]
    if resolved_view != "readings" and insufficient_usage:
        parser.error(
            "cumulative series need at least two readings to infer usage: "
            + ", ".join(insufficient_usage)
        )
    if resolved_view in {"readings", "usage", "both"} and not (
        all_inputs_are_cumulative
    ):
        parser.error(
            f"--view {resolved_view} requires cumulative inputs; use --diff "
            "to force cumulative interpretation"
        )
    if resolved_view == "readings" and plot_format != "auto":
        parser.error("--format does not apply to --view readings")
    if resolved_view == "readings" and (
        args.smooth_days is not None or args.no_smooth
    ):
        parser.error("smoothing options do not apply to --view readings")
    if resolved_view in {"readings", "both"} and (
        args.sum or args.bin or args.bin_width is not None
    ):
        parser.error(
            f"aggregation options do not apply to --view {resolved_view}; "
            "they would replace the source readings"
        )

    def diagnostic_points(
        item: SeriesData,
    ) -> Sequence[Tuple[_dt.date, float]]:
        """Return the points represented by the selected view."""

        return (
            item.raw_points
            if resolved_view in {"readings", "both"}
            else item.points
        )

    total_points = sum(len(diagnostic_points(item)) for item in series)
    if resolved_view == "both":
        total_intervals = sum(len(item.usage_intervals) for item in series)
        log(
            "Loaded {} series containing {} readings and {} usage "
            "intervals in total.".format(
                len(series), total_points, total_intervals
            )
        )
    else:
        log(
            "Loaded {} series containing {} points in total.".format(
                len(series), total_points
            )
        )
    log(f"View resolved to: {resolved_view}")
    for item in series:
        if resolved_view == "both":
            log(
                f"  {item.label} ({item.filename}): "
                f"{len(item.raw_points)} readings, "
                f"{len(item.usage_intervals)} usage intervals"
            )
        else:
            log(
                f"  {item.label} ({item.filename}): "
                f"{len(diagnostic_points(item))} points"
            )
        log(
            "    differencing {} ({})".format(
                "enabled" if item.diff_enabled else "disabled",
                item.diff_source,
            )
        )
        usage_trend_is_plotted = (
            resolved_view in {"usage", "both", "mixed"}
            and not args.no_smooth
            and plot_format in {"auto", "interval"}
            and not (args.sum or args.bin or args.bin_width is not None)
        )
        if item.diff_enabled and usage_trend_is_plotted:
            sigma = (
                args.smooth_days
                if args.smooth_days is not None
                else automatic_smoothing_days(item.usage_intervals)
            )
            width_source = (
                "command line" if args.smooth_days is not None else "adaptive"
            )
            log(f"    usage trend width: {sigma:g} days ({width_source})")
    all_dates = [
        date for item in series for date, _ in diagnostic_points(item)
    ]
    if all_dates:
        log(f"Date range: {min(all_dates)} – {max(all_dates)}")
    else:
        log("No data points found in the provided files.")

    if args.sum:
        if any(item.diff_enabled for item in series) and not all(
            item.diff_enabled for item in series
        ):
            parser.error(
                "--sum cannot mix cumulative usage rates with direct values"
            )
        log("Summing series across files by date.")
        series = [sum_series(series)]
        log(f"Summed series has {len(series[0].points)} aggregated points.")

    if args.bin or args.bin_width is not None:
        width = args.bin_width or 7
        log(
            "Binning data with width {} days using {} aggregation.".format(
                width, reducer_name
            )
        )
        series = [bin_series(item, width, reducer) for item in series]
        total_bins = sum(len(item.points) for item in series)
        log(f"Total bins produced: {total_bins}")
        for item in series:
            if item.points:
                log(
                    "  {}: {} bins ({} – {})".format(
                        item.label,
                        len(item.points),
                        item.points[0][0],
                        item.points[-1][0],
                    )
                )
            else:
                log(f"  {item.label}: 0 bins")

    series = ensure_sorted(series)
    total_points = sum(len(diagnostic_points(item)) for item in series)
    if resolved_view == "both":
        total_intervals = sum(len(item.usage_intervals) for item in series)
        log(
            "Preparing to plot {} readings and {} usage intervals across "
            "{} series.".format(total_points, total_intervals, len(series))
        )
    else:
        log(
            "Preparing to plot {} points across {} series.".format(
                total_points, len(series)
            )
        )
    if total_points:
        all_dates = [
            date for item in series for date, _ in diagnostic_points(item)
        ]
        log(f"Final date range: {min(all_dates)} – {max(all_dates)}")

    title = format_title(args, filenames)
    y_label = getattr(args, "y_label", None) or (
        "Reading"
        if resolved_view == "readings"
        else "Usage per day" if all_inputs_are_cumulative else "Value"
    )
    log(f"Plot title: {title}")
    log(f"Y-axis label: {y_label}")
    if resolved_view == "readings":
        figure = plot_readings(series, y_label, title)
    elif resolved_view == "both":
        figure = plot_readings_and_usage(
            series,
            plot_format,
            y_label,
            title,
            smooth=not args.no_smooth,
            smooth_days=args.smooth_days,
        )
    else:
        figure = plot_series(
            series,
            plot_format,
            y_label,
            title,
            smooth=not args.no_smooth,
            smooth_days=args.smooth_days,
        )
    log(f"Generated figure with {len(figure.axes)} axes.")

    if args.std:
        for item in series:
            points = (
                item.raw_points if resolved_view == "readings" else item.points
            )
            std_value = compute_std([value for _, value in points])
            print(f"{item.label}: {std_value}")

    plt.show()
