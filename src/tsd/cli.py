#!/usr/bin/python3

"""Maintain daily time series data."""


import datetime
import getopt
import os
from pathlib import Path
import subprocess
import sys

import dateutil.parser


G_VERSION = 0.1
G_CONFIG = {}
CONFIG_SUBPATH = Path("tsd") / "config"


# ############################################################
# Time series management


def recent_data(series, verbose):
    """Show recent values for the series.

    If verbose, show more values.
    If testing, return array of lines to print without printing.
    """

    sname = series_name(series, verbose)

    with open(sname, "r", encoding="UTF-8") as series_fp:
        lines = series_fp.read().splitlines()
    if verbose:
        my_lines = lines[-10:]
    else:
        my_lines = lines[-2:]
    if G_CONFIG["testing"]:
        return my_lines
    for line in my_lines:
        print(line)


def create_series(series, diff, verbose):
    """Initialize a new series.

    series - name of the new series
    diff   - if True, the series is the discrete derivative of the data points
    """
    sname = series_name(series, verbose, create=True)
    open(sname, "w").close()

    # For now, we have nothing to write to config if not a diff sequence
    if diff:
        with open(series_config_name(sname), "w") as series_fp:
            # opposite would be 'diff_type='
            series_fp.write("diff_type=1\n")
            series_fp.close()


def add_point(series, when, value, verbose=False):
    """Add (when, value) to series."""

    sname = series_name(series, verbose, create=False)
    with open(sname, "a") as series_fp:
        new_line = "{0}\t{1}\n".format(when, value)
        series_fp.write(new_line)
        if verbose:
            print(new_line)
    return


def show_series_config(sname, verbose=False):
    """Display the series config values.

    If verbose, include comments.
    If testing, return what we would have printed
    """
    config_text = _show_series_config(sname, verbose=verbose)
    if G_CONFIG["testing"]:
        return config_text
    print(config_text)


def _show_series_config(sname, verbose=False):
    """Display the series config values.

    If verbose, include comments.
    """
    config_lines = _get_config_raw(
        series_name(series_config_name(sname), verbose=verbose)
    ).splitlines()
    if verbose:
        return config_lines
    config_text = ""
    for line in config_lines:
        if line[0] != "#":
            config_text += line + "\n"
    return config_text


def edit_series_config(series, verbose):
    """Edit the series config values."""

    config_name = series_config_name(series_name(series, verbose))
    editor = os.environ.get("EDITOR")
    if not editor:
        print("EDITOR is not defined in the environment.")
        return
    # Probably better would be to make a copy and edit the copy
    edit_command = editor.split()
    edit_command.append(config_name)
    subprocess.call(edit_command)
    return


def list_series(verbose=False):
    """List available series.

    If verbose, note configs.
    """

    series = dict()
    series_dir = series_dir_name()
    for filename in os.listdir(series_dir):
        if filename.endswith("~"):
            continue
        if filename.endswith(".cfg"):
            if verbose:
                series[filename[:-4]] = True
        else:
            if filename not in series:
                series[filename] = False
    if G_CONFIG["testing"]:
        return series
    for [time_series_name, val] in series.items():
        if verbose:
            print(
                "{0}  {1}".format(
                    time_series_name, "[has config]" if val else ""
                )
            )
        else:
            print(time_series_name)
    return


def list_commands():
    """List available commands on a series.

    Useful for bash command completion.
    """

    commands = ["edit", "config", "init"]
    commands.sort()
    return commands


def series_dir_name():
    """Return the name of the series directory."""
    series_dir = G_CONFIG["series_dir"]
    if not os.path.exists(series_dir):
        try:
            os.mkdir(series_dir, 0o700)
        except OSError as err:
            print(
                "Failed to create directory for data series: {0}".format(
                    series_dir
                )
            )
            print(err)
            sys.exit(1)
    perms = os.stat(series_dir)
    if not G_CONFIG.get("testing") and perms.st_mode & 0o777 != 0o700:
        sys.stderr.write(
            "Warning: data directory " + series_dir + " is not 0700\n"
        )
    return series_dir


def series_name(series, verbose, create=False):
    """Compute the filename of the series and return it.

    If create, it must not exist.
    If not create, it must exist.
    Else we exit.
    """
    series_dir = series_dir_name()
    sname = series_dir + series
    exists = os.path.exists(sname)
    if not exists:
        if not create:
            print('Series "%s" does not exist, use init to create.' % series)
            if verbose:
                print("  (filename=%s)" % sname)
            sys.exit(1)
        if verbose:
            print('Will create series "%s"' % series)

    if exists and create:
        print('Series "%s" exists, creation not permitted.' % series)
        if verbose:
            print("  (filename=%s)" % sname)
        sys.exit(1)

    return sname


def series_config_name(sname):
    """Provide name of config file."""

    return sname + ".cfg"


