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

That installs the `tsd` command with `pipx` in editable mode and copies the
shell helper to `~/.dotfiles/bash/tsd` by default. If `~/.local/bin` is not on
your `PATH`, add it in your shell startup file. To enable completion and helper
functions, source the installed shell helper from your shell startup file.

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
```

## Development

```bash
make test
```

The plotting features depend on `gnuplot`. The main package dependency is
`python-dateutil`.
