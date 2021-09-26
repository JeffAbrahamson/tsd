#!/usr/bin/python3

import argparse
import datetime
import dateutil.parser
import matplotlib.pyplot as plt
import os

SERIES_DIR = os.getenv("HOME") + '/tsd/'

def read_series(series_name):
    """Read series and return as a list of (date, value) pairs.

    """
    unsorted_points = dict()
    with open(SERIES_DIR + series_name, 'r') as series_fp:
        for line in series_fp:
            [date_str, value_str] = line.split()
            date = dateutil.parser.parse(date_str).date()
            unsorted_points[date] = float(value_str)

    points = [(k, v) for (k, v) in unsorted_points.items()]
    points.sort(key=lambda kv_pair: kv_pair[0])
    return points

def plot_points(points):
    """Make a scatter plot by year (vertical) and day (horizontal).

    """
    points_by_year = [(d.year, (d - datetime.date(d.year, 1, 1)).days + 1) \
                      for (d, v) in points \
                      if v == 1]
    X = [d for (y, d) in points_by_year]
    Y = [y for (y, d) in points_by_year]
    years = list(set(Y))
    plt.scatter(X, Y)
    plt.yticks(years)
    plt.show()

def main():
    """Do what we do.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--series', '-s', type=str, required=True,
                        help='Name of series to plot.')
    args = parser.parse_args()
    series = read_series(args.series)
    plot_points(series)

if '__main__' == __name__:
    main()
