# tsd

`tsd` is a command-line tool for managing simple daily time series.

A series is a set of `(date, float)` pairs, typically one value per day for
things like meter readings, weight, or temperature.

## Project layout

This repository now follows a standard Python layout:

- `src/tsd/`: installable package and CLI entry point
- `tests/`: unit tests and test fixtures
- `scripts/`: auxiliary analysis scripts
- `shell/`: shell completion and convenience helpers
- `docs/`: notes and design documents

## Installation

```bash
make install
```

That installs the `tsd` and `tsd-today` commands with `pipx` in editable mode
and copies the shell helper to `~/.dotfiles/bash/tsd` by default. If
`~/.local/bin` is not on your `PATH`, add it in your shell startup file. To
enable completion and helper functions, source the installed shell helper from
your shell startup file.

The shell helper includes bash completion plus convenience functions such as
`tsd-table`, `tsd-value`, `tsd-m-count`, `tsd-y-count`, `tsd-m-sum`,
`tsd-y-sum`, `tsd-group`, `tsd-gv`, and related filters. Those helpers use
`TSD_DIR` when it is set and otherwise fall back to `~/tsd`.

Installation also exposes two utilities for estimating when a decreasing
series is likely to hit zero:

- `tsd-time-to-empty` uses a state-space random-walk rate model.
- `tsd-mc-time-to-empty` resamples historical daily consumption rates.

If you prefer non-default `pipx` locations, `make install` accepts overrides
such as `PIPX_HOME=...`, `PIPX_BIN_DIR=...`, and `PIPX_STATE_HOME=...`.

## Usage

```text
tsd -VhL
tsd series
tsd series <value>
tsd series [-v] config|edit|init|plot

    -v   verbose output
    -V   print version number and exit
    -h   print this help message
    -d   use date rather than current date
    -D   when used with init, indicates the series is cumulative
         (i.e., the data is the difference between successive points)
    -L   list available series (with -v, show more info)
    -C   list available commands that act on a series
```

Examples:

```bash
tsd temp init
tsd temp 22.3
tsd temp
tsd temp plot
tsd-time-to-empty toothpaste
tsd-time-to-empty -f ./sample-data.txt
tsd-mc-time-to-empty toothpaste
tsd-mc-time-to-empty -f ./sample-data.txt
```

### Daily entries and habit warnings

`tsd-today` lists the entries recorded today. It also warns on stderr about
entries present on more than four of the five preceding calendar days but
absent today:

```text
tsd-today [OPTIONS] [DAY]

DAY is YYYY-MM-DD or an integer offset from today, such as -4.

  -k, --habit-threshold-days K
  -n, --habit-history-days N
      --no-habit-threshold-check
  -v, --verbose
  -h, --help
```

For example, this checks the seven preceding days and warns for entries found
on more than five of them:

```bash
tsd-today --habit-history-days 7 --habit-threshold-days 5
```

### Configuration

User configuration is read from `$XDG_CONFIG_HOME/tsd/config`, defaulting to
`~/.config/tsd/config`. The file contains `key=value` lines:

```text
series_dir=~/tsd
habit_equivalence_prefixes=foo-,bar-
```

`TSD_DIR` overrides `series_dir` for `tsd-today`. Equivalence prefixes combine
matching series for the habit check. With `foo-` configured, entries such as
`foo-bar`, `foo-baz`, and `foo-buz` count as the same habit. When prefixes
overlap, the longest matching prefix is used.

`tsd-mc-time-to-empty` treats each interval without a quantity increase as
uniform daily consumption and excludes refill intervals. It samples those
historical days with replacement until the current quantity is exhausted.
Recent days receive a baseline-plus-Gaussian weight:

```text
weight = 1 + amplitude * exp(-0.5 * (age_days / sigma_days)^2)
```

The Gaussian is centered on the latest reading. The defaults,
`--recency-sigma 60 --recency-amplitude 1`, double the sampling weight at the
latest reading while retaining all older history at its baseline weight.

## Development

```bash
make test
```

The plotting features depend on `gnuplot`. The main package dependency is
`python-dateutil`.
