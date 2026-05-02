"""Estimate time remaining until a reserve reaches zero."""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple

import numpy as np

from . import cli as tsd_cli

DATE_FMT = "%Y-%m-%d"


@dataclass
class Options:
    """Command-line options for the forecast tool."""

    files: List[Tuple[str, str]]
    not_found: List[str]
    multi_file_mode: bool
    sigma_r: float
    sigma_q: float
    sigma_z: float
    nsims: int
    dt_forward: float
    max_days: float
    seed: Optional[int]
    allow_negative_rate: bool
    min_rate: float
    bins: int
    quantiles: Tuple[float, ...]
    drop_same_day_duplicates: bool
    fractional: bool
    auto_size: bool
    hist_min: float


@dataclass
class FileResult:
    """Processed results for a single input file."""

    label: str
    n_rows: int
    q_now: float
    r_now: float
    hits: np.ndarray
    finite: np.ndarray
    censored: int
    censored_pct: float
    already_empty: bool = False
    error: Optional[str] = None


def resolve_tsd_dir() -> str:
    """Return the directory containing tsd series data."""

    tsd_dir = os.environ.get("TSD_DIR")
    if tsd_dir:
        return tsd_dir
    tsd_cli.get_config()
    return tsd_cli.series_dir_name().rstrip("/")


def resolve_name_via_series_dir(
    pattern: str, tsd_dir: str
) -> List[Tuple[str, str]]:
    """Return matching ``(name, path)`` pairs from the configured series dir."""

    try:
        names = sorted(os.listdir(tsd_dir))
    except OSError as exc:
        sys.exit(f"Cannot list series directory {tsd_dir!r}: {exc}")

    matches = []
    for name in names:
        if name.endswith("~") or name.endswith(".cfg"):
            continue
        if pattern in name:
            matches.append((name, os.path.join(tsd_dir, name)))
    return matches


