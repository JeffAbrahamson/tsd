#!/usr/bin/python


"""Maintain daily time series data."""


import getopt, sys, os, subprocess
import datetime
import dateutil.parser
from math import sqrt
import tempfile


G_VERSION = 0.1
G_CONFIG = {}


# ############################################################
# Time series management

def recent_data(series, verbose):
    """Show recent values for the series.

    If verbose, show more values.
    If testing, return array of lines to print without printing.
    """

    sname = series_name(series, verbose)
    with open(sname, 'r') as series_fp:
        lines = series_fp.read().splitlines()
    if verbose:
        my_lines = lines[-10:]
    else:
        my_lines = lines[-2:]
    if G_CONFIG['testing']:
        return my_lines
    for line in my_lines:
        print line


def create_series(series, diff, verbose):
    """Initialize a new series.

    series - name of the new series
    diff   - if True, the series is the discrete derivative of the data points
    """
    sname = series_name(series, verbose, create=True)
    open(sname, 'w').close()

    # For now, we have nothing to write to config if not a diff sequence
    if diff:
        with open(series_config_name(sname), 'w') as series_fp:
            # opposite would be 'diff_type='
            series_fp.write('diff_type=1\n')
            # convolve_width governs convolution width, start with a
            # hopefully reasonable value
            series_fp.write('convolve_width=20\n')
            series_fp.close()


def add_point(series, when, value, verbose=False):
    """Add (when, value) to series."""

    sname = series_name(series, verbose, create=False)
    with open(sname, 'a') as series_fp:
        new_line = '{0}\t{1}\n'.format(when, value)
        series_fp.write(new_line)
        if verbose:
            print new_line
    return


def show_series_config(sname, verbose=False):
    """Display the series config values.

    If verbose, include comments.
    If testing, return what we would have printed
    """
    config_text = _show_series_config(sname, verbose=verbose)
    if G_CONFIG['testing']:
        return config_text
    print config_text


def _show_series_config(sname, verbose=False):
    """Display the series config values.

    If verbose, include comments.
    """
    config_lines = _get_config_raw(series_name(
        series_config_name(sname),
        verbose=verbose)).splitlines()
    if verbose:
        return config_lines
    config_text = ''
    for line in config_lines:
        if line[0] != '#':
            config_text += line + '\n'
    return config_text


def edit_series_config(series, verbose):
    """Edit the series config values."""

    config_name = series_config_name(series_name(series, verbose))
    editor = os.environ.get('EDITOR')
    if not editor:
        print 'EDITOR is not defined in the environment.'
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
        if filename.endswith('~'):
            continue
        if filename.endswith('.cfg'):
            if verbose:
                series[filename[:-4]] = True
        else:
            if filename not in series:
                series[filename] = False
    if G_CONFIG['testing']:
        return series
    for [time_series_name, val] in series.iteritems():
        if verbose:
            print '{0}  {1}'.format(time_series_name, \
                                    '[has config]' if val else '')
        else:
            print time_series_name
    return


def list_commands():
    """List available commands on a series.

    Useful for bash command completion.
    """

    commands = ['edit', 'config', 'init',  'plot']
    commands.sort()
    return commands


def series_dir_name():
    """Return the name of the series directory."""
    series_dir = G_CONFIG['series_dir']
    if(not os.path.exists(series_dir)):
        try:
            os.mkdir(series_dir, 0700)
        except OSError as err:
            print 'Failed to create directory for data series: {0}'.\
              format(series_dir)
            print err
            sys.exit(1)
    perms = os.stat(series_dir)
    if(perms.st_mode & 0777 != 0700):
        sys.stderr.write("Warning: data directory " \
                             + series_dir + " is not 0700\n")
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
            print 'Series "%s" does not exist, use init to create.' % series
            if verbose:
                print '  (filename=%s)' % sname
            sys.exit(1)
        if verbose:
            print 'Will create series "%s"' % series

    if exists and create:
        print 'Series "%s" exists, creation not permitted.' % series
        if verbose:
            print '  (filename=%s)' % sname
        sys.exit(1)

    return sname


def series_config_name(sname):
    """Provide name of config file."""

    return sname + '.cfg'


def series_config(sname):
    """Return config as a dict.

    Note that values are always strings.  Client must
    do the cast if needed.
    """
    config_name = series_config_name(sname)
    config = _get_config(config_name)
    return config


# ############################################################
# Plotting

def plot_series(series, verbose):
    """Plot the series."""

    sname = series_name(series, verbose)
    config = series_config(sname)
    width = int(config.get('convolve_width', 20))
    diff = bool(config.get('diff_type', False))

    [_, tmp_filename] = tempfile.mkstemp('.txt', 'srd_temp_')

    points = plot_get_points(sname)
    if diff:
        points = plot_discrete_derivative(points)
    smooth = plot_convolve(points, width)
    plot_put_points(tmp_filename, smooth)
    plot_display(tmp_filename)


