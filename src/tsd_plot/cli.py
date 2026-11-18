"""Command line interface for plotting TSD data files."""

from __future__ import annotations

import argparse
import datetime as _dt
import math
import os
import statistics
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence, Tuple

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from matplotlib.backend_bases import FigureCanvasBase
from matplotlib.container import BarContainer
from matplotlib.colors import to_hex, to_rgba
from matplotlib.ticker import MaxNLocator

from .series import (
    SeriesData,
    automatic_density_days,
    automatic_smoothing_days,
    daily_usage_points,
    ewma_points,
    load_plot_series,
    read_key_value_config,
    reading_dates,
    reading_density,
    sidecar_problems,
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
# Share of the density strip's height reserved for the reading rugs.
DENSITY_RUG_FRACTION = 0.3

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


def parse_date(value: str) -> _dt.date:
    """Parse a calendar date for a range endpoint."""
    try:
        return _dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Date must be a valid YYYY-MM-DD date"
        ) from exc


def resolve_date_range(
    start: _dt.date | None,
    end: _dt.date | None,
    duration_days: int | None,
) -> Tuple[_dt.date | None, _dt.date | None]:
    """Resolve an inclusive range, counting duration in calendar days."""
    if duration_days is not None:
        if duration_days <= 0:
            raise ValueError(
                "--duration-days must be a positive number of days"
            )
        if start is None and end is None:
            raise ValueError("--duration-days requires --start or --end")
        if start is not None and end is not None:
            raise ValueError(
                "specify at most two of --start, --end, --duration-days"
            )
        try:
            span = _dt.timedelta(days=duration_days - 1)
            if start is not None:
                end = start + span
            else:
                start = end - span
        except OverflowError as exc:
            raise ValueError("Date range exceeds supported dates") from exc
    if start is not None and end is not None and start > end:
        raise ValueError("--start must be on or before --end")
    return start, end


def restrict_date_range(
    series: SeriesData, start: _dt.date | None, end: _dt.date | None
) -> None:
    """Restrict observations and inferred usage to the selected days."""

    def included(point) -> bool:
        date = point[0]
        if isinstance(date, _dt.datetime):
            date = date.date()
        return (start is None or date >= start) and (
            end is None or date <= end
        )

    series.raw_points = [
        point for point in series.raw_points if included(point)
    ]
    if not series.diff_enabled:
        series.points = [point for point in series.points if included(point)]
        return
    intervals = []
    for interval in series.usage_intervals:
        first = max(interval.start, start) if start else interval.start
        last = interval.end
        # Usage intervals are half-open; the requested end day is inclusive.
        if end is not None and end < last:
            last = end + _dt.timedelta(days=1)
        if first < last:
            intervals.append(
                replace(
                    interval,
                    start=first,
                    end=last,
                    amount=interval.rate * (last - first).days,
                )
            )
    series.usage_intervals = intervals
    series.points = [(item.midpoint, item.rate) for item in intervals]


def resolve_tsd_dir() -> Path:
    """Return the directory holding TSD files."""

    for env_name in ("TSD", "TSD_DIR"):
        value = os.environ.get(env_name)
        if value:
            return Path(value).expanduser()
    return Path.home() / "tsd"


def parse_y_margin(value: str) -> float:
    """Parse a finite, non-negative fraction of the displayed data span."""
    try:
        margin = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Y margin must be a finite, non-negative number"
        ) from exc
    if not math.isfinite(margin) or margin < 0:
        raise argparse.ArgumentTypeError(
            "Y margin must be a finite, non-negative number"
        )
    return margin


def parse_positive_days(value: str, name: str) -> float:
    """Parse a finite, positive number of days described by *name*."""
    message = f"{name} must be finite and positive"
    try:
        days = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(message) from exc
    if not math.isfinite(days) or days <= 0:
        raise argparse.ArgumentTypeError(message)
    return days


def parse_ewma_halflife(value: str) -> float:
    """Parse the EWMA decay time in days."""
    return parse_positive_days(value, "EWMA half-life")


def parse_smooth_days(value: str) -> float:
    """Parse the Gaussian trend width in days."""
    return parse_positive_days(value, "Smoothing width")


