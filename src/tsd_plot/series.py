"""Shared loading and cumulative-series transformations for TSD plots."""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

import numpy as np

DateLike = Union[dt.date, dt.datetime]
Point = Tuple[DateLike, float]
CalendarPoint = Tuple[dt.date, float]


@dataclass(frozen=True)
class UsageInterval:
    """An average usage rate inferred between two cumulative readings."""

    start: dt.date
    end: dt.date
    amount: float
    rate: float
    reset: bool

    @property
    def days(self) -> int:
        """Return the length of the measurement interval in days."""
        return (self.end - self.start).days

    @property
    def midpoint(self) -> dt.datetime:
        """Return the temporal midpoint of the measurement interval."""
        start = dt.datetime.combine(self.start, dt.time())
        return start + (dt.timedelta(days=self.days) / 2)


@dataclass
class SeriesData:
    """A series together with its original readings and derived intervals."""

    label: str
    filename: str
    points: List[Point]
    raw_points: List[Point] = field(default_factory=list)
    usage_intervals: List[UsageInterval] = field(default_factory=list)
    diff_enabled: bool = False
    diff_source: str = "not configured"

    def __post_init__(self) -> None:
        if not self.raw_points:
            self.raw_points = list(self.points)

    def sorted_points(self) -> List[Point]:
        """Return points ordered by their timestamp."""
        return sorted(self.points, key=lambda item: item[0])


def read_series(filename: str, label: str, base_dir: Path) -> SeriesData:
    """Read a single TSD data file without applying configuration."""
    path = base_dir / filename
    points: List[Point] = []
    with path.open("r", encoding="utf8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                date_str, value_str = line.split()
                date = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
                value = float(value_str)
            except ValueError as exc:
                message = f"Could not parse line {line!r} in {path}"
                raise ValueError(message) from exc
            points.append((date, value))
    return SeriesData(label=label, filename=filename, points=points)


def read_key_value_config(path: Path) -> Dict[str, str]:
    """Read a simple ``name=value`` configuration file if it exists."""
    try:
        text = path.read_text(encoding="utf8")
    except FileNotFoundError:
        return {}

    config: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator:
            config[key.strip()] = value.strip()
    return config


def config_diff_type(path: Path) -> bool:
    """Return the configured cumulative-series flag from *path*."""
    value = read_key_value_config(path).get("diff_type", "").lower()
    if value in {"", "0", "false", "no", "off"}:
        return False
    if value in {"1", "true", "yes", "on"}:
        return True
    raise ValueError(f"Invalid diff_type={value!r} in {path}")


def derive_usage(series: SeriesData, source: str) -> SeriesData:
    """Derive reset-safe average usage intervals from cumulative readings."""
    readings = sorted(series.raw_points, key=lambda item: item[0])
    intervals: List[UsageInterval] = []
    points: List[Point] = []
    for previous, current in zip(readings, readings[1:]):
        previous_date, previous_value = previous
        current_date, current_value = current
        if isinstance(previous_date, dt.datetime):
            previous_date = previous_date.date()
        if isinstance(current_date, dt.datetime):
            current_date = current_date.date()
        elapsed = (current_date - previous_date).days
        if elapsed <= 0:
            raise ValueError(
                f"Series {series.filename!r} has repeated or unordered dates"
            )
        reset = current_value < previous_value
        amount = max(0.0, current_value - previous_value)
        interval = UsageInterval(
            start=previous_date,
            end=current_date,
            amount=amount,
            rate=amount / elapsed,
            reset=reset,
        )
        intervals.append(interval)
        points.append((interval.midpoint, interval.rate))

    return SeriesData(
        label=series.label,
        filename=series.filename,
        points=points,
        raw_points=list(readings),
        usage_intervals=intervals,
        diff_enabled=True,
        diff_source=source,
    )


def load_plot_series(
    filename: str,
    label: str,
    base_dir: Path,
    diff_override: Optional[bool],
) -> SeriesData:
    """Load one series and resolve its effective differencing behavior."""
    series = read_series(filename, label, base_dir)
    if diff_override is None:
        config_path = Path(f"{base_dir / filename}.cfg")
        enabled = config_diff_type(config_path)
        source = (
            config_path.name
            if config_path.exists()
            else "no diff_type configuration"
        )
    else:
        enabled = diff_override
        source = "--diff" if enabled else "--no-diff"

    if enabled:
        return derive_usage(series, source)
    series.diff_source = source
    return series


def automatic_smoothing_days(intervals: Iterable[UsageInterval]) -> float:
    """Choose a Gaussian width from the typical reading interval."""
    durations = [item.days for item in intervals if not item.reset]
    if not durations:
        return 1.0
    return max(1.0, statistics.median(durations))


def daily_usage_points(series: SeriesData) -> List[CalendarPoint]:
    """Expand inferred usage intervals onto the days they cover."""
    if not series.diff_enabled:
        return [
            (date.date() if isinstance(date, dt.datetime) else date, value)
            for date, value in series.points
        ]
    points: List[CalendarPoint] = []
    for interval in series.usage_intervals:
        date = interval.start
        while date < interval.end:
            points.append((date, interval.rate))
            date += dt.timedelta(days=1)
    return points


def smoothed_usage(
    intervals: List[UsageInterval], sigma_days: float
) -> Tuple[List[dt.datetime], List[float]]:
    """Smooth interval rates on a daily grid, ignoring reset intervals."""
    if sigma_days <= 0:
        raise ValueError("Smoothing width must be positive")
    if not intervals:
        return [], []

    first = min(item.start for item in intervals)
    last = max(item.end for item in intervals)
    day_count = (last - first).days
    if day_count <= 0:
        return [], []

    values = np.zeros(day_count, dtype=float)
    observed = np.zeros(day_count, dtype=float)
    for interval in intervals:
        if interval.reset:
            continue
        start = (interval.start - first).days
        end = (interval.end - first).days
        values[start:end] = interval.rate
        observed[start:end] = 1.0

    if not observed.any():
        return [], []

    radius = min(day_count - 1, max(1, int(round(4 * sigma_days))))
    offsets = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-0.5 * (offsets / sigma_days) ** 2)
    numerator_full = np.convolve(values * observed, kernel, mode="full")
    denominator_full = np.convolve(observed, kernel, mode="full")
    center = len(kernel) // 2
    numerator = numerator_full[center : center + day_count]
    denominator = denominator_full[center : center + day_count]
    smoothed = np.divide(
        numerator,
        denominator,
        out=np.zeros_like(numerator),
        where=denominator > 0,
    )
    dates = [
        dt.datetime.combine(first + dt.timedelta(days=index), dt.time(12))
        for index in range(day_count)
    ]
    return dates, smoothed.tolist()
