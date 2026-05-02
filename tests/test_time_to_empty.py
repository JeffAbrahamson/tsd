"""Tests for :mod:`tsd.time_to_empty`."""

from __future__ import annotations

import os
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "src" / "tsd" / "time_to_empty.py"
sys.path.insert(0, str(REPO_ROOT / "src"))

SPEC = importlib.util.spec_from_file_location("tsd.time_to_empty", MODULE_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

read_data = mod.read_data
compute_time_axis = mod.compute_time_axis
initial_rate_guess = mod.initial_rate_guess
kalman_filter_random_walk_rate = mod.kalman_filter_random_walk_rate
simulate_hitting_time = mod.simulate_hitting_time
ascii_histogram = mod.ascii_histogram

SAMPLE_DATA = """\
2025-03-01   120
2025-03-09   112
2025-03-15   100
2025-03-30   98
2025-04-10   98
2025-04-22   90
"""


def write_temp(content: str) -> str:
    """Write *content* to a temporary file and return its path."""

    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def cli_env(extra: dict | None = None) -> dict:
    """Return a subprocess environment that can import from ``src``."""

    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = (
        src_path if not existing else src_path + os.pathsep + existing
    )
    if extra:
        env.update(extra)
    return env


def run_script(*args, data: str = SAMPLE_DATA) -> subprocess.CompletedProcess:
    """Run the module against a temp data file; return the result."""

    path = write_temp(data)
    try:
        return subprocess.run(
            [sys.executable, "-m", "tsd.time_to_empty", "-f", path, *args],
            capture_output=True,
            text=True,
            env=cli_env(),
        )
    finally:
        os.unlink(path)


class TestReadData(unittest.TestCase):
    """Tests for ``read_data``."""

    def _read(self, content, **kwargs):
        path = write_temp(content)
        try:
            return read_data(path, **kwargs)
        finally:
            os.unlink(path)

    def test_basic_parsing(self):
        rows = self._read(SAMPLE_DATA, drop_same_day_duplicates=True)
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0], (date(2025, 3, 1), 120.0))
        self.assertEqual(rows[-1], (date(2025, 4, 22), 90.0))

    def test_sorts_by_date(self):
        content = "2025-03-15 100\n2025-03-01 120\n2025-03-09 112\n"
        rows = self._read(content, drop_same_day_duplicates=False)
        dates = [day for day, _ in rows]
        self.assertEqual(dates, sorted(dates))

    def test_skips_blank_and_comment_lines(self):
        content = "\n# header\n2025-03-01 120\n\n2025-03-09 112\n"
        rows = self._read(content, drop_same_day_duplicates=False)
        self.assertEqual(len(rows), 2)

    def test_skips_malformed_rows(self):
        content = "03/01/2025 120\n2025-03-01 x\n2025-03-09 112\n"
        rows = self._read(content, drop_same_day_duplicates=False)
        self.assertEqual(rows, [(date(2025, 3, 9), 112.0)])

    def test_dedup_keeps_last_reading_per_day(self):
        content = "2025-03-01 120\n2025-03-01 115\n2025-03-01 110\n"
        rows = self._read(content, drop_same_day_duplicates=True)
        self.assertEqual(rows, [(date(2025, 3, 1), 110.0)])

    def test_keep_same_day_retains_all_readings(self):
        content = "2025-03-01 120\n2025-03-01 115\n"
        rows = self._read(content, drop_same_day_duplicates=False)
        self.assertEqual(len(rows), 2)

    def test_float_quantity_is_rounded(self):
        content = "2025-03-01 36.6\n2025-03-09 37.0\n"
        rows = self._read(content, drop_same_day_duplicates=False)
        self.assertEqual(rows[0][1], 37.0)
        self.assertEqual(rows[1][1], 37.0)

    def test_exits_on_empty_file(self):
        path = write_temp("")
        try:
            with self.assertRaises(SystemExit):
                read_data(path, drop_same_day_duplicates=True)
        finally:
            os.unlink(path)