def parse_density_days(value: str) -> float:
    """Parse the reading-density bandwidth in days."""
    return parse_positive_days(value, "Density bandwidth")


def parse_config_bool(value: str) -> bool:
    """Parse an explicit boolean setting."""
    if value.lower() in {"1", "true", "yes", "on"}:
        return True
    if value.lower() in {"0", "false", "no", "off"}:
        return False
    raise ValueError("expected true or false")


def parse_threshold(value: str) -> float:
    """Parse a finite point-colouring threshold."""
    try:
        threshold = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Threshold must be finite") from exc
    if not math.isfinite(threshold):
        raise argparse.ArgumentTypeError("Threshold must be finite")
    return threshold


def parse_point_colour(value: str) -> str:
    """Validate and normalise a Matplotlib colour for comparisons."""
    try:
        return to_hex(to_rgba(value), keep_alpha=True)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid point colour: {value!r}"
        ) from exc


@dataclass(frozen=True)
class ThresholdColours:
    below: float | None = None
    above: float | None = None
    below_colour: str = "#009E73"
    above_colour: str = "#D55E00"

    @property
    def enabled(self) -> bool:
        return self.below is not None or self.above is not None

    def matches(self, value: float) -> bool:
        return math.isfinite(value) and (
            (self.below is not None and value < self.below)
            or (self.above is not None and value > self.above)
        )


def resolve_threshold_colours(
    filenames: Sequence[str], base_dir: Path, args: argparse.Namespace
) -> ThresholdColours:
    """Resolve compatible sidecar thresholds and CLI overrides."""
    if args.no_threshold_colours:
        return ThresholdColours()
    configs = [
        (path, read_key_value_config(path))
        for name in filenames
        for path in [Path(f"{base_dir / name}.cfg")]
    ]
    resolved = []
    for name, parse, default in (
        ("colour_below", parse_threshold, None),
        ("colour_above", parse_threshold, None),
        ("below_colour", parse_point_colour, "#009E73"),
        ("above_colour", parse_point_colour, "#D55E00"),
    ):
        override = getattr(args, name)
        if override is not None:
            resolved.append(override)
            continue
        values = set()
        for path, config in configs:
            if name in config:
                try:
                    values.add(parse(config[name]))
                except argparse.ArgumentTypeError as exc:
                    raise ValueError(
                        f"Invalid {name} in {path}: {exc}"
                    ) from exc
        if len(values) > 1:
            raise ValueError(
                f"Conflicting {name} settings in sidecar files; "
                f"use --{name.replace('_', '-')} to override them"
            )
        resolved.append(next(iter(values), default))
    settings = ThresholdColours(*resolved)
    if (
        settings.below is not None
        and settings.above is not None
        and settings.below >= settings.above
    ):
        raise ValueError("--colour-below must be less than --colour-above")
    return settings


def highlight_threshold_points(
    ax: plt.Axes,
    series_list: Sequence[SeriesData],
    settings: ThresholdColours,
    alpha: float,
) -> None:
    """Draw threshold markers with the plot's point transparency."""
    for threshold, colour, label, below in (
        (settings.below, settings.below_colour, "Below", True),
        (settings.above, settings.above_colour, "Above", False),
    ):
        if threshold is None:
            continue
        points = [
            (date, value)
            for series in series_list
            for date, value in series.points
            if math.isfinite(value)
            and (value < threshold if below else value > threshold)
        ]
        if points:
            dates, values = zip(*points)
            ax.scatter(
                dates,
                values,
                color=colour,
                alpha=alpha,
                zorder=5,
                label=f"{label} {threshold:g}",
            )


@dataclass(frozen=True)
class SidecarOption:
    """A setting read from sidecars, overridable by the same-named arg.

    *parse_cli* applies *parse* to a CLI value too, for options whose
    argparse value is not yet normalised.
    """

    name: str
    parse: Callable[[str], object]
    default: object
    parse_cli: bool = False


