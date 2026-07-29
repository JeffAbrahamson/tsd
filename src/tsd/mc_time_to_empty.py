"""Estimate time remaining by resampling historical daily consumption."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Tuple

import numpy as np

from .time_to_empty import (
    ascii_histogram,
    fmt_days,
    read_data,
    resolve_name_via_series_dir,
    resolve_tsd_dir,
    section_header,
)


@dataclass
class Options:
    """Command-line options for the empirical forecast tool."""

    files: List[Tuple[str, str]]
    not_found: List[str]
    multi_file_mode: bool
    nsims: int
    max_days: int
    seed: Optional[int]
    recency_sigma: float
    recency_amplitude: float
    bins: int
    quantiles: Tuple[float, ...]
    drop_same_day_duplicates: bool
    fractional: bool
    auto_size: bool
    hist_min: float


@dataclass
class HistoricalRates:
    """Daily rates and sampling weights reconstructed from observations."""

    rates: np.ndarray
    weights: np.ndarray
    excluded_refill_intervals: int


@dataclass
class FileResult:
    """Processed empirical forecast results for one input file."""

    label: str
    n_rows: int
    q_now: float
    historical_days: int
    mean_rate: float
    weighted_mean_rate: float
    excluded_refill_intervals: int
    hits: np.ndarray
    finite: np.ndarray
    censored: int
    censored_pct: float
    already_empty: bool = False
    error: Optional[str] = None


def parse_args() -> Options:
    """Parse command-line arguments and return validated options."""

    parser = argparse.ArgumentParser(
        description=(
            "Empirical Monte-Carlo time-to-empty estimator using historical "
            "daily consumption rates"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    inp = parser.add_argument_group("input")
    inp.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help="File names relative to the tsd series directory",
    )
    inp.add_argument(
        "-f",
        "--file",
        dest="file_path",
        metavar="PATH",
        help="Path to a single data file",
    )
    inp.add_argument(
        "--keep-same-day",
        dest="drop_same_day",
        action="store_false",
        help="Keep all readings on the same day (default: keep only the last)",
    )

    mc = parser.add_argument_group("Monte Carlo")
    mc.add_argument(
        "--nsims",
        type=int,
        default=20000,
        help="Number of forward simulations (default: 20000)",
    )
    mc.add_argument(
        "--max-days",
        type=int,
        default=3650,
        help="Forward horizon in days (default: 3650)",
    )
    mc.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )

    recency = parser.add_argument_group("recency weighting")
    recency.add_argument(
        "--recency-sigma",
        type=float,
        default=60.0,
        metavar="DAYS",
        help=(
            "Gaussian recency width in days; centered on the latest reading "
            "(default: 60)"
        ),
    )
    recency.add_argument(
        "--recency-amplitude",
        type=float,
        default=1.0,
        metavar="FACTOR",
        help=(
            "Gaussian weight above the historical baseline; 1 doubles "
            "today's weight (default: 1)"
        ),
    )

    disp = parser.add_argument_group("display")
    disp.add_argument(
        "--bins",
        type=int,
        default=24,
        help="Target number of histogram bins (default: 24)",
    )
    disp.add_argument(
        "--quantiles",
        type=str,
        default="0.10,0.25,0.50,0.75,0.90",
        help=(
            "Comma-separated quantiles to report "
            "(default: 0.10,0.25,0.50,0.75,0.90)"
        ),
    )
    disp.add_argument(
        "--fractional",
        action="store_true",
        help="Display fractional days; simulations use whole-day steps",
    )
    disp.add_argument(
        "--hist-min",
        type=float,
        default=0.0,
        help=(
            "Earliest day shown in histogram (default: 0); "
            "ignored with --auto-size"
        ),
    )
    disp.add_argument(
        "--auto-size",
        action="store_true",
        help=(
            "Fit histogram x-axis to where the data has mass; "
            "overrides --hist-min"
        ),
    )

    args = parser.parse_args()

    try:
        quantiles = tuple(float(value) for value in args.quantiles.split(","))
    except ValueError:
        parser.error(
            "invalid --quantiles; use comma-separated floats in (0,1)"
        )
    if not all(0 < value < 1 for value in quantiles):
        parser.error("quantiles must be in (0,1)")
    if args.nsims <= 0:
        parser.error("--nsims must be positive")
    if args.max_days <= 0:
        parser.error("--max-days must be positive")
    if args.recency_sigma <= 0:
        parser.error("--recency-sigma must be positive")
    if args.recency_amplitude < 0:
        parser.error("--recency-amplitude cannot be negative")
    if args.bins <= 0:
        parser.error("--bins must be positive")

    multi_file_mode = bool(args.files)
    files: List[Tuple[str, str]] = []
    not_found: List[str] = []

    if args.files:
        tsd_dir = resolve_tsd_dir()
        for name in args.files:
            path = os.path.join(tsd_dir, name)
            if os.path.exists(path):
                files.append((name, path))
            else:
                matches = resolve_name_via_series_dir(name, tsd_dir)
                if matches:
                    files.extend(matches)
                else:
                    not_found.append(name)

        seen = set()
        unique: List[Tuple[str, str]] = []
        for label, path in files:
            if path not in seen:
                seen.add(path)
                unique.append((label, path))
        files = unique

    if args.file_path:
        label = os.path.basename(args.file_path)
        files.append((label, args.file_path))
        if not args.files:
            multi_file_mode = False

    if not files and not not_found:
        parser.error("specify at least one file: use FILE arguments or -f")

    return Options(
        files=files,
        not_found=not_found,
        multi_file_mode=multi_file_mode,
        nsims=args.nsims,
        max_days=args.max_days,
        seed=args.seed,
        recency_sigma=args.recency_sigma,
        recency_amplitude=args.recency_amplitude,
        bins=args.bins,
        quantiles=quantiles,
        drop_same_day_duplicates=args.drop_same_day,
        fractional=args.fractional,
        auto_size=args.auto_size,
        hist_min=args.hist_min,
    )


def gaussian_recency_weight(
    age_days: np.ndarray,
    sigma_days: float,
    amplitude: float,
) -> np.ndarray:
    """Return baseline-plus-Gaussian weights for historical day ages."""

    scaled_age = age_days / sigma_days
    return 1.0 + amplitude * np.exp(-0.5 * scaled_age**2)


def build_historical_rates(
    rows: List[Tuple[date, float]],
    recency_sigma: float,
    recency_amplitude: float,
) -> HistoricalRates:
    """Expand non-increasing observation intervals into daily rates."""

    rates: List[float] = []
    days: List[date] = []
    excluded_refills = 0

    for (start_day, start_q), (end_day, end_q) in zip(rows, rows[1:]):
        elapsed = (end_day - start_day).days
        if elapsed <= 0:
            continue
        quantity_used = start_q - end_q
        if quantity_used < 0:
            excluded_refills += 1
            continue
        daily_rate = quantity_used / elapsed
        for offset in range(1, elapsed + 1):
            rates.append(daily_rate)
            days.append(start_day + timedelta(days=offset))

    if not rates:
        empty = np.array([], dtype=float)
        return HistoricalRates(empty, empty, excluded_refills)

    latest_day = rows[-1][0]
    ages = np.array(
        [(latest_day - historical_day).days for historical_day in days],
        dtype=float,
    )
    rate_array = np.array(rates, dtype=float)
    weights = gaussian_recency_weight(
        ages,
        sigma_days=recency_sigma,
        amplitude=recency_amplitude,
    )
    weights /= weights.sum()
    return HistoricalRates(rate_array, weights, excluded_refills)


def simulate_hitting_time(
    quantity_now: float,
    history: HistoricalRates,
    nsims: int,
    max_days: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Simulate depletion by independently resampling a historical day."""

    hits = np.full(nsims, np.inf, dtype=float)
    if len(history.rates) == 0 or not np.any(history.rates > 0):
        return hits

    quantity = np.full(nsims, quantity_now, dtype=float)
    active = quantity > 0
    hits[~active] = 0.0

    for step in range(1, max_days + 1):
        active_indices = np.flatnonzero(active)
        if len(active_indices) == 0:
            break
        sampled_rates = rng.choice(
            history.rates,
            size=len(active_indices),
            replace=True,
            p=history.weights,
        )
        quantity[active_indices] -= sampled_rates
        newly_hit_indices = active_indices[quantity[active_indices] <= 0.0]
        hits[newly_hit_indices] = float(step)
        active[newly_hit_indices] = False

    return hits


