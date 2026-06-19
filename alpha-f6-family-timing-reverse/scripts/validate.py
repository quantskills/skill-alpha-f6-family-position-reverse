from __future__ import annotations

import sys

import pandas as pd

from factor import (
    FACTOR_ID, FAMILY_BROKERS, TOP_K, SIGNAL_CLIP,
    calculate_factor, load_inputs,
    compute_family_delta, compute_next_return, compute_rolling_factor_raw,
    validate_netmarg, validate_daily,
)
# 第二层过拟合报告复用回测的前向收益与 IC 实现（单一口径，避免漂移）。
from backtest import build_forward_returns, pearson_ic


def check_schema(df: pd.DataFrame) -> list[str]:
    errs = []
    expected = ["trade_date", "asset_type", "symbol", "factor_id", "factor_name",
                "factor_value", "score", "rank", "signal", "confidence",
                "data_version", "update_time"]
    if list(df.columns) != expected:
        errs.append(f"字段不符: {list(df.columns)}")
    if df[["trade_date", "factor_id", "symbol"]].duplicated().any():
        errs.append("主键 trade_date+factor_id+symbol 存在重复")
    if not df["signal"].between(-SIGNAL_CLIP, SIGNAL_CLIP).all():
        errs.append("signal 超出 [-3,3]")
    if not df["score"].between(0, 100).all():
        errs.append("score 超出 [0,100]")
    if not df["confidence"].between(0, 1).all():
        errs.append("confidence 超出 [0,1]")
    if (df["factor_id"] != FACTOR_ID).any():
        errs.append("factor_id 非 F6_V2")
    return errs


def check_universe_size(df: pd.DataFrame) -> list[str]:
    per_day = df.groupby("trade_date")["symbol"].nunique()
    if per_day.max() > TOP_K:
        return [f"某日 universe 超过 TOP_K={TOP_K}: max={per_day.max()}"]
    return []


def check_no_lookahead(netmarg, dominant, daily) -> list[str]:
    """
    截断检验：删掉末尾若干日的数据重算，早期（截断点之前）的 factor_value 应与全量一致
    （因子只用历史，删未来数据不应改变历史值）。
    """
    nm = validate_netmarg(netmarg)
    dl = validate_daily(daily)
    dom_full = pd.DataFrame(dominant)
    dom_full["date"] = dom_full["date"].astype(str).str.replace("-", "", regex=False)

    # 用三个数据源各自的最大日期取交集，作为统一的截断基准，避免某源含更晚日期被静默丢弃
    common_last = min(nm["date"].max(), dl["date"].max(), dom_full["date"].max())
    dates = sorted(d for d in nm["date"].unique() if d <= common_last)
    if len(dates) < 90:
        return []  # 样本太短跳过
    cut = dates[-5]  # 删掉最后 5 个交易日

    nm_full = nm[nm["date"] <= common_last]
    dl_full = dl[dl["date"] <= common_last]
    nm_short = nm[nm["date"] < cut]
    dl_short = dl[dl["date"] < cut]
    dom_short = dom_full[dom_full["date"] < cut]

    full = calculate_factor(nm_full, dom_full, dl_full, update_time="x")
    short = calculate_factor(nm_short, dom_short, dl_short, update_time="x")
    merged = full.merge(short, on=["trade_date", "symbol"], suffixes=("_full", "_short"))
    cut_iso = pd.to_datetime(cut, format="%Y%m%d").strftime("%Y-%m-%d")
    early = merged[merged["trade_date"] < cut_iso]
    if early.empty:
        return ["截断检验无重叠样本，无法验证未来函数"]
    diff = (early["factor_value_full"] - early["factor_value_short"]).abs()
    if (diff > 1e-6).any():
        return [f"疑似未来函数：删未来数据后历史 factor_value 改变，max diff={diff.max():.2e}"]
    return []


def check_family_present(netmarg) -> list[str]:
    nm = validate_netmarg(netmarg)
    present = set(nm["broker"].unique())
    missing = [b for b in FAMILY_BROKERS if b not in present]
    if missing:
        return [f"家人席位缺失: {missing}"]
    return []


def check_oos(df: pd.DataFrame) -> list[str]:
    years = pd.to_datetime(df["trade_date"]).dt.year
    if years.nunique() < 2:
        return ["样本未跨年份，无法做样本外切片"]
    return []


def report_overfit(df, dominant, daily, train_end="2024-12-31") -> list[str]:
    """
    第二层 过拟合：报告训练/测试 IC，训练 IC 显著、测试 IC 大幅衰减时告警。
    返回的是告警信息（非硬性失败），用于人工降级评估。
    """
    from backtest import build_forward_returns, pearson_ic

    fwd = build_forward_returns(dominant, daily, horizon=1)
    fy = pd.to_datetime(df["trade_date"])
    train = df[fy <= train_end]
    test = df[fy > train_end]
    if train.empty or test.empty:
        print("  [过拟合] 训练/测试切片为空，跳过 IC 衰减报告")
        return []

    def _ic(part):
        panel = part.merge(fwd, on=["trade_date", "symbol"], how="inner")
        if panel.empty:
            return float("nan")
        dic = panel.groupby("trade_date").apply(pearson_ic, include_groups=False).dropna()
        return float(dic.mean()) if not dic.empty else float("nan")

    ic_train, ic_test = _ic(train), _ic(test)
    print(f"  [过拟合] 训练IC(≤{train_end})={ic_train:.4f}  测试IC(>{train_end})={ic_test:.4f}")
    warns = []
    if pd.notna(ic_train) and pd.notna(ic_test) and abs(ic_train) > 0.02:
        if ic_train * ic_test < 0:
            warns.append(f"过拟合告警：训练/测试 IC 方向相反（{ic_train:.4f} vs {ic_test:.4f}），需降级评估")
        elif abs(ic_test) < abs(ic_train) * 0.3:
            warns.append(f"过拟合告警：测试 IC 衰减超 70%（{ic_train:.4f}→{ic_test:.4f}），需降级评估")
    return warns


def main() -> int:
    netmarg, dominant, daily, multiplier = load_inputs()
    df = calculate_factor(netmarg, dominant, daily, multiplier_data=multiplier, update_time="validate")

    all_errs = []
    all_errs += check_schema(df)
    all_errs += check_universe_size(df)
    all_errs += check_family_present(netmarg)
    all_errs += check_oos(df)
    all_errs += check_no_lookahead(netmarg, dominant, daily)

    # 第二层 过拟合：报告训练/测试 IC（告警，不硬性失败）
    overfit_warns = report_overfit(df, dominant, daily)
    for w in overfit_warns:
        print(f"  - [warn] {w}")

    if all_errs:
        print("验证失败：")
        for e in all_errs:
            print(f"  - {e}")
        return 1
    print(f"验证通过：{len(df)} 行，{df['trade_date'].nunique()} 个交易日，"
          f"{df['symbol'].nunique()} 个品种；无未来函数、字段完整、universe≤{TOP_K}、家人席位齐全、跨年份。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