def resolve_style_settings(
    filenames: Sequence[str],
    base_dir: Path,
    args: argparse.Namespace,
    *,
    default_format: str = "auto",
) -> Tuple[str, bool, float, bool, float | None]:
    """Resolve sidecar style preferences, allowing CLI overrides.

    The density bandwidth is resolved only when density is on, so unused
    sidecar values neither conflict nor need to be valid.
    """
    resolved = resolve_sidecar_options(
        filenames,
        base_dir,
        args,
        (
            SidecarOption(
                "format",
                lambda value: resolve_prefix(value, PLOT_FORMATS),
                default_format,
                parse_cli=True,
            ),
            SidecarOption("ewma", parse_config_bool, False),
            SidecarOption("ewma_halflife_days", parse_ewma_halflife, 30.0),
            SidecarOption("density", parse_config_bool, False),
        ),
    )
    *_, density = resolved
    density_days = None
    if density:
        (density_days,) = resolve_sidecar_options(
            filenames,
            base_dir,
            args,
            (SidecarOption("density_days", parse_density_days, None),),
        )
    return (*resolved, density_days)


def resolve_sidecar_options(
    filenames: Sequence[str],
    base_dir: Path,
    args: argparse.Namespace,
    options: Sequence[SidecarOption],
) -> tuple:
    """Resolve *options* from sidecar files and command-line overrides.

    A CLI value (an attribute of *args* that is not None) wins. Otherwise
    explicit sidecar values must agree; files without the option impose
    no preference.
    """
    paths = [Path(f"{base_dir / filename}.cfg") for filename in filenames]
    configs = [(path, read_key_value_config(path)) for path in paths]
    resolved = []
    for option in options:
        name = option.name
        override = getattr(args, name, None)
        if override is not None:
            resolved.append(
                option.parse(override) if option.parse_cli else override
            )
            continue
        values = set()
        for path, config in configs:
            if name in config:
                try:
                    values.add(option.parse(config[name]))
                except (ValueError, argparse.ArgumentTypeError) as exc:
                    raise ValueError(
                        f"Invalid {name} in {path}: {exc}"
                    ) from exc
        if len(values) > 1:
            flag = name.replace("_", "-")
            overrides = (
                f"--{flag} or --no-{flag}"
                if option.parse is parse_config_bool
                else f"--{flag}"
            )
            raise ValueError(
                f"Conflicting {name} settings in sidecar files; "
                f"use {overrides} to override them"
            )
        resolved.append(next(iter(values), option.default))
    return tuple(resolved)


def resolve_y_settings(
    filenames: Sequence[str],
    base_dir: Path,
    y_range: str | None,
    y_margin: float | None,
) -> Tuple[str, float]:
    """Resolve CLI overrides and compatible explicit sidecar settings."""
    settings = {"y_range": set(), "y_margin": set()}
    for filename in filenames:
        path = Path(f"{base_dir / filename}.cfg")
        config = read_key_value_config(path)
        if y_range is None and "y_range" in config:
            value = config["y_range"].lower()
            if value not in {"auto", "data"}:
                raise ValueError(f"Invalid y_range={value!r} in {path}")
            settings["y_range"].add(value)
        if y_margin is None and "y_margin" in config:
            try:
                margin = parse_y_margin(config["y_margin"])
            except argparse.ArgumentTypeError as exc:
                raise ValueError(f"Invalid y_margin in {path}: {exc}") from exc
            settings["y_margin"].add(margin)
    for name, values in settings.items():
        if len(values) > 1:
            option = name.replace("_", "-")
            raise ValueError(
                f"Conflicting {name} settings in sidecar files; "
                f"use --{option} to override them"
            )
    return (
        (
            y_range
            if y_range is not None
            else next(iter(settings["y_range"]), "auto")
        ),
        (
            y_margin
            if y_margin is not None
            else next(iter(settings["y_margin"]), 0.05)
        ),
    )


def fit_y_axis_to_data(ax: plt.Axes, margin: float) -> None:
    """Fit the axis to rendered values without artificial bar baselines."""
    chunks = [line.get_ydata(orig=False) for line in ax.lines]
    chunks.extend(
        collection.get_offsets()[:, 1] for collection in ax.collections
    )
    # Stacked bar endpoints include their cumulative height.
    chunks.extend(
        [patch.get_y() + patch.get_height() for patch in container.patches]
        for container in ax.containers
        if isinstance(container, BarContainer)
    )
    if not chunks:
        return
    values = np.ma.masked_invalid(np.ma.concatenate(chunks)).compressed()
    if not len(values):
        return
    low, high = float(values.min()), float(values.max())
    padding = (high - low) * margin
    if low == high:
        padding = max(abs(low), 1.0) * max(margin, 0.05)
    ax.set_ylim(low - padding, high + padding)


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


