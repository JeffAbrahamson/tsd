# Plotting TSD series

`tsd-plot` shows chronological data. `tsd-season-plot` projects data into
repeated yearly, monthly, or weekly periods. They intentionally provide
different views while sharing the interpretation of cumulative readings.

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
