#!/usr/bin/python3

"""Maintain daily time series data."""


from math import sqrt
import argparse
import datetime
import os
import subprocess
import sys
import tempfile
from tabulate import tabulate
import dateutil.parser


K_VERSION = 1.0
G_CONFIG = {}


# ############################################################
# Time series management


def recent_data(args):
    """Return recent values for the series.

    If verbose, return more values.
    """

    sname = series_pathname(args)

    with open(sname, "r", encoding="UTF-8") as series_fp:
        lines = series_fp.read().splitlines()
    if args.verbose:
        my_lines = lines[-10:]
    else:
        my_lines = lines[-2:]
    return my_lines


def create_series(args):
    """Initialize a new series."""
    sname = series_pathname(args)
    with open(sname, "w", encoding="UTF-8") as fp_new_series:
        fp_new_series.close()

    if args.diff:
        config_name = series_config_name(sname)
        with open(config_name, "w", encoding="UTF-8") as series_fp:
            # Opposite would be 'diff_type='.
            series_fp.write("diff_type=1\n")
            # Convolve_width governs convolution width, start with a
            # hopefully reasonable value.
            series_fp.write("convolve_width=20\n")
            series_fp.close()


def add_point(value, args):
    """Add (when, value) to series."""

    sname = series_pathname(args)
    with open(sname, "a", encoding="UTF-8") as series_fp:
        new_line = f"{args.effective_date}\t{value}\n"
        series_fp.write(new_line)
        if args.verbose:
            print(new_line)


def edit_series_config(args):
    """Open $EDITOR on the series config file."""

    config_name = series_config_name(series_pathname(args))
    editor = os.environ.get("EDITOR")
    if not editor:
        print("EDITOR is not defined in the environment.")
        return
    edit_command = editor.split()
    edit_command.append(config_name)
    if args.verbose:
        print(f"Running {edit_command}")
    subprocess.call(edit_command)
    return


def enumerate_series_names(args):
    """Return the list of available series."""

    series = []
    if args.verbose:
        print(f"Looking for data in {args.series_dir}")
    for filename in os.listdir(args.series_dir):
        if args.verbose:
            print(f"  Considering filename={filename}")
        if filename.endswith("~"):
            continue
        if not filename.endswith(".cfg"):
            series.append(filename)
    series.sort()
    return series


def series_base_name(args):
    """Return the series base name."""
    if len(args.args) == 0:
        print("No series name specified.")
        sys.exit(1)
    return args.args[0]


def series_pathname(args):
    """Compute the full pathname of the series and return it.

    If create, it must not exist.
    If not create, it must exist.
    Else we exit with an error.
    """
    sname = os.path.join(args.series_dir, series_base_name(args))
    if not os.path.exists(sname):
        if not args.init:
            print(
                f'Series "{series_base_name(args)}" does not exist, use init to create.'
            )
            if args.verbose:
                print(f"  (filename={sname})")
            sys.exit(1)
        if args.verbose:
            print(f'Will create series "{series_base_name(args)}"')
    if args.init:
        print(
            f'Series "{series_base_name(args)}" exists, creation not permitted.'
        )
        if args.verbose:
            print(f"  (filename={sname})")
        sys.exit(1)
    return sname


def series_config_name(sname):
    """Given filename of series, return name of config file."""

    return sname + ".cfg"


# ############################################################
# Plotting


def plot_series(args):
    """Plot the series."""

    sname = series_pathname(args)
    config = series_config(args)
    width = int(config.get("convolve_width", 20))
    diff = bool(config.get("diff_type", False))

    [_, tmp_filename] = tempfile.mkstemp(".txt", "tsd_tempfile_")

    points = plot_get_points(sname)
    if diff:
        points = plot_discrete_derivative(points)
    smooth = plot_convolve(points, width)
    plot_put_points(tmp_filename, smooth)
    plot_display(tmp_filename)
    os.unlink(tmp_filename)


def plot_get_points(sname):
    """Read the data file, return as an array.

    Array format is [date, offset from first date, value].
    """

    unsorted_points = {}
    with open(sname, "r", encoding="UTF-8") as series_fp:
        for line in series_fp:
            [date_str, value_str] = line.split()
            date = dateutil.parser.parse(
                date_str, yearfirst=True, dayfirst=False
            ).date()
            unsorted_points[date] = float(value_str)

    first_day = {}
    points = []
    pairs = list(unsorted_points.items())
    pairs.sort(key=lambda x: x[0])
    for date, value in pairs:
        if 0 not in first_day:
            first_day[0] = date
        points.append(
            {
                "date": date,
                "offset": (date - first_day[0]).days,
                "value": value,
            }
        )
    return points