def plot_get_points(sname):
    """Read the data file, return as an array.

    Array format is [date, offset from first date, value].
    """

    unsorted_points = dict()
    with open(sname, 'r') as series_fp:
        for line in series_fp:
            [ date_str, value_str ] = line.split()
            date = dateutil.parser.parse(date_str).date()
            unsorted_points[date] = float(value_str)

    first_day = dict()
    points = []
    pairs = [(k, v) for (k, v) in unsorted_points.iteritems()]
    pairs.sort(key=lambda(k, v): k)
    for date, value in pairs:
        if 0 not in first_day:
            first_day[0] = date
        points.append({'date': date,
                       'offset': (date - first_day[0]).days,
                       'value': value})
    return(points)


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
        if [] == last_point:
            base_offset = point['offset']
        else:
            out_date = point['date']
            out_offset = point['offset'] - base_offset
            out_value = (point['value'] - last_point['value']) / \
                (point['offset'] - last_point['offset'])
            out_points.append({'date' : out_date,
                               'offset' : out_offset,
                               'value' : out_value})
        last_point = point
    return out_points


def plot_put_points(filename, points):
    """Print data."""

    with open(filename, 'w') as series_fp:
        for point in points:
            date = point['date']
            if('offset' in point):
                offset = point['offset']
            else:
                offset = 0
            value = point['value']
            if('convolved' in point):
                convolved = point['convolved']
            else:
                convolved = value
            if 'stdev' in point:
                stdev = point['stdev']
            else:
                stdev = 0
            value_plus = convolved + stdev
            value_minus = convolved - stdev
            series_fp.write('%4d %14s %4.2f %4.2f %4.2f %4.2f %4.4f\n' % \
                (offset, date.isoformat(), value, convolved, \
                 value_plus, value_minus, stdev))


def plot_convolve(points, num_days):
    """Given an array of dictionaries with keys date, offset (from
    least date), and value, add a key/value pair that is the simple
    triangle convolution of value for num_days days before and after.  The
    array is in sorted order by point.date.

    Also add a key/value pair for standard deviation, where we use the
    triangle convolution for the mean."""

    start = 0    # No sense looking earlier than this for valid points
    for i in xrange(len(points)):
        while((points[i]['offset'] - points[start]['offset'] > num_days)):
            start += 1
        points[i]['convolved'] = plot_convolve_from(points, start, i, num_days)
        points[i]['stdev'] = plot_standard_deviation(points, start, i, num_days)
    return(points)


def plot_convolve_from(points, start, center, width):
    """Compute a triangular convolution from points[start] centered at
    points[center] and of width width."""

    numer = 0.0
    denom = 0
    for i in xrange(start, len(points)):
        dist = abs(points[i]['offset'] - points[center]['offset'])
        if(dist > width):
            return(numer / denom)
        numer += points[i]['value'] * (width - dist) / width
        denom += float(width - dist) / width
    return(numer / denom)


def plot_standard_deviation(points, start, center, width):
    """Compute the standard deviation from points[start], centered at
    points[center], with width width."""
    sum_plain = 0.0
    sum_squares = 0.0
    num = 0
    for i in xrange(start, len(points)):
        dist = abs(points[i]['offset'] - points[center]['offset'])
        if(dist > width):
            return(plot_standard_deviation_sub(sum_plain, sum_squares, num))
        sum_plain += points[i]['value']
        sum_squares += points[i]['value'] * points[i]['value']
        num += 1
    return(plot_standard_deviation_sub(sum_plain, sum_squares, num))


def plot_standard_deviation_sub(sum_points, sum_squares, num_points):
    """Return the standard deviation given the sum of the samples, the
    sum of the squares of the samples, and the number of samples."""
    sq_sum = sum_points * sum_points
    sq_num = num_points * num_points
    return(sqrt(sum_squares / num_points - 2 * sq_sum / sq_num \
                + sq_sum / sq_num))