class TestComputeTimeAxis(unittest.TestCase):
    """Tests for ``compute_time_axis``."""

    ROWS = [
        (date(2025, 3, 1), 120.0),
        (date(2025, 3, 11), 110.0),
        (date(2025, 3, 21), 100.0),
    ]

    def test_first_time_is_zero(self):
        t, _ = compute_time_axis(self.ROWS)
        self.assertEqual(t[0], 0.0)

    def test_correct_day_intervals(self):
        t, _ = compute_time_axis(self.ROWS)
        np.testing.assert_array_equal(t, [0.0, 10.0, 20.0])

    def test_correct_quantities(self):
        _, q = compute_time_axis(self.ROWS)
        np.testing.assert_array_equal(q, [120.0, 110.0, 100.0])


class TestInitialRateGuess(unittest.TestCase):
    """Tests for ``initial_rate_guess``."""

    def _guess(self, days, vals):
        return initial_rate_guess(
            np.array(days, dtype=float),
            np.array(vals, dtype=float),
        )

    def test_simple_one_interval(self):
        self.assertAlmostEqual(self._guess([0, 10], [100, 90]), 1.0)

    def test_median_of_multiple_rates(self):
        self.assertAlmostEqual(
            self._guess([0, 10, 15, 25], [100, 90, 80, 70]), 1.0
        )

    def test_ignores_zero_or_negative_change(self):
        self.assertAlmostEqual(self._guess([0, 5, 10], [100, 100, 90]), 2.0)
        self.assertAlmostEqual(self._guess([0, 5, 10], [100, 110, 90]), 4.0)

    def test_fallback_when_no_positive_rates(self):
        self.assertEqual(self._guess([0, 5, 10], [80, 90, 100]), 1e-6)

    def test_fallback_on_duplicate_timestamps(self):
        self.assertEqual(self._guess([0, 0, 0], [100, 90, 80]), 1e-6)


class TestKalmanFilter(unittest.TestCase):
    """Tests for ``kalman_filter_random_walk_rate``."""

    def _kf(self, days, vals, **kwargs):
        defaults = dict(sigma_r=0.5, sigma_q=0.25, sigma_z=0.5)
        defaults.update(kwargs)
        return kalman_filter_random_walk_rate(
            np.array(days, dtype=float),
            np.array(vals, dtype=float),
            **defaults,
        )

    def test_single_observation_returns_prior(self):
        state, covariance = self._kf([0], [50])
        self.assertAlmostEqual(state[0], 50.0)
        self.assertGreaterEqual(state[1], 0.0)
        self.assertEqual(covariance.shape, (2, 2))

    def test_rate_always_non_negative(self):
        state, _ = self._kf(range(10), [50 + 2 * k for k in range(10)])
        self.assertGreaterEqual(state[1], 0.0)

    def test_linear_signal_recovers_rate(self):
        days = list(range(21))
        values = [100.0 - k for k in days]
        state, _ = self._kf(
            days, values, sigma_r=0.01, sigma_q=0.01, sigma_z=0.1
        )
        self.assertAlmostEqual(state[1], 1.0, delta=0.1)

    def test_covariance_is_symmetric_and_psd(self):
        _, covariance = self._kf([0, 5, 10, 15], [100, 96, 91, 87])
        np.testing.assert_allclose(covariance, covariance.T, atol=1e-10)
        eigenvalues = np.linalg.eigvalsh(covariance)
        self.assertTrue(np.all(eigenvalues >= -1e-10))


