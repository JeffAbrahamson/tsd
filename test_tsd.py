#!/usr/bin/python

"""Unit test functions in tsd.py."""


import tsd
import unittest


class TestTSD(unittest.TestCase):

    def test_recent_data(self):
        """Test recent_data().

        """
        lines = tsd.recent_data('test-short', False, testing=True)
        short_expected = ['2011-01-03	4', '2011-01-05	8']
        self.assertEqual(lines, short_expected)

        lines = tsd.recent_data('test-short', True, testing=True)
        short_expected_verbose = ['2011-01-01	2', '2011-01-03	4', '2011-01-05	8']
        self.assertEqual(lines, short_expected)
        

    def test_create_series(self):
        """Test create_series()."""
        pass

    def test_add_point(self):
        """Test add_point()."""
        pass

    def test_show_series_config(self):
        """Test show_series_config()."""
        pass

    def test_edit_series_config(self):
        """Test edit_series_config()."""
        pass

    def test_list_series(self):
        """Test list_series()."""
        pass

    def test_list_commands(self):
        """Test list_commands()."""

        L = tsd.list_commands()

        pass

    def test_series_dir_name(self):
        """Test series_dir_name()."""
        pass

    def test_series_name(self):
        """Test series_name()."""
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

    def test_plot_standard_deviation_sub(self):
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


if __name__ == '__main__':
    unittest.main()