def series_config(sname):
    """Return config as a dict.

    Note that values are always strings.  Client must
    do the cast if needed.
    """
    config_name = series_config_name(sname)
    config = _get_config(config_name)
    return config


# ############################################################
# Admin and options


def copyright_short():
    """Print copyright."""

    print("Time Series Data (tsd), copyright 2011, by Jeff Abrahamson.")
    print("Version ", G_VERSION)
    return


def copyright_long():
    """Print copyright and GPL info."""

    print(
        """Time Series Data (tsd)
Copyright (C) 2011 by Jeff Abrahamson

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
    return


def usage(verbose):
    """Print a usage message."""

    if verbose:
        copyright_long()
    else:
        copyright_short()
    print()
    print(
        """tsd -VhL
tsd series
tsd series <value>
tsd series [-v] %s

    -v   verbose output
    -V   print version number and exit
    -h   print this help message
    -d   use date rather than current date
    -D   when used with init, indicates the series is cumulative
         (i.e., the data is the difference between successive points)
    -L   list available series (with -v, show more info)
    -C   list available commands that act on a series

    series  is a time series name.  By itself, prints the last few values
            of the series.  If it is followed by a value, that value is
            assigned to the date (default is today, cf. -d).

    config  display series configuration (with -v, include comments)
    edit    permit editing of series configuration
    init    initializes a new time series
    Examples:
            $ tsd temp init          # Create the time series calle temp
            $ tsd temp 22.3          # It is 22.3 degrees today
            $ tsd temp               # will print today's date and temperature
"""
        % "|".join(list_commands())
    )
    return


def get_opts():
    """Get options."""

    options = {}
    options["verbose"] = False
    options["args"] = []
    options["date"] = datetime.date.today()
    options["diff"] = False  # only meaningful for init
    options["list"] = False
    options["commands"] = False

    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "hvVd:DLC")
    except getopt.GetoptError:
        usage(False)
        sys.exit(1)

    for option_flag, option_arg in opts:
        if option_flag == "-h":
            usage(options["verbose"])
            sys.exit(0)
        if option_flag == "-v":
            options["verbose"] = True
        if option_flag == "-V":
            copyright_short()
            sys.exit(0)
        if option_flag == "-L":
            options["list"] = True
        if option_flag == "-C":
            options["commands"] = True
        if option_flag == "-d":
            if option_arg[0] == "-":
                delta = datetime.timedelta(int(option_arg))
                options["date"] = datetime.date.today() + delta
            else:
                options["date"] = dateutil.parser.parse(option_arg).date()
        if option_flag == "-D":
            options["diff"] = True

    if args:
        options["args"] = args

    if options["list"]:
        list_series(options["verbose"])
        sys.exit(0)
    if options["commands"]:
        print("\n".join(list_commands()))
        sys.exit(0)
    return options


def get_config():
    """Get the user configuration file as a dict.

    Finding a config file is not mandatory.
    Set global dict G_CONFIG.
    """
    home = Path.home()
    config = {
        "series_dir": str(home / "tsd") + os.sep,
        "testing": 0,
    }
    config.update(_get_config(config_file_name()))
    # Cast what we can
    config["testing"] = bool(config["testing"])
    series_dir = os.path.expandvars(os.path.expanduser(config["series_dir"]))
    config["series_dir"] = series_dir.rstrip(os.sep) + os.sep
    global G_CONFIG
    G_CONFIG = config


def config_file_name():
    """Return the XDG user configuration file name."""

    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return str(Path(config_home) / CONFIG_SUBPATH)
    return str(Path.home() / ".config" / CONFIG_SUBPATH)


def _get_config(filename):
    """Get config file by name.

    Strip lines of form ^#.*$.
    Understand lines of form name=value.
    Return the dictionary of (name, value) pairs.
    Otherwise not very sophisticated.
    """
    config = {}
    for raw_line in _get_config_raw(filename).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, val = line.partition("=")
        if separator:
            config[key.strip()] = val.strip()
    return config


def _get_config_raw(config_name):
    """Return the config as a block of text.

    Includes embedded comments.
    """
    try:
        with open(config_name, "r") as config_fp:
            text = config_fp.read()
        return text
    except IOError:
        return ""


# ############################################################
# Main


def main():
    """Look at input from user, decide what to do, do it."""

    get_config()
    options = get_opts()

    if 0 == len(options["args"]):
        print("Missing time series name.")
        print()
        usage(options["verbose"])
        sys.exit(1)

    series = options["args"][0]
    if 1 == len(options["args"]):
        recent_data(series, options["verbose"])
        return

    command = options["args"][1]
    if "config" == command:
        show_series_config(series, options["verbose"])
        return

    if "edit" == command:
        edit_series_config(series, options["verbose"])
        return

    if "init" == command:
        create_series(series, options["diff"], options["verbose"])
        return

    # Else add a value
    value = float(command)
    add_point(series, options["date"], value, verbose=options["verbose"])
    return


if __name__ == "__main__":
    main()
