# Plotting TSD series

`tsd-plot` shows chronological data. `tsd-season-plot` projects data into
repeated yearly, monthly, or weekly periods. They intentionally provide
different views while sharing the interpretation of cumulative readings.

## Saving to a file

`tsd-plot` and `tsd-season-plot` open a window by default. `--output FILE`
(or `-o FILE`) saves the plot instead, choosing the format from the
extension (`.png`, `.pdf`, `.svg` and the other formats matplotlib
supports). Saving never needs a display, so it also works over SSH or in a
Wayland session without Xwayland:

```sh
tsd-plot mass --start 2024-01-01 -o mass.png
tsd-season-plot mass --period month -o mass-by-month.pdf
```

## Reading density

Smoothing, interval bars, binning and seasonal heatmaps all draw continuous
shapes across stretches with few or no readings. `--density` shows where the
plotted curve rests on real data:

```sh
tsd-plot mass --format scatter --ewma --density
tsd-season-plot meter --density
```

To show it by default, set it in the series' sidecar file (`mass.cfg`):

```ini
density=true
density_days=15
```

`density` accepts the same true/false values as `ewma` and applies to both
commands; `--no-density` turns it off for one invocation. `density_days`
applies to `tsd-plot` only and, like `ewma_halflife_days`, does not enable
the strip by itself. Explicit settings in multiple sidecars must agree unless
overridden on the command line.

In `tsd-plot` a strip below the plot (below both panels with `--view both`)
shows, for each input series:

* a rug with one tick per actual reading date, in a band below zero;
* a Gaussian kernel density estimate of the reading dates, scaled to readings
  per week rather than normalised to integrate to one, so its axis reads
  directly ("about seven a week here, none there"). Every curve spans the
  whole strip, falling to zero where its series has no readings. The legend
  gives each curve's bandwidth.

The bandwidth defaults to the median gap between successive readings, with a
floor of 7 days so that a daily series with the odd missed day stays steady.
Set it with `--density-days DAYS`. Near a series' first and last readings
the kernel is renormalised over the days between them, so a steady series
does not appear to thin out at its ends, whatever else is plotted. That
correction never exceeds the factor of two that applies exactly at an end,
so a lone reading still looks sparse. Beyond its ends the curve keeps that
factor, so it stays continuous, and falls to zero within about two
bandwidths; the rug marks the exact last reading.

In `tsd-season-plot` marginal strips count actual readings per position in
the period (above the plot) and per row (to its right), stacked by series and
coloured like the points. With `--sum` of direct values each source takes
its own colour, distinct from the sum's and named in a legend; `--color`
paints every source alike, so the stack then shows only the total. A cumulative series' points are interval midpoints
and its bands interval spans; the marginals count the readings themselves.
Because the final reading closes its interval rather than starting one, its
row is added to the plot when needed.

Both commands count the source readings before summation (and, in
`tsd-plot`, binning), since those replace readings with evenly spaced values;
`tsd-plot` counts only readings within its selected date range. With `--sum`,
each source series is shown separately, in colours other than the sum's.

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

## Point threshold colours

Highlight points outside chosen thresholds in scatter and line plots:

```sh
tsd-plot mass --format scatter --colour-below 65 --colour-above 67
```

Save the settings in `mass.cfg` to use them automatically:

```ini
format=scatter
colour_below=65
colour_above=67
```

Values strictly below 65 are teal green (`#009E73`); values strictly above
67 are warm vermilion (`#D55E00`). Points exactly on either threshold keep
the usual series colour, as do all points between them. Either threshold
can be used alone. Highlighted points use the same transparency as the
other points, including when EWMA fades scatter points. Connecting lines
and smoothing curves retain their usual colours.

The legend gives each band's share of the finite displayed points across
all series, for example `Below 65 (20%)`, `65 to 67 (60%)` and
`Above 67 (20%)`. The middle band's entry has no marker, as its points
keep their series colours; with one threshold it reads `65 or above` or
`67 or below`. Entries appear only for bands with points. A non-empty
band never shows as 0% or 100%: small shares show as `<1%` and
near-complete ones as `>99%`. Each share is rounded separately, so the
total may differ from 100% by a point or so.

Use `--below-colour` / `--above-colour` (sidecar keys `below_colour` /
`above_colour`) to choose other Matplotlib colours. Quote hexadecimal
colours on the command line. `--no-threshold-colours` disables all threshold
settings for that invocation, including settings supplied on the CLI.
CLI values override sidecar settings individually. Explicit settings in
multiple sidecars must agree unless overridden on the CLI.

Thresholds must be finite, and the lower threshold must be less than the
upper threshold. Comparisons use the displayed values after summation and
binning, or displayed interval rates for cumulative usage. The feature
requires scatter or line format. In `--view both` it applies only to the
usage panel; it does not apply to `--view readings`.

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

## Unrecognised sidecar settings

Both commands warn on standard error about any sidecar line they do not
understand: a setting neither command reads, or a non-comment line without
`=`. Where a known setting is close, the warning suggests it, for example
`density_days` for `density-days`. Settings are spelt with underscores.
Settings meant for one command, such as `y_range`, do not draw a warning from
the other. Comment out notes with `#` to silence their warnings.

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