class TestSimulateHittingTime(unittest.TestCase):
    """Tests for ``simulate_hitting_time``."""

    def _sim(
        self,
        q0,
        r0,
        *,
        nsims=300,
        sigma_r=0.0,
        sigma_q=0.0,
        dt=1.0,
        max_days=100.0,
        allow_neg=False,
        min_rate=0.0,
        seed=42,
    ):
        covariance = np.diag([1e-10, 1e-10])
        return simulate_hitting_time(
            x_mean=np.array([q0, r0]),
            P=covariance,
            nsims=nsims,
            sigma_r=sigma_r,
            sigma_q=sigma_q,
            dt_forward=dt,
            max_days=max_days,
            rng=np.random.default_rng(seed),
            allow_negative_rate=allow_neg,
            min_rate=min_rate,
        )

    def test_output_shape(self):
        hits = self._sim(10.0, 1.0, nsims=500)
        self.assertEqual(hits.shape, (500,))

    def test_high_rate_all_hit_first_step(self):
        hits = self._sim(10.0, 20.0, dt=1.0, max_days=5.0)
        np.testing.assert_array_equal(hits, 1.0)

    def test_zero_rate_no_noise_all_censored(self):
        hits = self._sim(1000.0, 0.0, max_days=50.0)
        self.assertTrue(np.all(~np.isfinite(hits)))

    def test_hitting_time_close_to_expected(self):
        hits = self._sim(20.0, 1.0, nsims=1000, max_days=60.0)
        finite = hits[np.isfinite(hits)]
        self.assertGreater(len(finite), 900)
        self.assertAlmostEqual(float(np.median(finite)), 20.0, delta=3.0)

    def test_seed_produces_identical_results(self):
        covariance = np.diag([0.5, 0.1])
        kwargs = dict(
            x_mean=np.array([50.0, 2.0]),
            P=covariance,
            nsims=200,
            sigma_r=0.1,
            sigma_q=0.05,
            dt_forward=1.0,
            max_days=100.0,
            allow_negative_rate=False,
            min_rate=0.0,
        )
        hits1 = simulate_hitting_time(**kwargs, rng=np.random.default_rng(7))
        hits2 = simulate_hitting_time(**kwargs, rng=np.random.default_rng(7))
        np.testing.assert_array_equal(hits1, hits2)

    def test_non_psd_covariance_handled(self):
        covariance = np.array([[1.0, 1.0], [1.0, 1.0]])
        hits = simulate_hitting_time(
            x_mean=np.array([10.0, 1.0]),
            P=covariance,
            nsims=50,
            sigma_r=0.1,
            sigma_q=0.1,
            dt_forward=1.0,
            max_days=50.0,
            rng=np.random.default_rng(0),
            allow_negative_rate=False,
            min_rate=0.0,
        )
        self.assertEqual(hits.shape, (50,))


class TestAsciiHistogram(unittest.TestCase):
    """Tests for ``ascii_histogram``."""

    def test_all_inf_returns_message(self):
        result = ascii_histogram(np.array([np.inf, np.inf]), bins=5)
        self.assertIn("no depletion", result)

    def test_line_count_equals_bins(self):
        data = np.linspace(1.0, 100.0, 200)
        lines = ascii_histogram(data, bins=10).strip().split("\n")
        self.assertEqual(len(lines), 10)

    def test_tallest_bin_has_full_width_bar(self):
        result = ascii_histogram(np.full(100, 42.0), bins=1, width=15)
        self.assertIn("█" * 15, result)

    def test_auto_size_omits_empty_leading_region(self):
        data = np.linspace(50.0, 100.0, 100)
        auto = (
            ascii_histogram(data, bins=5, auto_size=True).strip().split("\n")
        )
        default = ascii_histogram(data, bins=5).strip().split("\n")
        self.assertIn("█", auto[0])
        self.assertNotIn("█", default[0])

    def test_non_fractional_has_integer_edges(self):
        data = np.linspace(1.0, 100.0, 200)
        result = ascii_histogram(data, bins=10, fractional=False)
        for line in result.strip().split("\n"):
            edge_part = line.split(" d |")[0]
            self.assertNotIn(".", edge_part)


