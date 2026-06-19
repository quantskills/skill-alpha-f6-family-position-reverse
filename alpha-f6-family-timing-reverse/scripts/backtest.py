from __future__ import annotations

import pandas as pd
from scipy import stats

from factor import calculate_factor, load_inputs, compute_next_return


def _format_date(value: str) -> str:
    return pd.to_datetime(str(value), format="%Y%m%d").strftime("%Y-%m-%d")


def build_forward_returns(dominant: pd.DataFrame, daily: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    """
    回测前向收益，复用 factor.compute_next_return（唯一口径），
    再把列名转成因子输出口径 [trade_date, symbol, forward_return]。
    """
    panel = compute_next_return(dominant, daily, horizon=horizon)
    panel["trade_date"] = panel["date"].map(_format_date)
    return (
        panel.rename(columns={"underlying_symbol": "symbol", "ret_fwd": "forward_return"})
        [["trade_date", "symbol", "forward_return"]]
        .reset_index(drop=True)
    )


def pearson_ic(x: pd.DataFrame) -> float:
    if x["factor_value"].std() == 0 or x["forward_return"].std() == 0:
        return float("nan")
    return float(x["factor_value"].corr(x["forward_return"]))


def rank_ic(x: pd.DataFrame) -> float:
    fr = x["factor_value"].rank(method="average")
    rr = x["forward_return"].rank(method="average")
    if fr.std() == 0 or rr.std() == 0:
        return float("nan")
    return float(fr.corr(rr))


def information_ratio(returns: pd.Series) -> float:
    std = returns.std()
    if returns.empty or not std:
        return 0.0
    return float(returns.mean() / std * (252 ** 0.5))


def annualized_return(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    cum = float((1 + returns).prod() - 1)
    years = len(returns) / 252
    return float((1 + cum) ** (1 / years) - 1) if years > 0 else cum


def long_short_returns(factor: pd.DataFrame, fwd: pd.DataFrame) -> pd.Series:
    """signal>0 做多、<0 做空，按 |signal| 加权，每日组合收益。"""
    panel = factor.merge(fwd, on=["trade_date", "symbol"], how="inner")
    panel = panel[panel["signal"] != 0].copy()
    if panel.empty:
        return pd.Series(dtype=float)
    panel["w"] = panel["signal"]  # 带符号权重

    def _daily(g):
        denom = g["w"].abs().sum()
        return (g["w"] * g["forward_return"]).sum() / denom if denom > 0 else 0.0

    return panel.groupby("trade_date").apply(_daily, include_groups=False)


def bootstrap_ic_ci(daily_ic: pd.Series, n_bootstrap=500, ci=0.95):
    s = daily_ic.dropna()
    if len(s) < 4:
        return (float("nan"), float("nan"))
    alpha = (1 - ci) / 2
    means = pd.Series([s.sample(n=len(s), replace=True).mean() for _ in range(n_bootstrap)])
    return (round(float(means.quantile(alpha)), 6), round(float(means.quantile(1 - alpha)), 6))


def ic_decay(factor: pd.DataFrame, dominant: pd.DataFrame, daily: pd.DataFrame,
             horizons=(1, 2, 3, 5, 10, 20)) -> dict:
    out = {}
    for h in horizons:
        fwd = build_forward_returns(dominant, daily, horizon=h)
        panel = factor.merge(fwd, on=["trade_date", "symbol"], how="inner")
        if panel.empty:
            out[f"{h}D"] = {"IC": None, "RankIC": None}
            continue
        dic = panel.groupby("trade_date").apply(pearson_ic, include_groups=False).dropna()
        dric = panel.groupby("trade_date").apply(rank_ic, include_groups=False).dropna()
        out[f"{h}D"] = {
            "IC": round(float(dic.mean()), 6) if not dic.empty else None,
            "RankIC": round(float(dric.mean()), 6) if not dric.empty else None,
        }
    return out


def turnover_rate(factor: pd.DataFrame) -> float:
    """
    多空两侧按持仓集合 Jaccard 变化率平均。
    简化口径：只看品种进出（集合变化），不按 |signal| 加权仓位大小；
    因此高强度仓位的频繁换手会被低估，成本敏感性为偏乐观近似。
    """
    def side(sets):
        if sets.empty:
            return 0.0
        vals, prev = [], None
        for cur in sets:
            if prev is not None:
                union = cur | prev
                vals.append(1 - len(cur & prev) / len(union) if union else 0.0)
            prev = cur
        return float(sum(vals) / len(vals)) if vals else 0.0

    longs = factor[factor["signal"] > 0].groupby("trade_date")["symbol"].apply(set)
    shorts = factor[factor["signal"] < 0].groupby("trade_date")["symbol"].apply(set)
    lt, st = side(longs), side(shorts)
    active = (1 if lt > 0 else 0) + (1 if st > 0 else 0)
    return round((lt + st) / active, 6) if active else 0.0


_COST = {"0成本": 0.0, "低(0.05%)": 0.0005, "中(0.15%)": 0.0015, "高(0.30%)": 0.0030}


def cost_sensitivity(ls: pd.Series, to_rate: float) -> dict:
    res = {}
    for label, ow in _COST.items():
        net = ls - to_rate * 2 * ow
        curve = (1 + net).cumprod()
        mdd = (curve / curve.cummax() - 1).min() if not curve.empty else 0.0
        res[label] = {"净ARR(%)": round(annualized_return(net) * 100, 4),
                      "净MDD(%)": round(float(mdd) * 100, 4)}
    return res


def split_oos(factor: pd.DataFrame, train_end="2024-12-31"):
    fy = pd.to_datetime(factor["trade_date"])
    return factor[fy <= train_end], factor[fy > train_end]


def report(factor, dominant, daily, label="全样本"):
    fwd = build_forward_returns(dominant, daily, horizon=1)
    panel = factor.merge(fwd, on=["trade_date", "symbol"], how="inner")
    dic = panel.groupby("trade_date").apply(pearson_ic, include_groups=False).dropna()
    dric = panel.groupby("trade_date").apply(rank_ic, include_groups=False).dropna()
    ic = float(dic.mean()) if not dic.empty else float("nan")
    icir = float(dic.mean() / dic.std()) if dic.std() else float("nan")
    ric = float(dric.mean()) if not dric.empty else float("nan")
    ricir = float(dric.mean() / dric.std()) if dric.std() else float("nan")
    ic_p = stats.ttest_1samp(dic, 0).pvalue if len(dic) > 1 else None
    lo, hi = bootstrap_ic_ci(dic)
    ls = long_short_returns(factor, fwd)
    to = turnover_rate(factor)
    curve = (1 + ls).cumprod()
    mdd = float((curve / curve.cummax() - 1).min()) if not curve.empty else 0.0
    arr = annualized_return(ls) * 100
    cr = (arr / 100) / abs(mdd) if mdd else float("nan")

    print(f"\n===== {label} 研究口径 =====")
    print(f"IC={ic:.4f} ICIR={icir:.4f} RankIC={ric:.4f} RankICIR={ricir:.4f} "
          f"IC_p={ic_p if ic_p is None else round(float(ic_p),4)} "
          f"Bootstrap95%CI=[{lo:.4f},{hi:.4f}]")
    print(f"ARR(%)={arr:.4f} MDD(%)={mdd*100:.4f} CR={cr:.4f} 换手率={to}")
    print(f"IC衰减(1/2/3/5/10/20D)={ic_decay(factor, dominant, daily)}")
    print(f"成本敏感性={cost_sensitivity(ls, to)}")
    return ls


def report_tradeable(factor, dominant, daily):
    """可交易口径：data_lag=1（信号 T，执行 T+1→T+2），换月+交易各 5bps。"""
    fwd = build_forward_returns(dominant, daily, horizon=1)
    dates = sorted(factor["trade_date"].unique())
    lag = {d: dates[i - 1] if i >= 1 else None for i, d in enumerate(dates)}
    f2 = factor.copy()
    f2["trade_date"] = f2["trade_date"].map(lag)
    f2 = f2.dropna(subset=["trade_date"])
    ls = long_short_returns(f2, fwd)
    to = turnover_rate(factor)
    ls_net = ls - to * 2 * 0.0005 - 0.0005  # 交易成本 + 换月近似
    print(f"\n===== 可交易口径 =====")
    print(f"tradeable_ARR(%)={annualized_return(ls_net)*100:.4f} tradeable_IR={information_ratio(ls_net):.4f} "
          f"(data_lag=1, 换月5bps, 交易5bps)")


def main():
    netmarg, dominant, daily, multiplier = load_inputs()
    factor = calculate_factor(netmarg, dominant, daily, multiplier_data=multiplier, update_time="backtest")
    report(factor, dominant, daily, label="全样本")
    train, test = split_oos(factor)
    if not train.empty:
        report(train, dominant, daily, label="样本内(≤2024)")
    if not test.empty:
        report(test, dominant, daily, label="样本外(>2024)")
    report_tradeable(factor, dominant, daily)


if __name__ == "__main__":
    main()