def overlay_ewma(
    ax: plt.Axes,
    series_list: Sequence[SeriesData],
    halflife_days: float,
    *,
    readings: bool = False,
) -> None:
    """Overlay one time-based EWMA per displayed series."""
    colours = sns.color_palette("dark")
    for index, series in enumerate(series_list):
        points = ewma_points(
            series.raw_points if readings else series.points, halflife_days
        )
        if points:
            dates, values = zip(*points)
            ax.plot(
                dates,
                values,
                color=colours[(index + 3) % len(colours)],
                linewidth=2.5,
                zorder=4,
                label=f"{series.label} EWMA ({halflife_days:g} day half-life)",
            )


def plot_series(
    series_list: Sequence[SeriesData],
    plot_format: str,
    y_label: str,
    title: str,
    *,
    smooth: bool = True,
    smooth_days: float | None = None,
    ewma_halflife_days: float | None = None,
    threshold_colours: ThresholdColours = ThresholdColours(),
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

    if threshold_colours.enabled and effective_format not in {
        "scatter",
        "line",
    }:
        raise ValueError("Threshold colours require --format scatter or line")

    if effective_format == "stacked" or (
        effective_format == "bar" and len(series_list) > 1
    ):
        all_dates, value_map = prepare_plot_data(series_list)
        date_nums = mdates.date2num(all_dates)
        width = 0.8
        if effective_format == "stacked":
            bottoms = [0.0] * len(all_dates)
            for series in series_list:
                present = np.array(
                    [date in value_map[series.label] for date in all_dates],
                    dtype=bool,
                )
                values = [
                    value_map[series.label].get(date, 0.0)
                    for date in all_dates
                ]
                ax.bar(
                    date_nums[present],
                    np.array(values)[present],
                    width=width,
                    bottom=np.array(bottoms)[present],
                    linewidth=0,
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
                mapping = value_map[series.label]
                dates = sorted(mapping)
                values = [mapping[date] for date in dates]
                ax.bar(
                    mdates.date2num(dates) + offset,
                    values,
                    width=width / max(count, 1.0),
                    linewidth=0,
                    label=series.label,
                )
    elif effective_format == "bar":
        for series in series_list:
            plot_points = daily_usage_points(series)
            dates = [date for date, _ in plot_points]
            date_nums = mdates.date2num(dates)
            values = [value for _, value in plot_points]
            # White theme outlines can cover the fill of subpixel bars.
            ax.bar(
                date_nums, values, width=0.8, linewidth=0, label=series.label
            )
    elif effective_format == "line":
        for series in series_list:
            dates = [date for date, _ in series.points]
            values = [value for _, value in series.points]
            ax.plot(
                dates,
                values,
                marker="o",
                markevery=[
                    index
                    for index, value in enumerate(values)
                    if not threshold_colours.matches(value)
                ],
                label=series.label,
            )
    elif effective_format == "scatter":
        for series in series_list:
            points = [
                (date, value)
                for date, value in series.points
                if not threshold_colours.matches(value)
            ]
            dates = [mdates.date2num(date) for date, _ in points]
            values = [value for _, value in points]
            ax.scatter(
                dates,
                values,
                label=series.label,
                alpha=(
                    0.35 if smooth and ewma_halflife_days is not None else 1.0
                ),
            )
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
            if (
                smooth
                and ewma_halflife_days is None
                and series.usage_intervals
            ):
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

    if threshold_colours.enabled:
        highlight_threshold_points(
            ax,
            series_list,
            threshold_colours,
            alpha=(
                0.35
                if effective_format == "scatter"
                and smooth
                and ewma_halflife_days is not None
                else 1.0
            ),
        )

    if smooth and ewma_halflife_days is not None:
        overlay_ewma(ax, series_list, ewma_halflife_days)

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
    ewma_halflife_days: float | None = None,
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

    if ewma_halflife_days is not None:
        overlay_ewma(ax, series_list, ewma_halflife_days, readings=True)

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
    ewma_halflife_days: float | None = None,
    threshold_colours: ThresholdColours = ThresholdColours(),
    axes: Tuple[plt.Axes, plt.Axes] | None = None,
    finalize: bool = True,
) -> plt.Figure:
    """Plot raw readings above their inferred usage on aligned axes."""
    if axes is None:
        fig, (readings_ax, usage_ax) = plt.subplots(
            2,
            1,
            figsize=(10, 8),
            sharex=True,
        )
    else:
        readings_ax, usage_ax = axes
        fig = readings_ax.figure
    plot_readings(
        series_list,
        "Reading",
        "",
        ax=readings_ax,
        finalize=False,
        ewma_halflife_days=ewma_halflife_days if smooth else None,
    )
    plot_series(
        series_list,
        plot_format,
        usage_y_label,
        "",
        smooth=smooth,
        smooth_days=smooth_days,
        ewma_halflife_days=ewma_halflife_days,
        threshold_colours=threshold_colours,
        ax=usage_ax,
        finalize=False,
    )
    readings_ax.set_xlabel("")
    fig.suptitle(title)
    if finalize:
        fig.autofmt_xdate()
        fig.tight_layout(rect=(0, 0, 1, 0.97))
    return fig


def plot_density_strip(
    ax: plt.Axes,
    series_list: Sequence[SeriesData],
    density_days: float | None,
    *,
    colour_offset: int = 0,
) -> List[Tuple[str, int, float]]:
    """Draw reading density and a rug of reading dates for each series.

    The curves span the axis' current x-range, which it shares with the
    plot above. *colour_offset* skips colours already used there by
    series other than these sources. Returns ``(label, reading count,
    bandwidth)`` for each series.
    """
    colours = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    rug_height = DENSITY_RUG_FRACTION / max(len(series_list), 1)
    dates_by_series = [reading_dates(series) for series in series_list]
    all_dates = [date for dates in dates_by_series for date in dates]
    x_limits = ax.get_xlim()
    # An empty plot above leaves Matplotlib's default limits near 1970.
    plotted_above = any(
        np.isfinite(other.dataLim.intervalx).all()
        for other in ax.get_shared_x_axes().get_siblings(ax)
        if other is not ax
    )
    span = None
    if all_dates and not plotted_above:
        span = (min(all_dates), max(all_dates))
    elif all_dates:
        # Bars and clipped usage intervals can reach beyond the readings.
        span = (
            min(min(all_dates), mdates.num2date(x_limits[0]).date()),
            max(max(all_dates), mdates.num2date(x_limits[1]).date()),
        )
    peak = 0.0
    summary = []
    for index, (series, dates) in enumerate(zip(series_list, dates_by_series)):
        colour = colours[(index + colour_offset) % len(colours)]
        sigma = (
            density_days
            if density_days is not None
            else automatic_density_days(dates)
        )
        summary.append((series.label, len(dates), sigma))
        if not dates:
            continue
        grid, rates = reading_density(dates, sigma, span)
        ax.fill_between(grid, rates, color=colour, alpha=0.25, linewidth=0)
        ax.plot(
            grid,
            rates,
            color=colour,
            linewidth=1.2,
            label=f"{series.label} ({sigma:g} day bandwidth)",
        )
        peak = max(peak, max(rates))
        low = index * rug_height
        ax.vlines(
            dates,
            low + 0.1 * rug_height,
            low + 0.9 * rug_height,
            transform=ax.get_xaxis_transform(),
            color=colour,
            linewidth=0.8,
        )
    # The rugs sit in a band below zero so their ticks never hide the curve.
    top = peak * 1.1 if peak > 0 else 1.0
    bottom = -top * DENSITY_RUG_FRACTION / (1 - DENSITY_RUG_FRACTION)
    ax.set_yticks(
        [
            tick
            for tick in MaxNLocator(nbins=3).tick_values(0, top)
            if 0 <= tick <= top
        ]
    )
    ax.set_ylim(bottom, top)
    if all_dates and plotted_above:
        ax.set_xlim(x_limits)
    elif all_dates:
        low, high = mdates.date2num(span[0]), mdates.date2num(span[1])
        padding = max(1.0, 0.05 * (high - low))
        ax.set_xlim(low - padding, high + padding)
    ax.set_ylabel("Readings/week")
    ax.set_xlabel("Date")
    # Always shown, as the legend is where the bandwidth is reported.
    if all_dates:
        ax.legend(fontsize="small", loc="upper left")
    return summary


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
    output_group = parser.add_argument_group("output")
    diagnostics_group = parser.add_argument_group("diagnostics")

    for option in ("below", "above"):
        appearance_group.add_argument(
            f"--colour-{option}",
            type=parse_threshold,
            metavar="VALUE",
            help=(
                f"Highlight points strictly {option} VALUE in scatter or "
                "line plots. Overrides the sidecar setting."
            ),
        )
        appearance_group.add_argument(
            f"--{option}-colour",
            type=parse_point_colour,
            metavar="COLOUR",
            help=(
                f"Matplotlib colour for points {option} the threshold "
                f"(default: {'teal green' if option == 'below' else 'vermilion'})."
            ),
        )
    appearance_group.add_argument(
        "--no-threshold-colours",
        action="store_true",
        help="Disable all threshold colouring, including sidecar settings.",
    )

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
    input_group.add_argument(
        "--start",
        type=parse_date,
        metavar="YYYY-MM-DD",
        help="Include data on or after this date.",
    )
    input_group.add_argument(
        "--end",
        type=parse_date,
        metavar="YYYY-MM-DD",
        help="Include data on or before this date.",
    )
    input_group.add_argument(
        "--duration-days",
        type=int,
        metavar="DAYS",
        help=(
            "Positive number of calendar days, including both endpoints. "
            "Requires exactly one of --start or --end."
        ),
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
        default=argparse.SUPPRESS,
        help=(
            "Plot style. Allowed values: auto, bar, interval, line, "
            "stacked, scatter. Auto uses interval usage for cumulative "
            "series and bars otherwise. In readings view, raw measurements "
            "use markers and a last-known-value step line. "
            "Overrides sidecar format settings; defaults to scatter with "
            "y_range=data, auto otherwise. "
            "Unambiguous abbreviations are accepted."
        ),
    )
    ewma_group = appearance_group.add_mutually_exclusive_group()
    ewma_group.add_argument(
        "--ewma",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Overlay a time-based EWMA, overriding sidecar ewma settings.",
    )
    ewma_group.add_argument(
        "--no-ewma",
        dest="ewma",
        action="store_false",
        default=argparse.SUPPRESS,
        help="Disable EWMA, overriding sidecar ewma settings.",
    )
    appearance_group.add_argument(
        "--ewma-halflife-days",
        type=parse_ewma_halflife,
        default=argparse.SUPPRESS,
        help=(
            "EWMA half-life in elapsed days; defaults to 30. Overrides "
            "sidecar ewma_halflife_days. Requires EWMA to be enabled."
        ),
    )
    appearance_group.add_argument(
        "--smooth-days",
        type=parse_smooth_days,
        metavar="DAYS",
        help=(
            "Gaussian trend width in days for interval plots. By default "
            "it is inferred from the typical reading interval."
        ),
    )
    appearance_group.add_argument(
        "--no-smooth",
        action="store_true",
        help="Hide both Gaussian and EWMA smoothing overlays.",
    )
    density_group = appearance_group.add_mutually_exclusive_group()
    density_group.add_argument(
        "--density",
        action="store_true",
        default=argparse.SUPPRESS,
        help=(
            "Add a strip below the plot showing each source series' "
            "readings per week (a Gaussian density estimate) and a rug "
            "of its actual reading dates. Uses the readings before "
            "summation and binning. Overrides sidecar density settings."
        ),
    )
    density_group.add_argument(
        "--no-density",
        dest="density",
        action="store_false",
        default=argparse.SUPPRESS,
        help="Omit the density strip, overriding sidecar density settings.",
    )
    appearance_group.add_argument(
        "--density-days",
        type=parse_density_days,
        metavar="DAYS",
        help=(
            "Gaussian bandwidth for the density strip in days. Overrides "
            "sidecar density_days. By default it is the median gap "
            "between readings, and at least 7. Requires density to be "
            "enabled."
        ),
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
        "--y-range",
        choices=("auto", "data"),
        help=(
            "Y-axis scaling: auto preserves the plot style's normal limits; "
            "data fits displayed values. Overrides sidecar y_range settings; "
            "defaults to auto. Applies independently to both panels."
        ),
    )
    appearance_group.add_argument(
        "--y-margin",
        type=parse_y_margin,
        help=(
            "Padding at each end as a fraction of the displayed data span "
            "when y_range=data. Overrides sidecar y_margin settings; "
            "defaults to 0.05."
        ),
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
    add_output_argument(output_group)
    diagnostics_group.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print additional information about the loaded and plotted data.",
    )
    return parser


def warn_about_sidecars(
    parser: argparse.ArgumentParser,
    filenames: Sequence[str],
    base_dir: Path,
) -> None:
    """Warn about sidecar lines that would otherwise be silently ignored."""
    for filename in dict.fromkeys(filenames):
        path = Path(f"{base_dir / filename}.cfg")
        for problem in sidecar_problems(path):
            print(
                f"{parser.prog}: warning: {path}: {problem}",
                file=sys.stderr,
            )


def add_output_argument(group: argparse._ArgumentGroup) -> None:
    """Add the ``-o/--output`` option shared by the plotting commands."""

    group.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FILE",
        help=(
            "Save the plot to FILE instead of opening a window. The "
            "extension selects the format (e.g. .png, .pdf, .svg). Works "
            "without a display."
        ),
    )


