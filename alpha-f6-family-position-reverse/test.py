from __future__ import annotations

import builtins
import importlib
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


@contextmanager
def import_backtest_without_scipy():
    sys.modules.pop("backtest", None)
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "scipy" or name.startswith("scipy."):
            raise ImportError("scipy blocked by offline test")
        return original_import(name, *args, **kwargs)

    builtins.__import__ = blocked_import
    try:
        yield importlib.import_module("backtest")
    finally:
        builtins.__import__ = original_import
        sys.modules.pop("backtest", None)


class F6CrossSectionOfflineTests(unittest.TestCase):
    def sample_positions(self) -> pd.DataFrame:
        rows = []
        for date in ["20260102", "20260103"]:
            rows.extend(
                [
                    [date, "A", "东方财富", -80.0],
                    [date, "A", "永安期货", 40.0],
                    [date, "A", "中信期货", 20.0],
                    [date, "A", "其他席位", 60.0],
                    [date, "B", "东方财富", 80.0],
                    [date, "B", "永安期货", -40.0],
                    [date, "B", "中信期货", -20.0],
                    [date, "B", "其他席位", -60.0],
                    [date, "C", "东方财富", 0.0],
                    [date, "C", "永安期货", 20.0],
                    [date, "C", "中信期货", -20.0],
                    [date, "C", "其他席位", 40.0],
                ]
            )
        return pd.DataFrame(rows, columns=["date", "underlying_symbol", "broker", "net_margin"])

    def sample_dominant_and_daily(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        dominant = pd.DataFrame(
            [
                ["20260102", "A", "A2601"],
                ["20260103", "A", "A2601"],
                ["20260104", "A", "A2601"],
                ["20260102", "B", "B2601"],
                ["20260103", "B", "B2601"],
                ["20260104", "B", "B2601"],
                ["20260102", "C", "C2601"],
                ["20260103", "C", "C2601"],
                ["20260104", "C", "C2601"],
            ],
            columns=["date", "underlying_symbol", "symbol"],
        )
        daily = pd.DataFrame(
            [
                ["20260102", "A2601", 100.0],
                ["20260103", "A2601", 102.0],
                ["20260104", "A2601", 103.0],
                ["20260102", "B2601", 100.0],
                ["20260103", "B2601", 99.0],
                ["20260104", "B2601", 98.0],
                ["20260102", "C2601", 100.0],
                ["20260103", "C2601", 100.5],
                ["20260104", "C2601", 101.0],
            ],
            columns=["date", "symbol", "close"],
        )
        return dominant, daily

    def test_factor_is_f6_cross_section_position_reverse(self) -> None:
        factor = importlib.import_module("factor")
        result = factor.calculate_factor(self.sample_positions(), update_time="test")

        self.assertEqual(set(result["factor_id"]), {"F6"})
        self.assertEqual(set(result["factor_name"]), {"家人仓位反向"})
        self.assertEqual(set(result["signal"]).issubset({"buy", "sell", "hold"}), True)

        day = result[result["trade_date"] == "2026-01-02"].set_index("symbol")
        self.assertGreater(day.at["A", "factor_value"], day.at["C", "factor_value"])
        self.assertGreater(day.at["C", "factor_value"], day.at["B", "factor_value"])
        self.assertEqual(day.at["A", "signal"], "buy")
        self.assertEqual(day.at["B", "signal"], "sell")

    def test_truncating_future_rows_does_not_change_history(self) -> None:
        factor = importlib.import_module("factor")
        base = self.sample_positions()
        future = base.copy()
        future["date"] = "20260104"
        future["net_margin"] = future["net_margin"] * -9
        full = factor.calculate_factor(pd.concat([base, future], ignore_index=True), update_time="test")
        short = factor.calculate_factor(base, update_time="test")

        merged = full[full["trade_date"] < "2026-01-04"].merge(
            short,
            on=["trade_date", "symbol"],
            suffixes=("_full", "_short"),
        )
        diff = (merged["factor_value_full"] - merged["factor_value_short"]).abs()
        self.assertTrue((diff <= 1e-12).all())

    def test_backtest_import_does_not_require_scipy_and_has_tradeable_results(self) -> None:
        with import_backtest_without_scipy() as backtest:
            factor = importlib.import_module("factor")
            factor_df = factor.calculate_factor(self.sample_positions(), update_time="test")
            dominant, daily = self.sample_dominant_and_daily()
            result = backtest.compute_backtest_results(
                factor_df,
                dominant,
                daily,
                bootstrap_samples=100,
                bootstrap_seed=3,
            )

        self.assertIn("research", result)
        self.assertIn("tradeable", result)
        self.assertIn("bootstrap_ic", result)
        self.assertIn("holding_period_ic", result)
        self.assertEqual(result["bootstrap_ic"]["bootstrap_samples"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