def plot_display(filename):
    """Plot the data in filename."""

    plot_instructions = """
set xdata time
set timefmt "%Y-%m-%d"
set format x "%m-%Y"
set terminal png size 1360,717    # my laptop screen size (was x718)
set output '| display png:-'
set multiplot
set origin 0,.2
set size 1,.8"""
    plot_instructions += """
plot "%s" using 2:3 title "Measurements" lt -1, \\
     "%s" using 2:4 title "Convolution, 20 day triangle" with lines lt 4, \\
     "%s" using 2:5 title "Convolution plus std dev" with lines lt 1, \\
     "%s" using 2:6 title "Convolution minus std dev" with lines lt 1
""" % tuple([filename] * 4)
    plot_instructions += """set origin 0,0
set size 1,.2
set yrange [0:]
plot "%s" using 2:7 title "Standard Deviation" with lines lt 10
unset multiplot
set size 1,1
""" % filename

    pipe_fd = subprocess.Popen(['gnuplot'], stdin=subprocess.PIPE)
    pipe_fd.communicate(plot_instructions)
    pipe_fd.wait()


# ############################################################
# Admin and options

def copyright_short():
    """Print copyright."""

    print "Time Series Data (tsd), copyright 2011, by Jeff Abrahamson."
    print "Version ", G_VERSION
    return


def copyright_long():
    """Print copyright and GPL info."""

    print """Time Series Data (tsd)
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
    return


def usage(verbose):
    """Print a usage message."""

    if(verbose):
        copyright_long()
    else:
        copyright_short()
    print
    print """tsd -VhL
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
    plot    plots the named time series

    Examples:
            $ tsd temp init          # Create the time series calle temp
            $ tsd temp 22.3          # It is 22.3 degrees today
            $ tsd temp               # will print today's date and temperature
            $ tsd plot               # will plot the temperature history
""" % '|'.join(list_commands())


    return


def get_opts():
    """Get options."""

    options = {}
    options['verbose'] = False
    options['args'] = []
    options['date'] = datetime.date.today()
    options['diff'] = False        # only meaningful for init
    options['list'] = False
    options['commands'] = False

    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "hvVd:DLC")
    except getopt.GetoptError:
        usage(False)
        sys.exit(1)

    for option_flag, option_arg in opts:
        if option_flag == '-h':
            usage(options['verbose'])
            sys.exit(0)
        if option_flag == '-v':
            options.verbose = True
        if option_flag == '-V':
            copyright_short()
            sys.exit(0)
        if option_flag == '-L':
            options.list = True
        if option_flag == '-C':
            options.commands = True
        if option_flag == '-d':
            if option_arg[0] == '-':
                delta = datetime.timedelta(int(option_arg))
                options.date = datetime.date.today() + delta
            else:
                options.date = dateutil.parser.parse(option_arg).date()
        if option_flag == '-D':
            options.diff = True

    if args:
        options.args = args

    if options['list']:
        list_series(options['verbose'])
        sys.exit(0)
    if options['commands']:
        print '\n'.join(list_commands())
        sys.exit(0)
    return options


def get_config():
    """Get config file .tsdrc (as dict).

    Local config overrides HOME config.
    Finding a config file is not mandatory.
    Set global dict G_CONFIG.
    """
    config_name = '.tsdrc'
    # Startwith default values
    config = {
        'series_dir' : os.getenv('HOME')  + '/tsd/',
        'testing' : 0,
    }
    config.update(_get_config(os.getenv('HOME') + '/' + config_name))
    config.update(_get_config(config_name))
    # Cast what we can
    config['testing'] = bool(config['testing'])
    global G_CONFIG
    G_CONFIG = config


def _get_config(filename):
    """Get config file by name.

    Strip lines of form ^#.*$.
    Understand lines of form name=value.
    Return the dictionary of (name, value) pairs.
    Otherwise not very sophisticated.
    """
    config = {}
    raw_lines = _get_config_raw(filename).splitlines()
    lines = [line for line in raw_lines if line[0] != '#']
    for line in lines:
        [key, val] = line.split('=')
        config[key] = val
    return config


def _get_config_raw(config_name):
    """Return the config as a block of text.

    Includes embedded comments.
    """
    try:
        with open(config_name, 'r') as config_fp:
            text = config_fp.read()
        return text
    except IOError:
        return ''


# ############################################################
# Main


def main():
    """Look at input from user, decide what to do, do it."""

    get_config()
    options = get_opts()

    if 0 == len(options['args']):
        print 'Missing time series name.'
        print
        usage(options['verbose'])
        sys.exit(1)

    series = options['args'][0]
    if 1 == len(options['args']):
        recent_data(series, options['verbose'])
        return

    command = options['args'][1]
    if 'config' == command:
        show_series_config(series, options['verbose'])
        return

    if 'edit' == command:
        edit_series_config(series, options['verbose'])
        return

    if 'init' == command:
        create_series(series, options['diff'], options['verbose'])
        return

    if 'plot' == command:
        plot_series(series, options['verbose'])
        return

    # Else add a value
    value = float(command)
    add_point(series, options['date'], value, verbose=options['verbose'])
    return


if __name__ == "__main__":
    main()