def parse_args() -> Options:
    """Parse command-line arguments and return validated options."""

    parser = argparse.ArgumentParser(
        description=(
            "State-space random-walk rate + Monte-Carlo "
            "time-to-empty estimator"
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

    kf = parser.add_argument_group("Kalman filter")
    kf.add_argument(
        "--sigma-r",
        type=float,
        default=0.50,
        help="Rate random-walk diffusion per sqrt(day) (default: 0.50)",
    )
    kf.add_argument(
        "--sigma-q",
        type=float,
        default=0.25,
        help="Quantity process-noise diffusion per sqrt(day) (default: 0.25)",
    )
    kf.add_argument(
        "--sigma-z",
        type=float,
        default=0.50,
        help="Measurement noise std on observed quantity (default: 0.50)",
    )

    mc = parser.add_argument_group("Monte Carlo")
    mc.add_argument(
        "--nsims",
        type=int,
        default=20000,
        help="Number of forward simulations (default: 20000)",
    )
    mc.add_argument(
        "--dt-forward",
        type=float,
        default=1.0,
        help="Simulation step in days (default: 1.0)",
    )
    mc.add_argument(
        "--max-days",
        type=float,
        default=3650.0,
        help="Forward horizon in days (default: 3650)",
    )
    mc.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    mc.add_argument(
        "--allow-negative-rate",
        action="store_true",
        help=(
            "Allow simulated rate to go negative (net gains); "
            "default clips to 0"
        ),
    )
    mc.add_argument(
        "--min-rate",
        type=float,
        default=0.0,
        help="Lower bound for simulated rate (default: 0.0)",
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
        help="Display fractional days; default rounds to whole days",
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
        quantiles = tuple(float(x) for x in args.quantiles.split(","))
    except Exception:
        sys.exit("Invalid --quantiles; use comma-separated floats in (0,1).")
    if not all(0 < q < 1 for q in quantiles):
        sys.exit("Quantiles must be in (0,1).")

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
        parser.error("Specify at least one file: use FILE arguments or -f.")

    return Options(
        files=files,
        not_found=not_found,
        multi_file_mode=multi_file_mode,
        sigma_r=args.sigma_r,
        sigma_q=args.sigma_q,
        sigma_z=args.sigma_z,
        nsims=args.nsims,
        dt_forward=args.dt_forward,
        max_days=args.max_days,
        seed=args.seed,
        allow_negative_rate=args.allow_negative_rate,
        min_rate=args.min_rate,
        bins=args.bins,
        quantiles=quantiles,
        drop_same_day_duplicates=args.drop_same_day,
        fractional=args.fractional,
        auto_size=args.auto_size,
        hist_min=args.hist_min,
    )


def read_data(
    path: str, drop_same_day_duplicates: bool
) -> List[Tuple[date, float]]:
    """Read and parse sorted ``(date, quantity)`` pairs from *path*."""

    rows: List[Tuple[date, float]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            try:
                day = datetime.strptime(parts[0], DATE_FMT).date()
                quantity = float(round(float(parts[1])))
            except ValueError:
                continue
            rows.append((day, quantity))
    if not rows:
        sys.exit("No valid rows found.")

    rows.sort(key=lambda x: x[0])
    if drop_same_day_duplicates:
        dedup = {}
        for day, quantity in rows:
            dedup[day] = quantity
        rows = sorted(dedup.items(), key=lambda x: x[0])
    return rows


def compute_time_axis(
    rows: List[Tuple[date, float]],
) -> Tuple[np.ndarray, np.ndarray]:
    """Convert rows to ``(days_from_start, quantity)`` arrays."""

    start = rows[0][0]
    t_days = np.array([(day - start).days for (day, _) in rows], dtype=float)
    quantities = np.array([qty for (_, qty) in rows], dtype=float)
    return t_days, quantities


def initial_rate_guess(t: np.ndarray, q: np.ndarray) -> float:
    """Estimate an initial daily consumption rate from observed decreases."""

    rates = []
    for idx in range(1, len(t)):
        dt_value = t[idx] - t[idx - 1]
        if dt_value <= 0:
            continue
        quantity_delta = q[idx - 1] - q[idx]
        rate = quantity_delta / dt_value
        if rate > 0:
            rates.append(rate)
    if rates:
        return float(np.median(rates))
    return 1e-6


def kalman_filter_random_walk_rate(
    t: np.ndarray,
    z: np.ndarray,
    sigma_r: float,
    sigma_q: float,
    sigma_z: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Run a linear Kalman filter for quantity and consumption rate."""

    if len(t) < 2:
        state = np.array([z[-1], initial_rate_guess(t, z)], dtype=float)
        covariance = np.diag([10.0**2, 1.0**2])
        return state, covariance

    rate0 = initial_rate_guess(t, z)
    state = np.array([z[0], rate0], dtype=float)
    covariance = np.diag([10.0**2, 1.0**2])

    observation = np.array([[1.0, 0.0]])
    measurement_variance = sigma_z**2
    identity = np.eye(2)

    for idx in range(1, len(t)):
        dt_value = max(t[idx] - t[idx - 1], 1e-9)
        transition = np.array([[1.0, -dt_value], [0.0, 1.0]])
        process = np.diag([sigma_q**2 * dt_value, sigma_r**2 * dt_value])

        state = transition @ state
        covariance = transition @ covariance @ transition.T + process

        s_scalar = float((observation @ covariance @ observation.T)[0, 0])
        s_scalar += measurement_variance
        gain = (covariance @ observation.T) / s_scalar
        innovation = float(z[idx]) - float((observation @ state)[0])
        state = state + gain.ravel() * innovation

        kh_term = gain @ observation
        covariance = (identity - kh_term) @ covariance @ (
            identity - kh_term
        ).T + gain @ np.array([[measurement_variance]]) @ gain.T

    state[1] = max(state[1], 0.0)
    return state, covariance


def simulate_hitting_time(
    x_mean: np.ndarray,
    P: np.ndarray,
    nsims: int,
    sigma_r: float,
    sigma_q: float,
    dt_forward: float,
    max_days: float,
    rng: np.random.Generator,
    allow_negative_rate: bool,
    min_rate: float,
) -> np.ndarray:
    """Simulate depletion times in days for a random-walk rate model."""

    try:
        cholesky = np.linalg.cholesky(P)
    except np.linalg.LinAlgError:
        values, vectors = np.linalg.eigh(P)
        values = np.maximum(values, 0.0)
        cholesky = vectors @ np.diag(np.sqrt(values))

    sampled = x_mean[:, None] + cholesky @ rng.standard_normal((2, nsims))
    quantity = sampled[0].copy()
    rate = sampled[1].copy()
    if not allow_negative_rate:
        np.clip(rate, min_rate, None, out=rate)

    hits = np.full(nsims, np.inf, dtype=float)
    active = np.ones(nsims, dtype=bool)

    sqrt_dt = math.sqrt(dt_forward)
    n_steps = math.ceil(max_days / dt_forward)

    for step in range(1, n_steps + 1):
        n_active = int(active.sum())
        if n_active == 0:
            break

        rate[active] += rng.normal(0.0, sigma_r * sqrt_dt, size=n_active)
        if not allow_negative_rate:
            rate[active] = np.maximum(rate[active], min_rate)

        quantity[active] += rng.normal(0.0, sigma_q * sqrt_dt, size=n_active)
        quantity[active] -= rate[active] * dt_forward

        newly_hit = active & (quantity <= 0.0)
        hits[newly_hit] = step * dt_forward
        active &= ~newly_hit

    return hits


def make_error_result(label: str, msg: str) -> FileResult:
    """Create an error-valued file result."""

    empty = np.array([], dtype=float)
    return FileResult(
        label=label,
        n_rows=0,
        q_now=0.0,
        r_now=0.0,
        hits=empty,
        finite=empty,
        censored=0,
        censored_pct=0.0,
        error=msg,
    )


def process_file(
    label: str,
    path: str,
    opt: Options,
    rng: np.random.Generator,
) -> FileResult:
    """Run filtering and simulation for one file."""

    try:
        rows = read_data(
            path, drop_same_day_duplicates=opt.drop_same_day_duplicates
        )
    except OSError as exc:
        return make_error_result(label, str(exc))

    t_days, q_obs = compute_time_axis(rows)
    state, covariance = kalman_filter_random_walk_rate(
        t_days,
        q_obs,
        sigma_r=opt.sigma_r,
        sigma_q=opt.sigma_q,
        sigma_z=opt.sigma_z,
    )
    q_now = float(state[0])
    r_now = float(state[1])

    if q_obs[-1] <= 0.0:
        empty = np.array([], dtype=float)
        return FileResult(
            label=label,
            n_rows=len(rows),
            q_now=q_now,
            r_now=r_now,
            hits=empty,
            finite=empty,
            censored=0,
            censored_pct=0.0,
            already_empty=True,
        )

    hits = simulate_hitting_time(
        x_mean=state,
        P=covariance,
        nsims=opt.nsims,
        sigma_r=opt.sigma_r,
        sigma_q=opt.sigma_q,
        dt_forward=opt.dt_forward,
        max_days=opt.max_days,
        rng=rng,
        allow_negative_rate=opt.allow_negative_rate,
        min_rate=opt.min_rate,
    )
    finite = hits[np.isfinite(hits)]
    censored = int(np.sum(~np.isfinite(hits)))
    return FileResult(
        label=label,
        n_rows=len(rows),
        q_now=q_now,
        r_now=r_now,
        hits=hits,
        finite=finite,
        censored=censored,
        censored_pct=100.0 * censored / len(hits),
    )


def fmt_days(value: float, fractional: bool) -> str:
    """Format a day count."""

    if fractional:
        return f"{value:,.1f}"
    return f"{int(round(value)):,d}"


def ascii_histogram(
    data: np.ndarray,
    bins: int,
    width: int = 60,
    hist_min: float = 0.0,
    auto_size: bool = False,
    fractional: bool = True,
) -> str:
    """Render an ASCII histogram of finite depletion times."""

    finite = data[np.isfinite(data)]
    if len(finite) == 0:
        return "(no depletion within horizon for any simulation)"

    data_max = float(np.max(finite))

    if fractional:
        if auto_size:
            hist_range = None
        else:
            low = min(float(hist_min), data_max)
            hist_range = (low, data_max)
        counts, edges = np.histogram(finite, bins=bins, range=hist_range)

        def fmt(value: float) -> str:
            return f"{value:.1f}"

    else:
        if auto_size:
            low = int(math.floor(float(np.min(finite))))
        else:
            low = min(int(math.floor(hist_min)), int(math.floor(data_max)))
        high = int(math.ceil(data_max))
        bin_width = max(1, math.ceil((high - low) / bins))
        bin_edges = np.arange(low, high + bin_width, bin_width, dtype=float)
        counts, edges = np.histogram(finite, bins=bin_edges)

        def fmt(value: float) -> str:
            return f"{int(round(value))}"

    peak = counts.max()
    lines = []
    for idx in range(len(counts)):
        bar_len = int(round(width * counts[idx] / peak)) if peak > 0 else 0
        bar = "█" * bar_len
        lines.append(
            f"{fmt(edges[idx]):>8}–{fmt(edges[idx + 1]):>8} d | "
            f"{bar} {counts[idx]}"
        )
    return "\n".join(lines)


def print_single(result: FileResult, opt: Options) -> None:
    """Print the full single-file report."""

    if result.error:
        sys.exit(f"ERROR: {result.error}")
    print("=== Time-to-Empty Forecast (State-space RW rate + Monte Carlo) ===")
    print(
        f"Readings: {result.n_rows}"
        f"  |  Current q_now ≈ {result.q_now:.2f}"
        f"  |  Current rate r_now ≈ {result.r_now:.4f} per day"
    )

    if result.already_empty:
        print(
            "Already empty (last observed value is 0); no forecast produced."
        )
        sys.exit(0)

    print(
        f"Model params: sigma_r={opt.sigma_r:.3f}/√day,"
        f" sigma_q={opt.sigma_q:.3f}/√day, sigma_z={opt.sigma_z:.3f}"
    )
    print(
        f"Simulations: {opt.nsims}"
        f"  |  step={opt.dt_forward} day"
        f"  |  horizon={opt.max_days} days"
    )
    if result.censored > 0:
        print(
            f"Note: {result.censored} simulations"
            f" ({result.censored_pct:.1f}%) did NOT reach zero within horizon."
        )

    if len(result.finite) == 0:
        print(
            "No depletion expected within the chosen horizon "
            "given current model/settings."
        )
        sys.exit(0)

    quantiles = np.quantile(result.finite, q=opt.quantiles)
    labels = ", ".join(
        f"{int(100*q):>2d}%={fmt_days(float(v), opt.fractional)} d"
        for q, v in zip(opt.quantiles, quantiles)
    )
    print("Quantiles:", labels)

    thresholds = sorted({float(round(v / 10) * 10) for v in quantiles})
    if thresholds:
        probs = [
            f"P[T ≥ {fmt_days(th, opt.fractional)} d] = "
            f"{100.0 * (result.finite >= th).mean():5.1f}%"
            for th in thresholds
        ]
        print("Threshold survival:", " | ".join(probs))

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


def section_header(label: str, total_width: int = 60) -> str:
    """Return a divider line for a named file section."""

    prefix = f"── {label} "
    return prefix + "─" * max(0, total_width - len(prefix))


def print_file_section(result: FileResult, opt: Options) -> None:
    """Print the section for one file in multi-file mode."""

    print(section_header(result.label))
    if result.error:
        print(f"ERROR: {result.error}\n")
        return
    print(
        f"Readings: {result.n_rows}"
        f"  |  q_now ≈ {result.q_now:.2f}"
        f"  |  rate ≈ {result.r_now:.4f}/day"
    )
    if result.already_empty:
        print("Already empty (last observed value is 0).\n")
        return
    if result.censored > 0:
        print(
            f"Note: {result.censored} sims"
            f" ({result.censored_pct:.1f}%) did NOT reach zero within horizon."
        )
    if len(result.finite) == 0:
        print("No depletion within horizon.\n")
        return
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
    print()


def median_sort_key(result: FileResult) -> float:
    """Return the median depletion time for sorting."""

    if result.error or result.already_empty or len(result.finite) == 0:
        return float("inf")
    return float(np.median(result.finite))


def print_summary_table(results: List[FileResult], opt: Options) -> None:
    """Print the multi-file quantile summary table."""

    def sort_key(result: FileResult) -> Tuple[int, float]:
        if result.error:
            return (3, 0.0)
        if result.already_empty:
            return (2, 0.0)
        if len(result.finite) == 0:
            return (1, 0.0)
        return (0, -median_sort_key(result))

    sorted_results = sorted(results, key=sort_key)

    q_headers = [f"P{int(100*q)}" for q in opt.quantiles]
    name_w = max(4, max(len(result.label) for result in results))
    val_w = 8 if opt.fractional else 6

    print("\n=== Summary (sorted by median, descending) ===\n")
    header = f"{'Name':{name_w}s}"
    for name in q_headers:
        header += f"  {name:>{val_w}s}"
    header += f"  {'censored':>9s}"
    print(header)
    print("─" * len(header))

    for result in sorted_results:
        row = f"{result.label:{name_w}s}"
        if result.error:
            tag = "error"
            for _ in q_headers:
                row += f"  {tag:>{val_w}s}"
                tag = ""
        elif result.already_empty:
            tag = "empty"
            for _ in q_headers:
                row += f"  {tag:>{val_w}s}"
                tag = ""
        elif len(result.finite) == 0:
            for _ in q_headers:
                row += f"  {'—':>{val_w}s}"
        else:
            quantiles = np.quantile(result.finite, q=opt.quantiles)
            for value in quantiles:
                row += f"  {fmt_days(float(value), opt.fractional):>{val_w}s}"
        row += f"  {result.censored_pct:>8.1f}%"
        print(row)


def main() -> None:
    """Run the forecast CLI."""

    opt = parse_args()
    rng = np.random.default_rng(opt.seed)

    results: List[FileResult] = []
    for label, path in opt.files:
        results.append(process_file(label, path, opt, rng))
    for name in opt.not_found:
        results.append(
            make_error_result(name, f"no series matching {name!r} found")
        )

    if opt.multi_file_mode:
        print(
            f"Model: sigma_r={opt.sigma_r:.3f}"
            f"  sigma_q={opt.sigma_q:.3f}"
            f"  sigma_z={opt.sigma_z:.3f}"
        )
        print(
            f"Simulations: {opt.nsims}"
            f"  |  step={opt.dt_forward} d"
            f"  |  horizon={opt.max_days} d"
        )
        print()
        for result in results:
            print_file_section(result, opt)
        print_summary_table(results, opt)
    else:
        print_single(results[0], opt)

    if any(result.error for result in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