def prepare_output(
    parser: argparse.ArgumentParser, output: Path | None
) -> None:
    """Validate ``--output`` and select a backend before any plotting."""

    if output is None:
        return
    output_format = output.suffix.lstrip(".").lower()
    supported_formats = FigureCanvasBase.get_supported_filetypes()
    if output_format not in supported_formats:
        parser.error(
            "--output needs a file extension naming one of: "
            + ", ".join(sorted(supported_formats))
        )
    # Figures are created through pyplot, so an interactive default
    # backend would still need a display before anything is saved.
    plt.switch_backend("agg")


def show_or_save(
    parser: argparse.ArgumentParser,
    figure: plt.Figure,
    output: Path | None,
    log: Callable[[str], None],
) -> None:
    """Show ``figure`` in a window, or save it to ``output`` if given."""

    if output is None:
        plt.show()
        return
    try:
        figure.savefig(output)
    except OSError as exc:
        parser.exit(1, f"{parser.prog}: cannot write {output}: {exc}\n")
    finally:
        plt.close(figure)
    log(f"Saved plot to {output}")


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point for the ``tsd-plot`` command."""

    parser = create_parser()
    args = parser.parse_args(argv)
    prepare_output(parser, args.output)
    try:
        start, end = resolve_date_range(
            args.start, args.end, args.duration_days
        )
    except ValueError as exc:
        parser.error(str(exc))

    def log(message: str) -> None:
        if args.verbose:
            print(message)

    try:
        requested_view = resolve_prefix(args.view, PLOT_VIEWS)
    except PrefixMatchError as exc:
        parser.error(str(exc))

    try:
        reducer_name = resolve_prefix(args.bin_function, BIN_FUNCTIONS)
    except PrefixMatchError as exc:
        parser.error(str(exc))
    reducer = BIN_FUNCTIONS[reducer_name]
    log(f"Bin function resolved to: {reducer_name}")

    file_specs = [parse_filespec(value) for value in args.files]
    filenames = [name for name, _ in file_specs]
    base_dir = resolve_tsd_dir()
    log(f"Reading data from base directory: {base_dir}")

    try:
        warn_about_sidecars(parser, filenames, base_dir)
        threshold_colours = resolve_threshold_colours(
            filenames, base_dir, args
        )
        y_range, y_margin = resolve_y_settings(
            filenames, base_dir, args.y_range, args.y_margin
        )
        (
            plot_format,
            ewma,
            ewma_halflife_days,
            density,
            density_days,
        ) = resolve_style_settings(
            filenames,
            base_dir,
            args,
            default_format=(
                "scatter"
                if y_range == "data" and requested_view != "readings"
                else "auto"
            ),
        )
        diff_override = getattr(args, "diff", None)
        series = [
            load_plot_series(filename, label, base_dir, diff_override)
            for filename, label in file_specs
        ]
    except ValueError as exc:
        parser.error(str(exc))
    if args.density_days is not None and not density:
        parser.error("--density-days requires density; use --density")
    if ewma and args.smooth_days is not None:
        parser.error(
            "--smooth-days controls Gaussian smoothing; use --no-ewma first"
        )
    log(f"Plot format resolved to: {plot_format}")
    if ewma:
        log(f"EWMA half-life: {ewma_halflife_days:g} days")
    log(f"Y-axis range resolved to: {y_range} (margin {y_margin:g})")
    log(f"Density strip: {'on' if density else 'off'}")
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
    if threshold_colours.enabled:
        if resolved_view == "readings":
            parser.error("Threshold colours do not apply to --view readings")
        if plot_format not in {"scatter", "line"}:
            parser.error("Threshold colours require --format scatter or line")
    if resolved_view == "readings" and args.smooth_days is not None:
        parser.error("--smooth-days does not apply to --view readings")
    if resolved_view in {"readings", "both"} and (
        args.sum or args.bin or args.bin_width is not None
    ):
        parser.error(
            f"aggregation options do not apply to --view {resolved_view}; "
            "they would replace the source readings"
        )

    series = ensure_sorted(series)
    if start is not None or end is not None:
        log(
            f"Selected date range: {start or 'unbounded'} – {end or 'unbounded'}"
        )
        for item in series:
            restrict_date_range(item, start, end)
    # Summation and binning replace readings with evenly spaced values,
    # which would hide exactly the sparsity the density strip shows.
    density_series = list(series)

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
            and not ewma
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
    layout_rect = (0, 0, 1, 0.97) if resolved_view == "both" else None
    density_axis = None
    plot_axes: List[plt.Axes | None] = [None, None]
    if density:
        sns.set_theme(style="whitegrid")
        panel_count = 2 if resolved_view == "both" else 1
        figure, axes = plt.subplots(
            panel_count + 1,
            1,
            sharex=True,
            figsize=(10, 9) if panel_count == 2 else (6.4, 6.0),
            gridspec_kw={"height_ratios": [3] * panel_count + [1]},
        )
        *plot_axes, density_axis = axes
    finalize = density_axis is None
    if resolved_view == "readings":
        figure = plot_readings(
            series,
            y_label,
            title,
            ax=plot_axes[0],
            finalize=finalize,
            ewma_halflife_days=(
                ewma_halflife_days if ewma and not args.no_smooth else None
            ),
        )
    elif resolved_view == "both":
        figure = plot_readings_and_usage(
            series,
            plot_format,
            y_label,
            title,
            smooth=not args.no_smooth,
            smooth_days=args.smooth_days,
            ewma_halflife_days=ewma_halflife_days if ewma else None,
            threshold_colours=threshold_colours,
            axes=None if density_axis is None else tuple(plot_axes),
            finalize=finalize,
        )
    else:
        figure = plot_series(
            series,
            plot_format,
            y_label,
            title,
            ax=plot_axes[0],
            finalize=finalize,
            smooth=not args.no_smooth,
            smooth_days=args.smooth_days,
            ewma_halflife_days=ewma_halflife_days if ewma else None,
            threshold_colours=threshold_colours,
        )
    if density_axis is not None:
        for axis in plot_axes:
            axis.set_xlabel("")
        density_summary = plot_density_strip(
            density_axis,
            density_series,
            density_days,
            # The summed series is drawn in the first colour.
            colour_offset=1 if args.sum else 0,
        )
        for label, count, sigma in density_summary:
            log(
                f"  density {label}: {count} readings, "
                f"{sigma:g} day bandwidth"
            )
        figure.autofmt_xdate()
    log(f"Generated figure with {len(figure.axes)} axes.")

    if y_range == "data":
        for axis in figure.axes:
            if axis is not density_axis:
                fit_y_axis_to_data(axis, y_margin)
    if density_axis is not None or y_range == "data":
        figure.tight_layout(rect=layout_rect)

    if args.std:
        for item in series:
            points = (
                item.raw_points if resolved_view == "readings" else item.points
            )
            std_value = compute_std([value for _, value in points])
            print(f"{item.label}: {std_value}")

    show_or_save(parser, figure, args.output, log)
