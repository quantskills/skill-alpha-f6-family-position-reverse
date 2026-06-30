from __future__ import annotations

import pandas as pd

from factor import FAMILY_BROKERS, calculate_factor, load_real_position


REQUIRED_RESULT_COLUMNS = {
    "trade_date",
    "asset_type",
    "symbol",
    "factor_id",
    "factor_name",
    "factor_value",
    "score",
    "rank",
    "signal",
    "confidence",
    "data_version",
    "update_time",
}


def check_no_future_function() -> None:
    positions = load_real_position()
    pos = pd.DataFrame(positions).copy()
    pos["date"] = pos["date"].astype(str).str.replace("-", "", regex=False)

    dates = sorted(pos["date"].unique())
    if len(dates) < 10:
        print("check_no_future_function: 样本不足 10 日，跳过截断检验")
        return

    cut = dates[-5]
    cut_iso = pd.to_datetime(cut, format="%Y%m%d").strftime("%Y-%m-%d")
    factor_full = calculate_factor(pos, update_time="validate")
    factor_short = calculate_factor(pos[pos["date"] < cut], update_time="validate")

    merged = factor_full.merge(factor_short, on=["trade_date", "symbol"], suffixes=("_full", "_short"))
    early = merged[merged["trade_date"] < cut_iso]
    if early.empty:
        print("check_no_future_function: 无重叠样本，跳过比较")
        return

    diff = (early["factor_value_full"] - early["factor_value_short"]).abs()
    assert (diff <= 1e-6).all(), f"存在未来函数嫌疑：删末尾数据后历史因子值改变，max diff={diff.max():.2e}"


def check_required_fields(result) -> None:
    missing = REQUIRED_RESULT_COLUMNS - set(result.columns)
    assert not missing, f"结果缺少字段: {sorted(missing)}"
    assert (result["asset_type"] == "future").all(), "asset_type 必须为 future"
    assert (result["factor_id"] == "F6").all(), "factor_id 必须为 F6"
    assert (result["factor_name"] == "家人仓位反向").all(), "factor_name 必须为 家人仓位反向"
    required_notna = ["trade_date", "symbol", "factor_value", "score", "rank", "signal", "data_version", "update_time"]
    assert result[required_notna].notna().all().all(), "必需字段不能包含空值"


def check_value_range(result) -> None:
    assert result["factor_value"].between(-1, 1).all(), "factor_value 必须位于 [-1, 1]"
    assert result["score"].between(0, 100).all(), "score 必须位于 [0, 100]"
    assert result["confidence"].between(0, 1).all(), "confidence 必须位于 [0, 1]"
    assert (result["rank"] >= 1).all(), "rank 必须大于等于 1"


def check_signal_enum(result) -> None:
    assert set(result["signal"]).issubset({"buy", "sell", "hold"}), "signal 必须属于 buy/sell/hold"


def check_family_brokers_present(positions, min_count: int = 1) -> None:
    counts = positions[positions["broker"].isin(FAMILY_BROKERS)]["broker"].value_counts()
    present = [broker for broker in FAMILY_BROKERS if int(counts.get(broker, 0)) >= min_count]
    assert present, f"家人席位样本不足: {FAMILY_BROKERS}"


def check_out_of_sample_slice(result) -> None:
    dates = sorted(result["trade_date"].unique())
    assert len(dates) >= 2, "样本外检查至少需要两个交易日"
    split_date = dates[(len(dates) - 1) // 2]
    train = result[result["trade_date"] <= split_date]
    test = result[result["trade_date"] > split_date]
    assert not train.empty and not test.empty, "样本外切片不能为空"


if __name__ == "__main__":
    positions = load_real_position()
    result = calculate_factor(positions, update_time="2026-06-01T12:00:00")
    check_no_future_function()
    check_required_fields(result)
    check_value_range(result)
    check_signal_enum(result)
    check_family_brokers_present(positions)
    check_out_of_sample_slice(result)
    print("验证通过：无未来函数，字段完整，取值范围合法，信号枚举合法，家人席位存在，样本外切片可用")