class TestIntegration(unittest.TestCase):
    """Integration tests for the module CLI."""

    ZERO_DATA = """\
2025-03-01   120
2025-03-09     0
2025-03-15     0
"""

    ZERO_LAST_DATA = """\
2025-03-01   120
2025-03-09   112
2025-03-15     0
"""

    def _run_multi(
        self, files_data: dict, *args, env_overrides: dict | None = None
    ) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, data in files_data.items():
                with open(
                    os.path.join(tmpdir, name), "w", encoding="utf-8"
                ) as fh:
                    fh.write(data)
            env = cli_env({"TSD_DIR": tmpdir})
            if env_overrides:
                env.update(env_overrides)
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tsd.time_to_empty",
                    *files_data.keys(),
                    *args,
                ],
                capture_output=True,
                text=True,
                env=env,
            )

    def test_normal_run_exits_zero(self):
        result = run_script("--seed", "42", "--nsims", "500")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_output_contains_expected_sections(self):
        result = run_script("--seed", "42", "--nsims", "500")
        self.assertIn("Time-to-Empty Forecast", result.stdout)
        self.assertIn("Readings: 6", result.stdout)
        self.assertIn("Quantiles:", result.stdout)
        self.assertIn("Histogram", result.stdout)
        self.assertIn("Summary:", result.stdout)

    def test_seed_makes_output_reproducible(self):
        result1 = run_script("--seed", "99", "--nsims", "500")
        result2 = run_script("--seed", "99", "--nsims", "500")
        self.assertEqual(result1.stdout, result2.stdout)

    def test_missing_file_exits_nonzero(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tsd.time_to_empty",
                "-f",
                "/nonexistent/__no_such_file__.txt",
            ],
            capture_output=True,
            text=True,
            env=cli_env(),
        )
        self.assertNotEqual(result.returncode, 0)

    def test_invalid_quantiles_exit_nonzero(self):
        self.assertNotEqual(
            run_script("--quantiles", "not,numbers").returncode, 0
        )
        self.assertNotEqual(
            run_script("--quantiles", "0.0,0.5,1.0").returncode, 0
        )

    def test_keep_same_day_retains_duplicates(self):
        data = "2025-03-01 120\n2025-03-01 110\n2025-03-09 100\n"
        result = run_script("--seed", "42", "--nsims", "500", data=data)
        self.assertIn("Readings: 2", result.stdout)
        result = run_script(
            "--seed",
            "42",
            "--nsims",
            "500",
            "--keep-same-day",
            data=data,
        )
        self.assertIn("Readings: 3", result.stdout)

    def test_multi_file_exits_zero(self):
        result = self._run_multi(
            {"alpha": SAMPLE_DATA, "beta": SAMPLE_DATA},
            "--seed",
            "42",
            "--nsims",
            "500",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_multi_file_summary_present(self):
        result = self._run_multi(
            {"alpha": SAMPLE_DATA},
            "--seed",
            "42",
            "--nsims",
            "500",
        )
        self.assertIn("── alpha", result.stdout)
        self.assertIn("Summary", result.stdout)
        self.assertNotIn("Time-to-Empty Forecast", result.stdout)

    def test_multi_file_summary_sorted_descending(self):
        fast = "2025-03-01 120\n2025-03-07 100\n2025-03-13 80\n"
        slow = "2025-03-01 120\n2025-03-07 119\n2025-03-13 118\n"
        result = self._run_multi(
            {"fast": fast, "slow": slow},
            "--seed",
            "42",
            "--nsims",
            "2000",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        summary_start = result.stdout.index("Summary")
        slow_pos = result.stdout.index("slow", summary_start)
        fast_pos = result.stdout.index("fast", summary_start)
        self.assertLess(slow_pos, fast_pos)

    def test_multi_file_without_tsd_dir_uses_default_config_path(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            env = cli_env({"HOME": tmp_home})
            env.pop("TSD_DIR", None)
            result = subprocess.run(
                [sys.executable, "-m", "tsd.time_to_empty", "somefile"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no series matching", result.stdout + result.stderr)

    def test_already_empty_single_file_message(self):
        result = run_script(
            "--seed", "42", "--nsims", "500", data=self.ZERO_DATA
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Already empty", result.stdout)
        self.assertNotIn("Histogram", result.stdout)

    def test_already_empty_single_zero_last_reading(self):
        result = run_script(
            "--seed", "42", "--nsims", "500", data=self.ZERO_LAST_DATA
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Already empty", result.stdout)

    def test_already_empty_multi_file_sorted_last(self):
        result = self._run_multi(
            {"zero": self.ZERO_DATA, "normal": SAMPLE_DATA},
            "--seed",
            "42",
            "--nsims",
            "500",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        summary_start = result.stdout.index("Summary")
        normal_pos = result.stdout.index("normal", summary_start)
        zero_pos = result.stdout.index("zero", summary_start)
        self.assertLess(normal_pos, zero_pos)
        self.assertIn("empty", result.stdout[summary_start:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