def plot_discrete_derivative(points):
    """Compute the discrete derivative of a point set.

    Expect an array of {date, offset from first date, value} keys.
    Modify value to be the difference of this and the previous
    value, normalized by the time passed between them.
    Drops the first point.
    """
    out_points = []
    last_point = []
    for point in points:
        if not last_point:
            base_offset = point["offset"]
        else:
            out_date = point["date"]
            out_offset = point["offset"] - base_offset
            out_value = (point["value"] - last_point["value"]) / (
                point["offset"] - last_point["offset"]
            )
            out_points.append(
                {"date": out_date, "offset": out_offset, "value": out_value}
            )
        last_point = point
    return out_points


def plot_put_points(filename, points):
    """Print data."""

    with open(filename, "w", encoding="UTF-8") as series_fp:
        for point in points:
            date = point["date"]
            if "offset" in point:
                offset = point["offset"]
            else:
                offset = 0
            value = point["value"]
            if "convolved" in point:
                convolved = point["convolved"]
            else:
                convolved = value
            if "stdev" in point:
                stdev = point["stdev"]
            else:
                stdev = 0
            value_plus = convolved + stdev
            value_minus = convolved - stdev
            value_plus = point["max"]
            value_minus = point["min"]
            series_fp.write(
                "%4d %14s %f %f %f %f %f\n"
                % (
                    offset,
                    date.isoformat(),
                    value,
                    convolved,
                    value_plus,
                    value_minus,
                    stdev,
                )
            )
        series_fp.flush()


def plot_convolve(points, num_days):
    """Given an array of dictionaries with keys date, offset (from
    least date), and value, add a key/value pair that is the simple
    triangle convolution of value for num_days days before and after.  The
    array is in sorted order by point.date.

    Also add a key/value pair for standard deviation, where we use the
    triangle convolution for the mean."""

    start = 0  # No sense looking earlier than this for valid points
    for i in range(len(points)):
        while points[i]["offset"] - points[start]["offset"] > num_days:
            start += 1
        points[i]["convolved"] = plot_convolve_from(points, start, i, num_days)
        points[i]["min"] = plot_convolve_min(points, start, i, num_days)
        points[i]["max"] = plot_convolve_max(points, start, i, num_days)
        points[i]["stdev"] = plot_standard_deviation(
            points, start, i, num_days
        )
    return points


def plot_convolve_from(points, start, center, width):
    """Compute a triangular convolution from points[start] centered at
    points[center] and of width width."""

    numer = 0.0
    denom = 0
    for i in range(start, len(points)):
        dist = abs(points[i]["offset"] - points[center]["offset"])
        if dist > width:
            return numer / denom
        numer += points[i]["value"] * (width - dist) / width
        denom += float(width - dist) / width
    return numer / denom


def plot_convolve_min(points, start, center, width):
    """Compute min value from points[start] centered at
    points[center] and of width width."""

    the_min = points[start]["value"]
    for i in range(start, len(points)):
        dist = abs(points[i]["offset"] - points[center]["offset"])
        if dist > width:
            return the_min
        the_min = min(the_min, points[i]["value"])
    return the_min


def plot_convolve_max(points, start, center, width):
    """Compute max value from points[start] centered at
    points[center] and of width width."""

    the_max = points[start]["value"]
    for i in range(start, len(points)):
        dist = abs(points[i]["offset"] - points[center]["offset"])
        if dist > width:
            return the_max
        the_max = max(the_max, points[i]["value"])
    return the_max


def plot_standard_deviation(points, start, center, width):
    """Compute the standard deviation from points[start], centered at
    points[center], with width width."""
    sum_plain = 0.0
    sum_squares = 0.0
    num = 0
    for i in range(start, len(points)):
        dist = abs(points[i]["offset"] - points[center]["offset"])
        if dist > width:
            return plot_standard_deviation_sub(sum_plain, sum_squares, num)
        sum_plain += points[i]["value"]
        sum_squares += points[i]["value"] * points[i]["value"]
        num += 1
    return plot_standard_deviation_sub(sum_plain, sum_squares, num)


def plot_standard_deviation_sub(sum_points, sum_squares, num_points):
    """Return the standard deviation given the sum of the samples, the
    sum of the squares of the samples, and the number of samples."""
    sq_sum = sum_points * sum_points
    sq_num = num_points * num_points
    return sqrt(
        sum_squares / num_points - 2 * sq_sum / sq_num + sq_sum / sq_num
    )


def plot_display(filename):
    """Plot the data in filename."""

    plot_instructions = """
set xdata time
set timefmt "%Y-%m-%d"
set format x "%m-%Y"
set multiplot
set origin 0,.2
set size 1,.8"""
    plot_instructions += """
plot "{filename}" using 2:3 title "Measurements" lt -1 pt 13 ps .45, \\
     "{filename}" using 2:4 title "Convolution, 20 day triangle" with lines lt 4, \\
     "{filename}" using 2:5 title "Convolution plus std dev" with lines lt 1, \\
     "{filename}" using 2:6 title "Convolution minus std dev" with lines lt 1
set origin 0,0
set size 1,.2
set yrange [0:]
plot "{filename}" using 2:7 title "Standard Deviation" with lines lt 10
unset multiplot
set size 1,1
""".format(
        filename=filename
    )
    # pause mouse close

    pipe_fd = subprocess.Popen(["gnuplot", "-persist"], stdin=subprocess.PIPE)
    pipe_fd.communicate(plot_instructions.encode())
    pipe_fd.wait()


