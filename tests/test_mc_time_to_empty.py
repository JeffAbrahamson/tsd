"""Tests for :mod:`tsd.mc_time_to_empty`."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from tsd.mc_time_to_empty import (
    HistoricalRates,
    build_historical_rates,
    gaussian_recency_weight,
    simulate_hitting_time,
)

SAMPLE_DATA = """\
2026-05-01 1000
2026-05-16 500
2026-05-21 500
2026-05-26 0
2026-05-27 1000
2026-05-30 700
"""

SAMPLE_ROWS = [
    (date(2026, 5, 1), 1000.0),
    (date(2026, 5, 16), 500.0),
    (date(2026, 5, 21), 500.0),
    (date(2026, 5, 26), 0.0),
    (date(2026, 5, 27), 1000.0),
    (date(2026, 5, 30), 700.0),
]


def write_temp(content: str) -> str:
    """Write *content* to a temporary file and return its path."""

    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as file_handle:
        file_handle.write(content)
    return path


def run_script(*args, data: str = SAMPLE_DATA) -> subprocess.CompletedProcess:
    """Run the empirical forecast module against temporary data."""

    path = write_temp(data)
    env = dict(os.environ)
    source_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = source_path
    try:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "tsd.mc_time_to_empty",
                "-f",
                path,
                *args,
            ],
            capture_output=True,
            text=True,
            env=env,
        )
    finally:
        os.unlink(path)


class TestGaussianRecencyWeight(unittest.TestCase):
    """Tests for Gaussian present-time weighting."""

    def test_has_baseline_plus_gaussian_shape(self):
        weights = gaussian_recency_weight(
            np.array([0.0, 60.0, 120.0]),
            sigma_days=60.0,
            amplitude=1.0,
        )
        np.testing.assert_allclose(
            weights,
            [
                2.0,
                1.0 + np.exp(-0.5),
                1.0 + np.exp(-2.0),
            ],
        )

    def test_zero_amplitude_gives_uniform_weights(self):
        weights = gaussian_recency_weight(
            np.array([0.0, 60.0, 600.0]),
            sigma_days=60.0,
            amplitude=0.0,
        )
        np.testing.assert_array_equal(weights, np.ones(3))


class TestBuildHistoricalRates(unittest.TestCase):
    """Tests for reconstructing the empirical daily rate population."""

    def test_expands_intervals_by_elapsed_days(self):
        history = build_historical_rates(
            SAMPLE_ROWS, recency_sigma=60.0, recency_amplitude=0.0
        )
        self.assertEqual(len(history.rates), 28)
        np.testing.assert_allclose(history.rates[:15], 500.0 / 15.0)
        np.testing.assert_array_equal(history.rates[15:20], 0.0)
        np.testing.assert_array_equal(history.rates[20:25], 100.0)
        np.testing.assert_array_equal(history.rates[25:], 100.0)

    def test_excludes_refill_intervals(self):
        history = build_historical_rates(
            SAMPLE_ROWS, recency_sigma=60.0, recency_amplitude=0.0
        )
        self.assertEqual(history.excluded_refill_intervals, 1)
        self.assertEqual(len(history.rates), 28)

    def test_days_have_uniform_weights_when_amplitude_is_zero(self):
        history = build_historical_rates(
            SAMPLE_ROWS, recency_sigma=60.0, recency_amplitude=0.0
        )
        np.testing.assert_allclose(history.weights, np.full(28, 1.0 / 28.0))

    def test_default_recency_favors_recent_days(self):
        history = build_historical_rates(
            SAMPLE_ROWS, recency_sigma=60.0, recency_amplitude=1.0
        )
        self.assertGreater(history.weights[-1], history.weights[0])

    def test_returns_empty_history_without_usable_intervals(self):
        rows = [
            (date(2026, 5, 1), 100.0),
            (date(2026, 5, 2), 200.0),
        ]
        history = build_historical_rates(
            rows, recency_sigma=60.0, recency_amplitude=1.0
        )
        self.assertEqual(len(history.rates), 0)
        self.assertEqual(history.excluded_refill_intervals, 1)


class TestSimulateHittingTime(unittest.TestCase):
    """Tests for empirical daily-rate simulations."""

    def test_constant_history_has_deterministic_hitting_time(self):
        history = HistoricalRates(
            rates=np.array([10.0]),
            weights=np.array([1.0]),
            excluded_refill_intervals=0,
        )
        hits = simulate_hitting_time(
            50.0, history, 500, 20, np.random.default_rng(1)
        )
        np.testing.assert_array_equal(hits, 5.0)

    def test_mixed_history_produces_a_distribution(self):
        history = HistoricalRates(
            rates=np.array([0.0, 100.0]),
            weights=np.array([0.5, 0.5]),
            excluded_refill_intervals=0,
        )
        hits = simulate_hitting_time(
            700.0, history, 5000, 100, np.random.default_rng(2)
        )
        self.assertGreater(len(np.unique(hits)), 5)
        self.assertGreater(float(np.quantile(hits, 0.9)), np.median(hits))

    def test_all_zero_history_is_censored(self):
        history = HistoricalRates(
            rates=np.array([0.0, 0.0]),
            weights=np.array([0.5, 0.5]),
            excluded_refill_intervals=0,
        )
        hits = simulate_hitting_time(
            100.0, history, 100, 30, np.random.default_rng(3)
        )
        self.assertTrue(np.all(~np.isfinite(hits)))


class TestIntegration(unittest.TestCase):
    """Integration tests for the empirical forecast CLI."""

    def _run_multi(
        self, files_data: dict, *args
    ) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as directory:
            for name, data in files_data.items():
                path = os.path.join(directory, name)
                with open(path, "w", encoding="utf-8") as file_handle:
                    file_handle.write(data)
            env = dict(os.environ)
            env["PYTHONPATH"] = str(REPO_ROOT / "src")
            env["TSD_DIR"] = directory
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tsd.mc_time_to_empty",
                    *files_data.keys(),
                    *args,
                ],
                capture_output=True,
                text=True,
                env=env,
            )

    def test_example_has_expected_history_and_spread(self):
        result = run_script(
            "--seed",
            "42",
            "--nsims",
            "5000",
            "--recency-amplitude",
            "0",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Current quantity = 700.00", result.stdout)
        self.assertIn("Historical days = 28", result.stdout)
        self.assertIn("Refill intervals excluded = 1", result.stdout)
        self.assertNotIn("10%=9 d, 25%=9 d, 50%=9 d", result.stdout)

    def test_seed_makes_output_reproducible(self):
        first = run_script("--seed", "99", "--nsims", "500")
        second = run_script("--seed", "99", "--nsims", "500")
        self.assertEqual(first.stdout, second.stdout)

    def test_default_recency_parameters_are_reported(self):
        result = run_script("--seed", "42", "--nsims", "100")
        self.assertIn(
            "Recency weighting: sigma=60.0 days  |  amplitude=1.00",
            result.stdout,
        )

    def test_invalid_recency_parameters_exit_nonzero(self):
        self.assertNotEqual(run_script("--recency-sigma", "0").returncode, 0)
        self.assertNotEqual(
            run_script("--recency-amplitude", "-1").returncode, 0
        )

    def test_multi_file_summary_is_present(self):
        result = self._run_multi(
            {"alpha": SAMPLE_DATA, "beta": SAMPLE_DATA},
            "--seed",
            "42",
            "--nsims",
            "100",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("── alpha", result.stdout)
        self.assertIn("── beta", result.stdout)
        self.assertIn("=== Summary", result.stdout)

    def test_single_empty_reading_is_already_empty(self):
        result = run_script(data="2026-05-01 0\n")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Already empty", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
