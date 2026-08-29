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

## Open aggregation question

For chronological summation and binning, `tsd-plot` expands interval averages
onto the calendar days they cover. This makes a bin mean a mean daily rate and
a bin sum the inferred amount used during those days.

The meaning of `--sum` for cumulative series in a seasonal plot remains
unresolved. Inputs can have different measurement intervals, and assigning an
interval-derived value to one seasonal bin would imply unsupported timing
precision. `tsd-season-plot` therefore rejects that combination for now. Come
back to this after deciding whether summation should operate on inferred daily
rates, interval amounts, or another explicitly defined representation.

The current seasonal heatmap provisionally distributes each interval's average
rate over its covered days. Consequently, `--heatmap-mode sum` sums inferred
daily rates at each seasonal position; it does not assign the whole interval
amount to a month or other seasonal bin. Revisit this definition together with
cross-series seasonal summation.