def make_error_result(label: str, message: str) -> FileResult:
    """Create an error-valued file result."""

    empty = np.array([], dtype=float)
    return FileResult(
        label=label,
        n_rows=0,
        q_now=0.0,
        historical_days=0,
        mean_rate=0.0,
        weighted_mean_rate=0.0,
        excluded_refill_intervals=0,
        hits=empty,
        finite=empty,
        censored=0,
        censored_pct=0.0,
        error=message,
    )


def process_file(
    label: str,
    path: str,
    opt: Options,
    rng: np.random.Generator,
) -> FileResult:
    """Build an empirical history and simulate one input file."""

    try:
        rows = read_data(
            path, drop_same_day_duplicates=opt.drop_same_day_duplicates
        )
    except (OSError, SystemExit) as exc:
        return make_error_result(label, str(exc))

    q_now = rows[-1][1]
    history = build_historical_rates(
        rows,
        recency_sigma=opt.recency_sigma,
        recency_amplitude=opt.recency_amplitude,
    )

    if len(history.rates) > 0:
        mean_rate = float(np.mean(history.rates))
        weighted_mean_rate = float(
            np.average(history.rates, weights=history.weights)
        )
    else:
        mean_rate = 0.0
        weighted_mean_rate = 0.0

    if q_now <= 0:
        empty = np.array([], dtype=float)
        return FileResult(
            label=label,
            n_rows=len(rows),
            q_now=q_now,
            historical_days=len(history.rates),
            mean_rate=mean_rate,
            weighted_mean_rate=weighted_mean_rate,
            excluded_refill_intervals=history.excluded_refill_intervals,
            hits=empty,
            finite=empty,
            censored=0,
            censored_pct=0.0,
            already_empty=True,
        )

    if len(history.rates) == 0:
        return make_error_result(
            label, "no usable non-increasing date intervals found"
        )

    hits = simulate_hitting_time(
        quantity_now=q_now,
        history=history,
        nsims=opt.nsims,
        max_days=opt.max_days,
        rng=rng,
    )
    finite = hits[np.isfinite(hits)]
    censored = int(np.sum(~np.isfinite(hits)))
    return FileResult(
        label=label,
        n_rows=len(rows),
        q_now=q_now,
        historical_days=len(history.rates),
        mean_rate=mean_rate,
        weighted_mean_rate=weighted_mean_rate,
        excluded_refill_intervals=history.excluded_refill_intervals,
        hits=hits,
        finite=finite,
        censored=censored,
        censored_pct=100.0 * censored / len(hits),
    )


