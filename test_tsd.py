#!/usr/bin/python3

"""Unit test functions in tsd.py."""

import os
import tsd
import unittest


class TestTSD(unittest.TestCase):
    """Test functions for tsd.py."""

    def setUp(self):
        """What we need to run tests."""
        tsd.get_config()
        try:
            os.mkdir("./test_data/tmp")
        except OSError as err:
            # Error 17 means directory exists, that's fine
            if 17 != err.errno:
                raise

    def tearDown(self):
        """Clean up after ourselves."""

        def rmrf():
            """The equivalent of 'rm -rf ./test_data/tmp'."""
            top_dir = "./test_data/tmp"
            for root, dirs, files in os.walk(top_dir, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(top_dir)

        rmrf()

    def test_local_config(self):
        """Test that ./.tsdrc exists and is correct."""
        tsd.get_config()
        config = tsd.G_CONFIG
        self.assertEqual(config["series_dir"], "./test_data/")
        self.assertEqual(config["testing"], True)

    def test_recent_data(self):
        """Test recent_data()."""
        lines = tsd.recent_data("test-short", False)
        short_expected = ["2011-01-03	4", "2011-01-05	8"]
        self.assertEqual(lines, short_expected)

        lines = tsd.recent_data("test-short", True)
        short_expected_verbose = ["2011-01-01	2", "2011-01-03	4", "2011-01-05	8"]
        self.assertEqual(lines, short_expected_verbose)

    def test_add_point(self):
        """Test add_point()."""
        sname = "tmp/add-points"
        tsd.create_series(sname, False, False)
        lines = tsd.recent_data(sname, True)
        self.assertEqual([], lines)
        tsd.add_point(sname, "2013-04-01", 3.1415)
        lines = tsd.recent_data(sname, True)
        self.assertEqual(["2013-04-01\t3.1415"], lines)

    def test_show_series_config(self):
        """Test show_series_config()."""
        sname = "tmp/for_its_config"
        # Create a diff series, which has a config
        tsd.create_series(sname, True, False)
        config_lines = tsd.show_series_config(sname)
        expected = "diff_type=1\nconvolve_width=20\n"
        self.assertEqual(expected, config_lines)
        #### Needs a test to exercise verbose=True/False

    def test_edit_series_config(self):
        """Test edit_series_config()."""
        #### Needs to be tested
        pass

    def test_list_series(self):
        """Test list_series()."""
        series = tsd.list_series()
        expected = set(["test-bulge", "test-flat", "test-short", "test-square", "tmp"])
        self.assertEqual(expected, set(series.keys()))

        series = tsd.list_series(verbose=True)
        expected = set(["test-bulge", "test-flat", "test-short", "test-square", "tmp"])
        self.assertEqual(expected, set(series.keys()))
        values = series.values()
        values = sorted(values)
        self.assertEqual([False, False, False, False, True], values)
        self.assertEqual(series["test-square"], True)

    def test_list_commands(self):
        """Test list_commands()."""

        commands = tsd.list_commands()
        self.assertEqual(["config", "edit", "init", "plot"], commands)

    def test_series_dir_name(self):
        """Test series_dir_name()."""
        dir_name = tsd.series_dir_name()
        self.assertEqual(dir_name, tsd.G_CONFIG["series_dir"])
        self.assertTrue(os.path.exists(dir_name))

    def test_series_name(self):
        """Test series_name()."""
        name = tsd.series_name("test-bulge", False)
        self.assertTrue(os.path.exists(name))
        self.assertEqual(name, "./test_data/test-bulge")
        pass

    def test_series_config_name(self):
        """Test series_config_name()."""
        pass

    def test_series_config(self):
        """Test series_config()."""
        pass

    def test_series_config_raw(self):
        """Test series_config_raw()."""
        pass

    def test_plot_series(self):
        """Test plot_series()."""
        pass

    def test_plot_get_points(self):
        """Test plot_get_points()."""
        pass

    def test_plot_discrete_derivative(self):
        """Test plot_discrete_derivative()."""
        pass

    def test_plot_put_points(self):
        """Test plot_put_points()."""
        pass

    def test_plot_convolve(self):
        """Test test_plot_convolve()."""
        pass

    def test_plot_convolve_from(self):
        """Test plot_convolve_from()."""
        pass

    def test_plot_standard_deviation(self):
        """Test plot_standard_deviation()."""
        pass

    def test_plot_standard_dev_sub(self):
        """Test plot_standard_deviation_sub()."""
        pass

    def test_plot_display(self):
        """Test plot_display()."""
        pass

    def test_copyright_short(self):
        """Test copyright_short()."""
        pass

    def test_copyright_long(self):
        """Test copyright_long()."""
        pass

    def test_usage(self):
        """Test usage()."""
        pass

    def test_get_opts(self):
        """Test get_opts()."""
        pass

    def test_create_series(self):
        """Test create_series()."""
        tsd.create_series("tmp/non-diff", False, False)
        expected_sname = "./test_data/tmp/non-diff"
        try:
            stat = os.stat(expected_sname)
            self.assertEqual(stat.st_size, 0)
        except OSError as err:
            print("{0}:  Create series error: {1}".format(expected_sname, err))
            self.assertEqual("", err)

        tsd.create_series("tmp/diff", True, False)
        expected_diff_sname = "./test_data/tmp/diff"
        try:
            stat = os.stat(expected_diff_sname)
            self.assertEqual(stat.st_size, 0)
        except OSError as err:
            print(
                "{0}:  Create diff series error: {1}".format(expected_diff_sname, err)
            )
            self.assertEqual("", err)
        try:
            stat = os.stat(expected_diff_sname + ".cfg")
            self.assertEqual(stat.st_size, 30)
        except OSError as err:
            print(
                "{0}:  Create diff series config error: {1}".format(
                    expected_diff_sname + ".cfg", err
                )
            )
            self.assertEqual("", err)


if __name__ == "__main__":
    unittest.main()
