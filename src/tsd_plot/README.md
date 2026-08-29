# tsd_plot

This package implements the `tsd-plot` and `tsd-season-plot` commands. They
share series loading and cumulative-reading semantics while retaining separate
plotting models and command-line interfaces.

## Contents

* [`cli.py`](cli.py) implements general time-series plotting, binning, and aggregation.
* [`seasonal.py`](seasonal.py) implements seasonal projections and recurring-pattern heatmaps for yearly or weekly views.
* [`series.py`](series.py) loads data and derives reset-safe usage intervals from cumulative readings.
* [`__init__.py`](__init__.py) marks the package and exposes the module namespace.