def quantile_text(result: FileResult, opt: Options) -> str:
    """Return formatted quantiles for a result."""

    values = np.quantile(result.finite, q=opt.quantiles)
    return ", ".join(
        f"{int(100 * quantile):>2d}%="
        f"{fmt_days(float(value), opt.fractional)} d"
        for quantile, value in zip(opt.quantiles, values)
    )


def print_history_summary(result: FileResult) -> None:
    """Print historical sampling information for a result."""

    print(
        f"Readings: {result.n_rows}"
        f"  |  Current quantity = {result.q_now:.2f}"
        f"  |  Historical days = {result.historical_days}"
    )
    print(
        f"Historical mean rate = {result.mean_rate:.4f}/day"
        f"  |  Recency-weighted mean = "
        f"{result.weighted_mean_rate:.4f}/day"
        f"  |  Refill intervals excluded = "
        f"{result.excluded_refill_intervals}"
    )


def print_simulation_notes(result: FileResult) -> None:
    """Print censoring notes shared by single and multi-file reports."""

    if result.censored > 0:
        print(
            f"Note: {result.censored} simulations"
            f" ({result.censored_pct:.1f}%) did NOT reach zero within horizon."
        )


def print_histogram(result: FileResult, opt: Options) -> None:
    """Print the result histogram."""

    print("\nHistogram of time-to-empty (days):")
    print(
        ascii_histogram(
            result.finite,
            bins=opt.bins,
            hist_min=opt.hist_min,
            auto_size=opt.auto_size,
            fractional=opt.fractional,
        )
    )


