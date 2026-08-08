"""List series recorded on a day and warn about missing habits."""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import cli as tsd_cli


DEFAULT_HABIT_THRESHOLD_DAYS = 4
DEFAULT_HABIT_HISTORY_DAYS = 5
DATE_FORMAT = "%Y-%m-%d"


def parse_day(value: Optional[str], today: Optional[date] = None) -> date:
    """Parse an absolute date or an integer offset from today."""

    current = today or date.today()
    if value is None:
        return current
    try:
        return current + timedelta(days=int(value))
    except ValueError:
        pass
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid day {value!r}; use YYYY-MM-DD or an integer offset"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(
        prog="tsd-today",
        description=(
            "List time-series entries for a day and warn when habitual "
            "entries are absent."
        ),
    )
    parser.add_argument(
        "day",
        nargs="?",
        help="day to display (YYYY-MM-DD or an integer offset; default: 0)",
    )
    parser.add_argument(
        "-k",
        "--habit-threshold-days",
        type=int,
        default=DEFAULT_HABIT_THRESHOLD_DAYS,
        metavar="K",
        help=(
            "warn for entries present on more than K habit-history days "
            f"(default: {DEFAULT_HABIT_THRESHOLD_DAYS})"
        ),
    )
    parser.add_argument(
        "-n",
        "--habit-history-days",
        type=int,
        default=DEFAULT_HABIT_HISTORY_DAYS,
        metavar="N",
        help=(
            "number of preceding calendar days used to identify habits "
            f"(default: {DEFAULT_HABIT_HISTORY_DAYS})"
        ),
    )
    parser.add_argument(
        "--no-habit-threshold-check",
        action="store_true",
        help="list entries without checking for missing habits",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="describe the habit check on stderr",
    )
    return parser


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse and validate command-line arguments."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.day = parse_day(args.day)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.habit_history_days <= 0:
        parser.error("--habit-history-days must be greater than zero")
    if not 0 <= args.habit_threshold_days < args.habit_history_days:
        parser.error(
            "--habit-threshold-days must be non-negative and less than "
            "--habit-history-days"
        )
    return args


def resolve_series_dir(config: Dict[str, object]) -> Path:
    """Resolve the series directory from the environment or configuration."""

    configured = os.environ.get("TSD_DIR") or str(config["series_dir"])
    return Path(configured).expanduser()


def equivalence_prefixes(config: Dict[str, object]) -> Tuple[str, ...]:
    """Return configured equivalence prefixes, longest first."""

    raw = str(config.get("habit_equivalence_prefixes", ""))
    prefixes = {prefix.strip() for prefix in raw.split(",") if prefix.strip()}
    return tuple(sorted(prefixes, key=lambda prefix: (-len(prefix), prefix)))


def canonical_name(name: str, prefixes: Iterable[str]) -> str:
    """Map a series name to its configured habit-equivalence name."""

    for prefix in prefixes:
        if name.startswith(prefix):
            return prefix + "*"
    return name


def iter_series_files(series_dir: Path) -> Iterable[Path]:
    """Yield data-series files in the order used by the former shell helper."""

    try:
        paths = sorted(series_dir.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise RuntimeError(
            f"cannot list series directory {str(series_dir)!r}: {exc}"
        ) from exc
    for path in paths:
        if path.is_file() and not path.name.endswith((".cfg", "~")):
            yield path


def read_entries(
    series_dir: Path, first_day: date, last_day: date
) -> Dict[date, List[Tuple[str, float]]]:
    """Read valid entries in the inclusive date interval."""

    entries: Dict[date, List[Tuple[str, float]]] = defaultdict(list)
    for path in iter_series_files(series_dir):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(
                f"cannot read series {str(path)!r}: {exc}"
            ) from exc
        for line in lines:
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                entry_day = datetime.strptime(parts[0], DATE_FORMAT).date()
                value = float(parts[1])
            except ValueError:
                continue
            if first_day <= entry_day <= last_day:
                entries[entry_day].append((path.name, value))
    return entries


def habitual_absences(
    entries: Dict[date, List[Tuple[str, float]]],
    selected_day: date,
    history_days: int,
    threshold_days: int,
    prefixes: Iterable[str],
) -> List[Tuple[str, int]]:
    """Return habitual canonical names absent on the selected day."""

    present_today = {
        canonical_name(name, prefixes) for name, _ in entries[selected_day]
    }
    counts: Dict[str, int] = defaultdict(int)
    for offset in range(1, history_days + 1):
        history_day = selected_day - timedelta(days=offset)
        present = {
            canonical_name(name, prefixes) for name, _ in entries[history_day]
        }
        for name in present:
            counts[name] += 1
    return sorted(
        (name, count)
        for name, count in counts.items()
        if count > threshold_days and name not in present_today
    )


def run(args: argparse.Namespace) -> int:
    """Run the listing and optional habit check."""

    tsd_cli.get_config()
    config = tsd_cli.G_CONFIG
    series_dir = resolve_series_dir(config)
    history_start = args.day - timedelta(days=args.habit_history_days)
    first_day = args.day if args.no_habit_threshold_check else history_start
    try:
        entries = read_entries(series_dir, first_day, args.day)
    except RuntimeError as exc:
        print(f"tsd-today: {exc}", file=sys.stderr)
        return 1

    day_text = args.day.isoformat()
    for name, value in entries[args.day]:
        print(f"{name:<30}  {day_text}  {value:8.1f}")

    if args.no_habit_threshold_check:
        if args.verbose:
            print("Habit threshold check disabled.", file=sys.stderr)
        return 0

    prefixes = equivalence_prefixes(config)
    if args.verbose:
        prefix_text = ", ".join(prefixes) if prefixes else "(none)"
        print(
            "Habit threshold check: "
            f"day={day_text}, history={history_start.isoformat()}.."
            f"{(args.day - timedelta(days=1)).isoformat()}, "
            f"present on more than {args.habit_threshold_days} of "
            f"{args.habit_history_days} days, prefixes={prefix_text}",
            file=sys.stderr,
        )
    absences = habitual_absences(
        entries,
        args.day,
        args.habit_history_days,
        args.habit_threshold_days,
        prefixes,
    )
    if absences:
        print(file=sys.stderr)
    for name, count in absences:
        print(
            f"  -> Warning: habitual entry {name!r} is absent on {day_text} "
            f"(present on {count} of the preceding "
            f"{args.habit_history_days} days).",
            file=sys.stderr,
        )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Command-line entry point."""

    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
