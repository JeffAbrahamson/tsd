# Plotting TSD series

`tsd-plot` shows chronological data. `tsd-season-plot` projects data into
repeated yearly, monthly, or weekly periods. They intentionally provide
different views while sharing the interpretation of cumulative readings.

## Date ranges

By default, `tsd-plot` uses the full series. Use `--start YYYY-MM-DD` and/or
`--end YYYY-MM-DD` to select an inclusive date range. An omitted endpoint
leaves that side unbounded. Alternatively, supply `--duration-days DAYS` with
exactly one endpoint to select that many calendar days, including both
endpoints:

```sh
tsd-plot mass --start 2024-01-01 --end 2024-01-31
tsd-plot mass --start 2024-01-01 --duration-days 31
tsd-plot mass --end 2024-01-31 --duration-days 31
```

These commands select the same days. Duration must be a positive integer;
duration alone, all three options together, and reversed ranges are errors.

Selection happens before summation, binning, smoothing and statistics. Bins
retain their usual calendar alignment and may be labelled before the start
date, but only selected days contribute. Cumulative usage is inferred from
the full source readings, then clipped to the selected days with its rate
preserved. The readings view shows only actual readings within the range;
it may therefore be empty even when inferred usage covers the range.

## Plot format and EWMA

Set the chronological plot style and add an exponentially weighted moving
average (EWMA) in a series' sidecar file, for example `mass.cfg`:

```ini
format=scatter
ewma=true
ewma_halflife_days=30
```

`format` accepts the same values and unambiguous abbreviations as `--format`:
`auto`, `bar`, `interval`, `line`, `scatter`, and `stacked`. Its default is
`scatter` when `y_range=data` and `auto` otherwise. An explicit `format=auto`
or `--format auto` selects the usual automatic style even with `y_range=data`.
The `readings` view keeps its fixed step-and-marker style by default.
`ewma` defaults to false and accepts true/false, yes/no, on/off or 1/0.
The half-life defaults to 30 elapsed days and must be finite and positive;
setting it alone does not enable EWMA. Larger half-lives give smoother trends.

The first finite observation initialises the average. At each subsequent
observation, the previous average's weight is `2 ** (-elapsed_days / half_life)`;
the new value receives the remaining weight. Decay follows calendar time,
including gaps and fractional days, rather than the number of observations.
Non-finite values are skipped; repeated timestamps give the new value zero
weight. No readings are inserted into gaps.

EWMA follows the series after summation and binning. For cumulative usage it
smooths the displayed interval rates at their midpoints, including zero-rate
reset intervals, and replaces the default Gaussian trend. In `--view readings`
it smooths the raw readings; `--view both` adds a separate EWMA to each panel.
For stacked bars, each line smooths its individual series' values.

CLI overrides are `--format scatter`, `--ewma`, `--no-ewma`, and
`--ewma-halflife-days 14`. `--no-smooth` hides all smoothing overlays, including
EWMA. `--smooth-days` configures the Gaussian trend and cannot be combined with
enabled EWMA; use `--no-ewma` to select Gaussian smoothing again. Existing
Gaussian smoothing remains unchanged when EWMA is disabled.

For multiple inputs, explicit sidecar preferences must agree for each option;
an omitted option imposes no preference. CLI overrides resolve conflicts per
option. These settings apply only to `tsd-plot`. The `readings` view retains
its fixed step-and-marker style and requires `format=auto` (or `--format auto`).

## Y-axis range

For a series such as body mass, fit the y-axis around its values by adding
these settings to its sidecar file (`mass.cfg`):

```ini
y_range=data
y_margin=0.05
```

`y_range=data` uses the minimum and maximum displayed values, with padding at
each end equal to `y_margin` times their span. The default margin is `0.05`
(5% at each end); it must be finite and non-negative. `y_range=auto` (the
default) preserves the plot style's normal scaling, including the zero
baseline for bars. A margin alone does not select data fitting.

Override sidecar settings with `--y-range data`, `--y-range auto`, or
`--y-margin 0.1`. For multiple inputs, explicit sidecar settings must agree
for each option; files without that option impose no preference. A CLI
override resolves conflicts for its option.

Limits follow the displayed values after differencing, summation and binning,
including smoothed trends and cumulative heights in stacked bars. Artificial
bar baselines and missing observations do not extend the fitted range. With
`--view both`, each panel is fitted independently. Constant data gets padding
of at least 5% of its absolute value (or 0.05 for values below one in absolute
value), even when the requested margin is zero. Empty or entirely non-finite
data leaves the axis limits unchanged.

These settings apply to `tsd-plot` only; `tsd-season-plot` ignores them.

## Cumulative readings

A sidecar file named `<series>.cfg` can mark a series as cumulative:

```text
diff_type=1
```

Both plotting commands honor that setting. `--diff` forces cumulative
interpretation for every input, while `--no-diff` forces direct plotting.
Command-line options take precedence over sidecar configuration.

These options determine what the stored numbers mean; they do not choose what
to draw. In `tsd-plot`, `--view` independently chooses the representation:

* `auto` shows inferred usage for cumulative inputs and ordinary values for
  direct inputs.

* `readings` shows raw cumulative measurements with markers and a step line
  carrying the last known reading forward. It requires cumulative inputs.

* `usage` shows inferred usage intervals and requires cumulative inputs.

* `both` uses aligned reading and usage panels and requires cumulative inputs.

`tsd-season-plot` has no `--view` option. It always shows inferred usage for
cumulative inputs because raw cumulative readings are not seasonally useful.

Successive cumulative readings define measurement intervals. Usage is the
non-negative change divided by the number of elapsed days. A falling reading
is treated as a meter reset: its displayed rate is zero and it is omitted from
chronological trend fitting.

The chronological plot displays each inferred average across the whole
measurement interval, marks the interval midpoint, and overlays a Gaussian
trend. The automatic Gaussian width is the median non-reset measurement
interval. Use `--smooth-days` to override it or `--no-smooth` to hide it.

The seasonal plot marks interval midpoints and draws their extent across each
seasonal row. Heatmaps distribute the inferred average rate across every day
covered by the interval instead of assigning it to the final reading date.

## Aggregation semantics

For chronological summation and binning, `tsd-plot` expands interval averages
onto the calendar days they cover. This makes a bin mean a mean daily rate and
a bin sum the inferred amount used during those days.

For cumulative series, seasonal `--sum` expands each non-reset interval into
its inferred daily rate and uses strict shared coverage: a date contributes
only when every requested series supports it. A reset interval is missing for
this aggregation, not zero, so dates touched by a reset are excluded. The
source interval spans and midpoint observations remain visible. Hollow square
markers identify the inferred daily aggregate and keep it visually distinct
from actual interval observations.

With cumulative `--sum`, heatmaps use the shared-coverage aggregate rather than
the individual source series. `--heatmap-mode mean` is the average inferred
daily rate at each seasonal position, `sum` is the total inferred amount over
the supporting days, and `count` is the number of supporting daily estimates.
Without `--sum`, cumulative heatmaps continue to show each series' interval
coverage; reset intervals remain visible as zero in that standalone display.