def print_single(result: FileResult, opt: Options) -> None:
    """Print the full single-file report."""

    if result.error:
        sys.exit(f"ERROR: {result.error}")

    print("=== Time-to-Empty Forecast (Empirical daily-rate Monte Carlo) ===")
    print_history_summary(result)
    print(
        f"Recency weighting: sigma={opt.recency_sigma:.1f} days"
        f"  |  amplitude={opt.recency_amplitude:.2f}"
    )

    if result.already_empty:
        print(
            "Already empty (last observed value is 0); no forecast produced."
        )
        return

    print(
        f"Simulations: {opt.nsims}"
        f"  |  step=1 day"
        f"  |  horizon={opt.max_days} days"
    )
    print_simulation_notes(result)
    if len(result.finite) == 0:
        print(
            "No depletion expected within the chosen horizon "
            "given the historical daily rates."
        )
        return

    print("Quantiles:", quantile_text(result, opt))
    print_histogram(result, opt)

    median = fmt_days(float(np.median(result.finite)), opt.fractional)
    low = fmt_days(float(np.quantile(result.finite, 0.25)), opt.fractional)
    high = fmt_days(float(np.quantile(result.finite, 0.75)), opt.fractional)
    tail_summary = (
        "with long tail"
        if result.censored_pct > 0
        else "finite for nearly all sims"
    )
    print(
        f"\nSummary: median ≈ {median} days (IQR {low}–{high}), "
        f"{tail_summary}."
    )


def print_file_section(result: FileResult, opt: Options) -> None:
    """Print one file section in multi-file mode."""

    print(section_header(result.label))
    if result.error:
        print(f"ERROR: {result.error}\n")
        return
    print_history_summary(result)
    if result.already_empty:
        print("Already empty (last observed value is 0).\n")
        return
    print_simulation_notes(result)
    if len(result.finite) == 0:
        print("No depletion within horizon.\n")
        return
    print_histogram(result, opt)
    print()


def print_summary_table(results: List[FileResult], opt: Options) -> None:
    """Print the multi-file quantile summary table."""

    def sort_key(result: FileResult) -> Tuple[int, float]:
        if result.error:
            return (3, 0.0)
        if result.already_empty:
            return (2, 0.0)
        if len(result.finite) == 0:
            return (1, 0.0)
        return (0, -float(np.median(result.finite)))

    sorted_results = sorted(results, key=sort_key)
    headers = [f"P{int(100 * value)}" for value in opt.quantiles]
    name_width = max(4, max(len(result.label) for result in results))
    value_width = 8 if opt.fractional else 6

    print("\n=== Summary (sorted by median, descending) ===\n")
    header = f"{'Name':{name_width}s}"
    for name in headers:
        header += f"  {name:>{value_width}s}"
    header += f"  {'censored':>9s}"
    print(header)
    print("─" * len(header))

    for result in sorted_results:
        row = f"{result.label:{name_width}s}"
        if result.error:
            tag = "error"
            for _ in headers:
                row += f"  {tag:>{value_width}s}"
                tag = ""
        elif result.already_empty:
            tag = "empty"
            for _ in headers:
                row += f"  {tag:>{value_width}s}"
                tag = ""
        elif len(result.finite) == 0:
            for _ in headers:
                row += f"  {'—':>{value_width}s}"
        else:
            values = np.quantile(result.finite, q=opt.quantiles)
            for value in values:
                formatted = fmt_days(float(value), opt.fractional)
                row += f"  {formatted:>{value_width}s}"
        row += f"  {result.censored_pct:>8.1f}%"
        print(row)


def main() -> None:
    """Run the empirical forecast CLI."""

    opt = parse_args()
    rng = np.random.default_rng(opt.seed)
    results = [
        process_file(label, path, opt, rng) for label, path in opt.files
    ]
    results.extend(
        make_error_result(name, f"no series matching {name!r} found")
        for name in opt.not_found
    )

    if opt.multi_file_mode:
        print(
            f"Model: empirical daily-rate bootstrap"
            f"  |  recency sigma={opt.recency_sigma:.1f} d"
            f"  amplitude={opt.recency_amplitude:.2f}"
        )
        print(
            f"Simulations: {opt.nsims}"
            f"  |  step=1 d"
            f"  |  horizon={opt.max_days} d\n"
        )
        for result in results:
            print_file_section(result, opt)
        print_summary_table(results, opt)
    else:
        print_single(results[0], opt)

    if any(result.error for result in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