def copyright_short():
    """Print copyright."""

    print("Time Series Data (tsd), copyright 2011-2023, by Jeff Abrahamson.")
    print(f"Version {K_VERSION}")


def copyright_long():
    """Print copyright and GPL info."""

    copyright_short()
    print(
        """
This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
    """
    )


def get_args():
    """Get commandline arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Hopefully be more usefully verbose",
    )
    parser.add_argument(
        "--version",
        "-V",
        action="store_true",
        help="Print the version and exit",
    )
    parser.add_argument(
        "--date",
        "-d",
        default=datetime.date.today().strftime("%F"),
        help="Use date rather than current date, may be a date in the"
        " current month (integer), or a date in YYYY-MM-DD format,"
        " may be combined with -b",
    )
    parser.add_argument(
        "--days-before",
        "-b",
        default=0,
        help="Negative offset (integer) from the current date,"
        " may be combined with -d",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="On series creation (init), "
        "indicate the series is the discrete derivative of the data",
    )
    parser.add_argument(
        "--list", "-L", action="store_true", help="Print available series"
    )
    parser.add_argument(
        "--edit", "-e", action="store_true", help="Open $EDITOR series config"
    )
    parser.add_argument(
        "--config",
        action="store_true",
        help="Display series config (stripping comments unless -v)",
    )
    parser.add_argument(
        "--series-dir",
        default=os.path.join(os.getenv("HOME"), "tsd"),
        help="Directory for series",
    )
    parser.add_argument("--init", action="store_true", help="Init new series")
    parser.add_argument("--plot", action="store_true", help="Plot series")
    parser.add_argument("args", nargs="*", help="Series name")
    args = parser.parse_args()
    set_effective_date(args)
    if args.verbose:
        print(args)

    if args.version:
        copyright_short()
        sys.exit(0)
    if args.list:
        for series in enumerate_series_names(args):
            print(series)
        sys.exit(0)
    return args


def set_effective_date(args):
    """Return the effective date for adding a new point to the series."""
    delta = datetime.timedelta(int(args.days_before))
    try:
        # If args.date is an integer, it's the day of the current
        # month.  Note that the cast to int(), which is necessary
        # because argparse provides strings, will throw if the value
        # is a YYYY-MM-DD date.  That exception acts as our
        # conditional.
        today = datetime.date.today()
        the_day = today.replace(day=int(args.date))
        if args.verbose:
            print("Looks like an absolute day of month.")
    except ValueError:
        # Otherwise, it's a date in YYYY-MM-DD format.
        if args.verbose:
            print("Looks like a day in %F format.")
        the_day = dateutil.parser.parse(
            args.date, yearfirst=True, dayfirst=False
        ).date()

    setattr(args, "effective_date", the_day - delta)
    if args.verbose:
        print(f"Effective date is {args.effective_date}")


def series_config_text(args):
    """Read the config file for a series.

    The file format is a set of "key=value" pairs, one per line.

    Hash serves as a comment introducer: it and anything following on
    the line is ignored.

    Return a dictionary of the key/value pairs, which is silently
    empty if the config file does not exist for the named series.

    """
    config_file = series_config_name(series_pathname(args))
    if not os.path.exists(config_file):
        if args.verbose:
            print(f"No config file {config_file}")
        return ""
    with open(config_file, "r", encoding="UTF-8") as fd_config:
        return fd_config.read()


def series_config(args):
    """Parse the config file contents and return a dict."""
    config_text = series_config_text(args)
    config = {}
    for line in config_text.split("\n"):
        line_without_comment = line.split("#")[0]
        line_without_comment = line.strip()
        if not line_without_comment:
            continue
        key, value = line_without_comment.split("=", 1)
        config[key.strip()] = value.strip()
    return config


def main():
    """Look at input from user, decide what to do, do it."""

    args = get_args()

    if 0 == len(args.args):
        print("Missing time series name.")
        sys.exit(1)
    # Start with flags that determine what we do.
    if args.config:
        if args.verbose:
            config_text = series_config_text(args)
            print(config_text)
        else:
            config = series_config(args)
            print(tabulate, config, tablefmt="plain")
        return
    if args.edit:
        edit_series_config(args)
        return
    if args.init:
        create_series(args)
        return
    if args.plot:
        plot_series(args)
        return
    # If no action flags and only one argument, show recent data.
    if 1 == len(args.args):
        lines = recent_data(args)
        for line in lines:
            print(line)
        return

    if len(args.args) > 2:
        print(f"Excess time series names: {', '.join(args.args)}.")
        sys.exit(1)

    # Else add a value
    value = float(args.args[1])
    add_point(value, args)
    return


if __name__ == "__main__":
    main()
