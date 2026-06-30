from __future__ import annotations

import random
import time
from datetime import timedelta

import pandas as pd

from factor import _call_with_retry, _date_to_yyyymmdd, calculate_factor, load_real_position


FACTOR_ID = "F6"
FACTOR_NAME = "家人仓位反向"
_BATCH = 5
_BATCH_SLEEP = 2.0


def _format_date(value: str) -> str:
    return pd.to_datetime(str(value), format="%Y%m%d").strftime("%Y-%m-%d")


def _batched(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def load_real_dominant_and_daily(
    underlying_symbols: list[str],
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    import panda_data

    start = _date_to_yyyymmdd(start_date)
    end_dt = pd.to_datetime(_date_to_yyyymmdd(end_date), format="%Y%m%d") + timedelta(days=10)
    end_plus = end_dt.strftime("%Y%m%d")

    dominant_chunks = []
    batches = list(_batched(underlying_symbols, _BATCH))
    for i, batch in enumerate(batches):
        print(f"  加载主力合约 batch {i + 1}/{len(batches)}: {batch}")
        chunk = _call_with_retry(
            panda_data.get_future_dominant,
            underlying_symbol=batch,
            start_date=start,
            end_date=end_plus,
        )
        if not chunk.empty:
            dominant_chunks.append(chunk)
        if i < len(batches) - 1:
            time.sleep(_BATCH_SLEEP)
    if not dominant_chunks:
        raise ValueError("Panda data 未返回主力合约数据")
    dominant = pd.concat(dominant_chunks, ignore_index=True)

    contracts = sorted(dominant["symbol"].dropna().astype(str).unique().tolist())
    daily_chunks = []
    batches = list(_batched(contracts, _BATCH))
    for i, batch in enumerate(batches):
        print(f"  加载日线数据 batch {i + 1}/{len(batches)}: {batch}")
        chunk = _call_with_retry(
            panda_data.get_future_daily,
            symbol=batch,
            start_date=start,
            end_date=end_plus,
            fields=[],
        )
        if not chunk.empty:
            daily_chunks.append(chunk)
        if i < len(batches) - 1:
            time.sleep(_BATCH_SLEEP)
    if not daily_chunks:
        raise ValueError("Panda data 未返回期货日线数据")
    daily = pd.concat(daily_chunks, ignore_index=True)
    return dominant, daily


def build_forward_returns(dominant: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    dom = dominant[["date", "underlying_symbol", "symbol"]].copy()
    dom["date"] = dom["date"].astype(str).str.replace("-", "", regex=False)
    dom["trade_date"] = dom["date"].map(_format_date)
    dom = dom.rename(columns={"underlying_symbol": "symbol", "symbol": "contract_symbol"})
    dom = dom.sort_values(["symbol", "date"]).reset_index(drop=True)
    dom["next_date"] = dom.groupby("symbol")["date"].shift(-1)

    prices = daily[["date", "symbol", "close"]].copy()
    prices["date"] = prices["date"].astype(str).str.replace("-", "", regex=False)
    prices["close"] = pd.to_numeric(prices["close"], errors="raise")

    current_price = prices.rename(columns={"symbol": "contract_symbol", "close": "close_t"})
    next_price = prices.rename(columns={"date": "next_date", "symbol": "contract_symbol", "close": "close_t1"})
    panel = dom.merge(current_price, on=["date", "contract_symbol"], how="left").merge(
        next_price,
        on=["next_date", "contract_symbol"],
        how="left",
    )
    panel = panel.dropna(subset=["close_t", "close_t1"]).copy()
    panel = panel[panel["close_t"] > 0]
    panel["forward_return"] = panel["close_t1"] / panel["close_t"] - 1
    return panel[["trade_date", "symbol", "contract_symbol", "forward_return"]].reset_index(drop=True)


def build_tradeable_forward_returns(
    dominant: pd.DataFrame,
    daily: pd.DataFrame,
    data_lag: int = 0,
    roll_cost_bps: float = 5.0,
) -> pd.DataFrame:
    base = build_forward_returns(dominant, daily)
    if base.empty:
        return base

    dom = dominant[["date", "underlying_symbol", "symbol"]].copy()
    dom["date"] = dom["date"].astype(str).str.replace("-", "", regex=False)
    dom["trade_date"] = dom["date"].map(_format_date)
    dom = dom.rename(columns={"underlying_symbol": "symbol", "symbol": "contract_symbol"})
    dom = dom.sort_values(["symbol", "trade_date"])
    dom["prev_contract"] = dom.groupby("symbol")["contract_symbol"].shift(1)
    rollover_days = dom[dom["contract_symbol"] != dom["prev_contract"]].copy()
    rollover_set = set(zip(rollover_days["trade_date"], rollover_days["symbol"]))

    roll_cost = roll_cost_bps / 10000
    result = base.copy()
    result["is_rollover"] = result.apply(lambda r: (r["trade_date"], r["symbol"]) in rollover_set, axis=1)
    result["forward_return"] = result["forward_return"] - result["is_rollover"] * roll_cost * 2

    if data_lag > 0:
        dates = sorted(result["trade_date"].unique())
        date_to_lag = {d: dates[i - data_lag] if i >= data_lag else None for i, d in enumerate(dates)}
        result["signal_date"] = result["trade_date"].map(date_to_lag)
        result = result.dropna(subset=["signal_date"])
        result = result.rename(columns={"trade_date": "execution_date", "signal_date": "trade_date"})

    return result[["trade_date", "symbol", "contract_symbol", "forward_return"]].reset_index(drop=True)


def build_multi_period_returns(
    dominant: pd.DataFrame,
    daily: pd.DataFrame,
    periods: list[int] | None = None,
) -> pd.DataFrame:
    if periods is None:
        periods = [1, 3, 5, 10, 20]

    dom = dominant[["date", "underlying_symbol", "symbol"]].copy()
    dom["date"] = dom["date"].astype(str).str.replace("-", "", regex=False)
    dom["trade_date"] = dom["date"].map(_format_date)
    dom = dom.rename(columns={"underlying_symbol": "symbol", "symbol": "contract_symbol"})
    dom = dom.sort_values(["symbol", "date"]).reset_index(drop=True)

    prices = daily[["date", "symbol", "close"]].copy()
    prices["date"] = prices["date"].astype(str).str.replace("-", "", regex=False)
    prices["close"] = pd.to_numeric(prices["close"], errors="raise")
    price_map = prices.drop_duplicates(["date", "symbol"], keep="last").set_index(["date", "symbol"])["close"]

    result = dom[["trade_date", "symbol", "date", "contract_symbol"]].copy()
    for h in periods:
        shifted = dom.copy()
        shifted["target_date"] = shifted.groupby("symbol")["date"].shift(-h)
        shifted["target_contract"] = shifted.groupby("symbol")["contract_symbol"].shift(-h)

        def _compute_return(row, _pm=price_map):
            try:
                c0 = _pm.at[(row["date"], row["contract_symbol"])]
                c1 = _pm.at[(row["target_date"], row["target_contract"])]
                if float(c0) > 0:
                    return float(c1) / float(c0) - 1
            except KeyError:
                pass
            return float("nan")

        result[f"forward_return_{h}d"] = shifted.apply(_compute_return, axis=1).values

    return result[["trade_date", "symbol"] + [f"forward_return_{h}d" for h in periods]].reset_index(drop=True)


def pearson_ic(x: pd.DataFrame) -> float:
    if x["factor_value"].std() == 0 or x["forward_return"].std() == 0:
        return float("nan")
    return float(x["factor_value"].corr(x["forward_return"]))


def rank_ic(x: pd.DataFrame) -> float:
    factor_rank = x["factor_value"].rank(method="average")
    return_rank = x["forward_return"].rank(method="average")
    if factor_rank.std() == 0 or return_rank.std() == 0:
        return float("nan")
    return float(factor_rank.corr(return_rank))


def _daily_ic_from_panel(panel: pd.DataFrame) -> pd.Series:
    return panel.groupby("trade_date").apply(pearson_ic, include_groups=False).dropna()


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = (len(ordered) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def bootstrap_ic_confidence_interval(
    factor_df: pd.DataFrame,
    returns_df: pd.DataFrame,
    n_bootstrap: int = 1000,
    confidence_level: float = 0.95,
    random_state: int = 42,
) -> dict:
    panel = factor_df[["trade_date", "symbol", "factor_value"]].merge(
        returns_df[["trade_date", "symbol", "forward_return"]],
        on=["trade_date", "symbol"],
        how="inner",
    ).dropna(subset=["factor_value", "forward_return"])
    if panel.empty:
        raise ValueError("回测样本为空：factor_df 与 returns_df 无匹配记录")

    daily_ic = _daily_ic_from_panel(panel)
    if daily_ic.empty:
        return {"IC": 0.0, "IC_95_CI_low": 0.0, "IC_95_CI_high": 0.0, "bootstrap_samples": 0}

    values = [float(v) for v in daily_ic.tolist()]
    rng = random.Random(random_state)
    boot_means = []
    for _ in range(n_bootstrap):
        sample = [values[rng.randrange(len(values))] for _ in values]
        boot_means.append(sum(sample) / len(sample))
    alpha = (1 - confidence_level) / 2
    return {
        "IC": round(float(daily_ic.mean()), 6),
        "IC_95_CI_low": round(_quantile(boot_means, alpha), 6),
        "IC_95_CI_high": round(_quantile(boot_means, 1 - alpha), 6),
        "bootstrap_samples": int(n_bootstrap),
    }


def information_ratio(returns: pd.Series) -> float:
    std = returns.std()
    if returns.empty or not std:
        return 0.0
    return float(returns.mean() / std * (252 ** 0.5))


def annualized_return(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    cumulative_return = float((1 + returns).prod() - 1)
    years = len(returns) / 252
    if years <= 0:
        return cumulative_return
    return float((1 + cumulative_return) ** (1 / years) - 1)


def count_rollovers(dominant: pd.DataFrame) -> int:
    dom = dominant[["date", "underlying_symbol", "symbol"]].copy()
    dom["date"] = dom["date"].astype(str).str.replace("-", "", regex=False)
    dom = dom.sort_values(["underlying_symbol", "date"])
    changed = dom.groupby("underlying_symbol")["symbol"].apply(lambda s: s.ne(s.shift()).sum() - 1)
    return int(changed.clip(lower=0).sum())


def _turnover(panel: pd.DataFrame) -> float:
    def side_turnover(daily_sets) -> float:
        if daily_sets.empty:
            return 0.0
        values, previous = [], None
        for current in daily_sets:
            if previous is not None:
                union = current | previous
                values.append(1 - len(current & previous) / len(union) if union else 0.0)
            previous = current
        return float(sum(values) / len(values)) if values else 0.0

    buy_sets = panel[panel["signal"] == "buy"].groupby("trade_date")["symbol"].apply(set)
    sell_sets = panel[panel["signal"] == "sell"].groupby("trade_date")["symbol"].apply(set)
    buy_to = side_turnover(buy_sets)
    sell_to = side_turnover(sell_sets)
    active_sides = (1 if buy_to > 0 else 0) + (1 if sell_to > 0 else 0)
    if active_sides == 0:
        return 0.0
    return round((buy_to + sell_to) / active_sides, 6)


def evaluate_factor(factor_df: pd.DataFrame, returns_df: pd.DataFrame) -> dict:
    panel = factor_df.merge(returns_df, on=["trade_date", "symbol"], how="inner")
    if panel.empty:
        raise ValueError("回测样本为空：factor_df 与 returns_df 无匹配记录")

    daily_ic = _daily_ic_from_panel(panel)
    daily_rank_ic = panel.groupby("trade_date").apply(rank_ic, include_groups=False).dropna()
    ic = float(daily_ic.mean()) if not daily_ic.empty else 0.0
    icir = float(daily_ic.mean() / daily_ic.std()) if len(daily_ic) > 1 and daily_ic.std() else 0.0
    rank_ic_value = float(daily_rank_ic.mean()) if not daily_rank_ic.empty else 0.0
    rank_icir = float(daily_rank_ic.mean() / daily_rank_ic.std()) if len(daily_rank_ic) > 1 and daily_rank_ic.std() else 0.0

    buy_return = panel[panel["signal"] == "buy"].groupby("trade_date")["forward_return"].mean().fillna(0)
    sell_return = panel[panel["signal"] == "sell"].groupby("trade_date")["forward_return"].mean().fillna(0)
    long_short = buy_return.subtract(sell_return, fill_value=0)
    curve = (1 + long_short).cumprod()
    drawdown = curve / curve.cummax() - 1 if not curve.empty else pd.Series(dtype=float)
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0

    return {
        "IC": round(ic, 6),
        "ICIR": round(icir, 6),
        "RankIC": round(rank_ic_value, 6),
        "RankICIR": round(rank_icir, 6),
        "ARR(%)": round(annualized_return(long_short) * 100, 6),
        "MDD(%)": round(max_drawdown * 100, 6),
        "IR": round(information_ratio(long_short), 6),
        "long_short_return": round(float(long_short.mean()), 6) if not long_short.empty else 0.0,
        "换手率": _turnover(panel),
        "样本数": int(len(panel)),
    }


def cost_sensitivity(
    factor_df: pd.DataFrame,
    returns_df: pd.DataFrame,
    cost_levels: list[int] | None = None,
) -> dict:
    if cost_levels is None:
        cost_levels = [0, 5, 15, 30]
    panel = factor_df.merge(returns_df, on=["trade_date", "symbol"], how="inner")
    if panel.empty:
        raise ValueError("回测样本为空：factor_df 与 returns_df 无匹配记录")

    buy_return = panel[panel["signal"] == "buy"].groupby("trade_date")["forward_return"].mean().fillna(0)
    sell_return = panel[panel["signal"] == "sell"].groupby("trade_date")["forward_return"].mean().fillna(0)
    long_short = buy_return.subtract(sell_return, fill_value=0)
    turnover_rate = _turnover(panel)
    result = {}
    for bps in cost_levels:
        daily_cost = turnover_rate * 2 * bps / 10000
        net_ls = long_short - daily_cost
        result[f"{bps / 100:.2f}%"] = {"avg_daily_long_short": round(float(net_ls.mean()), 8)}
    return result


def holding_period_ic(
    factor_df: pd.DataFrame,
    returns_df: pd.DataFrame,
    periods: list[int] | None = None,
) -> dict[int, dict[str, float]]:
    if periods is None:
        periods = [1, 3, 5, 10, 20]
    result = {}
    for h in periods:
        col = f"forward_return_{h}d"
        if col not in returns_df.columns:
            result[h] = {"IC": float("nan"), "ICIR": float("nan")}
            continue
        panel = factor_df[["trade_date", "symbol", "factor_value"]].merge(
            returns_df[["trade_date", "symbol", col]],
            on=["trade_date", "symbol"],
            how="inner",
        ).dropna(subset=["factor_value", col])
        if panel.empty:
            result[h] = {"IC": float("nan"), "ICIR": float("nan")}
            continue
        daily_ic = panel.groupby("trade_date").apply(
            lambda x: float(x["factor_value"].corr(x[col]))
            if x["factor_value"].std() > 0 and x[col].std() > 0
            else float("nan"),
            include_groups=False,
        ).dropna()
        ic = float(daily_ic.mean()) if not daily_ic.empty else float("nan")
        icir = float(daily_ic.mean() / daily_ic.std()) if len(daily_ic) > 1 and daily_ic.std() > 0 else float("nan")
        result[h] = {"IC": round(ic, 6), "ICIR": round(icir, 6)}
    return result


def compute_backtest_results(
    factor: pd.DataFrame,
    dominant: pd.DataFrame,
    daily: pd.DataFrame,
    data_lag: int = 0,
    roll_cost_bps: float = 5.0,
    bootstrap_samples: int = 1000,
    bootstrap_seed: int = 42,
) -> dict:
    research_forward = build_forward_returns(dominant, daily)
    tradeable_forward = build_tradeable_forward_returns(dominant, daily, data_lag=data_lag, roll_cost_bps=roll_cost_bps)
    multi_returns = build_multi_period_returns(dominant, daily)
    return {
        "research": evaluate_factor(factor, research_forward),
        "tradeable": evaluate_factor(factor, tradeable_forward),
        "bootstrap_ic": bootstrap_ic_confidence_interval(
            factor,
            research_forward,
            n_bootstrap=bootstrap_samples,
            random_state=bootstrap_seed,
        ),
        "cost_sensitivity": cost_sensitivity(factor, tradeable_forward, cost_levels=[0, 5, 15, 30]),
        "holding_period_ic": holding_period_ic(factor, multi_returns),
        "rollover_count": count_rollovers(dominant),
    }


def run_backtest() -> dict:
    positions = load_real_position()
    factor = calculate_factor(positions)
    symbols = sorted(factor["symbol"].unique().tolist())
    start_date = factor["trade_date"].min()
    end_date = factor["trade_date"].max()
    dominant, daily = load_real_dominant_and_daily(symbols, start_date, end_date)
    return compute_backtest_results(factor, dominant, daily)


if __name__ == "__main__":
    positions = load_real_position()
    factor = calculate_factor(positions)
    symbols = sorted(factor["symbol"].unique().tolist())
    start_date = factor["trade_date"].min()
    end_date = factor["trade_date"].max()
    dominant, daily = load_real_dominant_and_daily(symbols, start_date, end_date)
    results = compute_backtest_results(factor, dominant, daily)

    print("\n" + "=" * 60)
    print(f"F6 {FACTOR_NAME} 回测结果")
    print("=" * 60)
    print("\n研究口径指标:")
    for key, value in results["research"].items():
        print(f"  {key}: {value}")
    print("\n可交易口径指标:")
    print(f"  rollover_count: {results['rollover_count']}")
    for key, value in results["tradeable"].items():
        print(f"  {key}: {value}")
    print("\nBootstrap IC 95% CI:")
    for key, value in results["bootstrap_ic"].items():
        print(f"  {key}: {value}")
    print("\n成本敏感性分析:")
    for label, value in results["cost_sensitivity"].items():
        print(f"  {label}: {value}")
    print("\n持有期 IC 衰减分析:")
    for h in [1, 3, 5, 10, 20]:
        print(f"  {h:>4}D: {results['holding_period_ic'].get(h)}")
