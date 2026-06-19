from __future__ import annotations

import math
import os
from datetime import datetime
from typing import Any

import pandas as pd

FACTOR_ID = "F6_V2"
FACTOR_NAME = "家人择时反向"
FAMILY_BROKERS = ["东方财富", "徽商期货", "平安期货"]
DATA_VERSION = "real-v1"

# 热门 universe
TOP_K = 10
HOT_WINDOW = 20            # 近 N 日均成交额
# "amount" = 直接用 get_future_daily 的 amount 字段（若存在，最优）
# "vcm"    = volume × close × multiplier 回退口径
TURNOVER_MODE = "amount"   # 按 Task 0 Step 2 探测结果设定

# 相关性与标准化
CORR_WINDOW = 20           # 滚动相关系数窗口
ZSCORE_WINDOW = 60
MIN_ZSCORE_PERIODS = 20

# 信号
SIGNAL_THRESHOLD = 0.5     # 进场 Z 阈值
SIGNAL_CLIP = 3.0          # signal 裁剪范围 ±3

REQUIRED_NETMARG_COLUMNS = {"date", "underlying_symbol", "broker", "net_margin"}
REQUIRED_DAILY_COLUMNS = {"date", "symbol", "underlying_symbol", "close"}
_BATCH = 5


# ---------------------------------------------------------------------------
# Task 1: 输入校验
# ---------------------------------------------------------------------------
def validate_netmarg(input_data: Any) -> pd.DataFrame:
    df = pd.DataFrame(input_data)
    if df.empty:
        raise ValueError("席位净持仓数据不能为空")
    missing = REQUIRED_NETMARG_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"席位净持仓数据缺少必要字段: {sorted(missing)}")
    cleaned = df.copy()
    cleaned["date"] = cleaned["date"].astype(str).str.replace("-", "", regex=False)
    if (~cleaned["date"].str.fullmatch(r"\d{8}")).any():
        raise ValueError("date 必须是 YYYYMMDD 或 YYYY-MM-DD")
    cleaned["underlying_symbol"] = cleaned["underlying_symbol"].astype(str).str.upper()
    cleaned["broker"] = cleaned["broker"].astype(str)
    cleaned["net_margin"] = pd.to_numeric(cleaned["net_margin"], errors="raise")
    if cleaned["underlying_symbol"].str.len().eq(0).any():
        raise ValueError("underlying_symbol 不能为空")
    return cleaned.sort_values(["date", "underlying_symbol", "broker"]).reset_index(drop=True)


def validate_daily(input_data: Any) -> pd.DataFrame:
    df = pd.DataFrame(input_data)
    if df.empty:
        raise ValueError("日线数据不能为空")
    missing = REQUIRED_DAILY_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"日线数据缺少必要字段: {sorted(missing)}")
    cleaned = df.copy()
    cleaned["date"] = cleaned["date"].astype(str).str.replace("-", "", regex=False)
    cleaned["symbol"] = cleaned["symbol"].astype(str)
    cleaned["underlying_symbol"] = cleaned["underlying_symbol"].astype(str).str.upper()
    cleaned["close"] = pd.to_numeric(cleaned["close"], errors="raise")
    return cleaned.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Task 2: 热门 universe（每日滚动 Top K）
# ---------------------------------------------------------------------------
def prepare_turnover(daily: pd.DataFrame, multiplier: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    返回每个品种每日成交额 turnover_raw（按 TURNOVER_MODE）。
    daily 已是主力合约日线（每品种每日一行）。
    """
    df = daily.copy()
    if TURNOVER_MODE == "amount":
        if "amount" not in df.columns:
            raise ValueError("TURNOVER_MODE=amount 但 daily 缺少 amount 字段")
        df["turnover_raw"] = pd.to_numeric(df["amount"], errors="raise")
    else:  # vcm
        if "volume" not in df.columns:
            raise ValueError("TURNOVER_MODE=vcm 但 daily 缺少 volume 字段")
        df["volume"] = pd.to_numeric(df["volume"], errors="raise")
        df["close"] = pd.to_numeric(df["close"], errors="raise")
        if multiplier is not None and "multiplier" in multiplier.columns:
            mul = multiplier[["underlying_symbol", "multiplier"]].drop_duplicates("underlying_symbol")
            df = df.merge(mul, on="underlying_symbol", how="left")
            df["multiplier"] = pd.to_numeric(df["multiplier"], errors="coerce").fillna(1.0)
        else:
            df["multiplier"] = 1.0
        df["turnover_raw"] = df["volume"] * df["close"] * df["multiplier"]
    return df[["date", "underlying_symbol", "turnover_raw"]].reset_index(drop=True)


def compute_hot_universe(daily: pd.DataFrame, top_k: int = TOP_K, hot_window: int = HOT_WINDOW) -> pd.DataFrame:
    """
    返回 [date, underlying_symbol]，每日 hot_score 滞后均值 Top K。
    hot_score(t,u) = mean(turnover_raw[t-hot_window : t-1])，shift(1) 保证滞后，无未来函数。
    """
    if "turnover_raw" in daily.columns:
        tv = daily[["date", "underlying_symbol", "turnover_raw"]].copy()
    else:
        tv = prepare_turnover(daily)
    tv = tv.sort_values(["underlying_symbol", "date"]).reset_index(drop=True)
    tv["hot_score"] = (
        tv.groupby("underlying_symbol")["turnover_raw"]
        .transform(lambda s: s.rolling(hot_window, min_periods=hot_window).mean().shift(1))
    )
    tv = tv.dropna(subset=["hot_score"])
    tv["hot_rank"] = tv.groupby("date")["hot_score"].rank(ascending=False, method="first")
    universe = tv[tv["hot_rank"] <= top_k][["date", "underlying_symbol"]].reset_index(drop=True)
    return universe


# ---------------------------------------------------------------------------
# Task 3: 家人净持仓变化 + 下一期收益（Method A）
# ---------------------------------------------------------------------------
def compute_family_delta(netmarg: pd.DataFrame) -> pd.DataFrame:
    """每品种每日家人席位净持仓 family_margin 及其一阶差分 delta_family。"""
    fam = (
        netmarg[netmarg["broker"].isin(FAMILY_BROKERS)]
        .groupby(["date", "underlying_symbol"], as_index=False)["net_margin"]
        .sum()
        .rename(columns={"net_margin": "family_margin"})
    )
    fam = fam.sort_values(["underlying_symbol", "date"]).reset_index(drop=True)
    fam["delta_family"] = fam.groupby("underlying_symbol")["family_margin"].diff()
    return fam.dropna(subset=["delta_family"]).reset_index(drop=True)


def compute_next_return(dominant: pd.DataFrame, daily: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    """
    Method A 收益：ret_fwd(t,u)=close(t+horizon,c_t)/close(t,c_t)-1。
    返回 [date, underlying_symbol, ret_fwd]。horizon=1 为下一期收益（因子默认）。
    这是 factor 与 backtest 共用的唯一前向收益实现，避免口径漂移。
    """
    dom = dominant[["date", "underlying_symbol", "symbol"]].copy()
    dom["date"] = dom["date"].astype(str).str.replace("-", "", regex=False)
    dom["underlying_symbol"] = dom["underlying_symbol"].astype(str).str.upper()
    dom = dom.rename(columns={"symbol": "contract"})
    dom = dom.sort_values(["underlying_symbol", "date"]).reset_index(drop=True)
    dom["next_date"] = dom.groupby("underlying_symbol")["date"].shift(-horizon)

    px = daily[["date", "symbol", "close"]].copy()
    px["date"] = px["date"].astype(str).str.replace("-", "", regex=False)
    px["close"] = pd.to_numeric(px["close"], errors="raise")
    cur = px.rename(columns={"symbol": "contract", "close": "close_t"})
    nxt = px.rename(columns={"date": "next_date", "symbol": "contract", "close": "close_t1"})
    panel = (
        dom.merge(cur, on=["date", "contract"], how="left")
        .merge(nxt, on=["next_date", "contract"], how="left")
    )
    panel = panel[(panel["close_t"] > 0) & panel["close_t1"].notna()].copy()
    if panel.empty:
        raise ValueError(
            "前向收益为空：dominant 与 daily 的 (date, 合约) 无法对齐，"
            "请检查日期格式与主力合约映射是否一致"
        )
    panel["ret_fwd"] = panel["close_t1"] / panel["close_t"] - 1
    return panel[["date", "underlying_symbol", "ret_fwd"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Task 4: 滚动相关（家人滚动 IC）+ 固定反向
# ---------------------------------------------------------------------------
def compute_rolling_factor_raw(
    family_delta: pd.DataFrame,
    next_return: pd.DataFrame,
    corr_window: int = CORR_WINDOW,
) -> pd.DataFrame:
    """
    rollIC(t,u) = corr(delta_family[t-window:t-1], ret_fwd[t-window:t-1])
    factor_raw(t,u) = -rollIC(t,u)  固定反向。
    用 shift(1) 把窗口结尾对齐到 t-1，无未来函数。
    """
    panel = (
        family_delta.merge(next_return, on=["date", "underlying_symbol"], how="inner")
        .sort_values(["underlying_symbol", "date"])
        .reset_index(drop=True)
    )

    def _roll(s: pd.Series) -> pd.Series:
        grp = panel.loc[s.index]
        c = grp["delta_family"].rolling(corr_window, min_periods=corr_window).corr(grp["ret_fwd"])
        return c.shift(1)

    panel["roll_ic"] = (
        panel.groupby("underlying_symbol", group_keys=False)["delta_family"].apply(_roll)
    )
    panel["factor_raw"] = -panel["roll_ic"]
    return panel[["date", "underlying_symbol", "factor_raw"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Task 5: 时序 Z-score + 时序分位 score + 数值信号
# ---------------------------------------------------------------------------
def apply_timeseries_zscore_and_signal(
    raw: pd.DataFrame,
    zscore_window: int = ZSCORE_WINDOW,
    min_periods: int = MIN_ZSCORE_PERIODS,
    threshold: float = SIGNAL_THRESHOLD,
    clip: float = SIGNAL_CLIP,
) -> pd.DataFrame:
    """
    factor_value = 时序 Z-score(factor_raw, zscore_window)
    score        = factor_value 的时序滚动百分位 × 100（该品种自身历史，非横截面）
    signal       = clip(factor_value, -clip, clip) if |factor_value|>=threshold else 0
    confidence   = |signal| / clip
    """
    min_periods = max(2, min(min_periods, zscore_window))
    df = raw.dropna(subset=["factor_raw"]).sort_values(["underlying_symbol", "date"]).copy()
    g = df.groupby("underlying_symbol")["factor_raw"]
    roll = g.rolling(zscore_window, min_periods=min_periods)
    mean = roll.mean().reset_index(level=0, drop=True)
    std = roll.std().reset_index(level=0, drop=True)
    # std=NaN 表示窗口未满（warm-up），factor_value 置 NaN 后丢弃；
    # std=0 表示窗口内常数序列，factor_value 置 0.0 保留。
    fv = (df["factor_raw"] - mean) / std
    fv = fv.replace([float("inf"), float("-inf")], pd.NA)
    fv = fv.mask(std == 0, 0.0)        # 仅当 std 恰为 0（非 NaN）时置 0
    df["factor_value"] = fv
    df = df.dropna(subset=["factor_value"]).reset_index(drop=True)

    # 时序分位 score：每品种自身历史 factor_value 的滚动百分位
    def _pct(s: pd.Series) -> pd.Series:
        return s.rolling(zscore_window, min_periods=min_periods).apply(
            lambda w: (w <= w[-1]).mean(), raw=True
        )
    df["score"] = (
        df.groupby("underlying_symbol")["factor_value"].transform(_pct).fillna(0.5) * 100
    ).round(2)

    fv = df["factor_value"]
    sig = fv.clip(-clip, clip)
    sig = sig.where(fv.abs() >= threshold, 0.0)
    df["signal"] = sig.round(6)
    df["confidence"] = (df["signal"].abs() / clip).round(4)
    return df


# ---------------------------------------------------------------------------
# Task 6: 主装配 calculate_factor + universe 过滤 + 输出 schema
# ---------------------------------------------------------------------------
def _date_to_yyyymmdd(value: str) -> str:
    text = str(value).replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"日期必须是 YYYY-MM-DD 或 YYYYMMDD: {value}")
    return text


def _date_to_iso(value: str) -> str:
    return pd.to_datetime(str(value), format="%Y%m%d").strftime("%Y-%m-%d")


OUTPUT_COLUMNS = [
    "trade_date", "asset_type", "symbol", "factor_id", "factor_name",
    "factor_value", "score", "rank", "signal", "confidence",
    "data_version", "update_time",
]


def calculate_factor(
    netmarg_data: Any,
    dominant_data: Any,
    daily_data: Any,
    update_time: str | None = None,
    multiplier_data: Any | None = None,
    top_k: int = TOP_K,
    hot_window: int = HOT_WINDOW,
    corr_window: int = CORR_WINDOW,
    zscore_window: int = ZSCORE_WINDOW,
    min_zscore_periods: int = MIN_ZSCORE_PERIODS,
    threshold: float = SIGNAL_THRESHOLD,
    clip: float = SIGNAL_CLIP,
) -> pd.DataFrame:
    update_time = update_time or datetime.now().isoformat(timespec="seconds")
    netmarg = validate_netmarg(netmarg_data)
    daily = validate_daily(daily_data)
    dominant = pd.DataFrame(dominant_data)

    # 主力日线（每品种每日一行）：从 daily 里按 dominant 合约挑出
    dom = dominant[["date", "underlying_symbol", "symbol"]].copy()
    dom["date"] = dom["date"].astype(str).str.replace("-", "", regex=False)
    dom["underlying_symbol"] = dom["underlying_symbol"].astype(str).str.upper()
    dom_daily = daily.merge(
        dom.rename(columns={"symbol": "dom_symbol"}),
        left_on=["date", "underlying_symbol", "symbol"],
        right_on=["date", "underlying_symbol", "dom_symbol"],
        how="inner",
    )

    turnover = prepare_turnover(
        dom_daily,
        multiplier=pd.DataFrame(multiplier_data) if multiplier_data is not None else None,
    )
    universe = compute_hot_universe(turnover, top_k=top_k, hot_window=hot_window)

    family_delta = compute_family_delta(netmarg)
    next_return = compute_next_return(dominant, daily)
    factor_raw = compute_rolling_factor_raw(family_delta, next_return, corr_window=corr_window)

    scored = apply_timeseries_zscore_and_signal(
        factor_raw, zscore_window=zscore_window, min_periods=min_zscore_periods,
        threshold=threshold, clip=clip,
    )

    # universe 过滤：仅保留热门品种
    scored = scored.merge(universe, on=["date", "underlying_symbol"], how="inner")

    scored["trade_date"] = scored["date"].map(_date_to_iso)
    scored["symbol"] = scored["underlying_symbol"]
    scored["asset_type"] = "future"
    scored["factor_id"] = FACTOR_ID
    scored["factor_name"] = FACTOR_NAME
    scored["data_version"] = DATA_VERSION
    scored["update_time"] = update_time

    # rank：当日 universe 内按 factor_value 降序，1=最高（弱化字段，仅参考）
    scored["rank"] = (
        scored.groupby("trade_date")["factor_value"].rank(ascending=False, method="first").astype(int)
    )

    result = scored[OUTPUT_COLUMNS].sort_values(["trade_date", "rank", "symbol"]).reset_index(drop=True)
    return result


# ---------------------------------------------------------------------------
# Task 7: 数据加载（联网）+ __main__
# ---------------------------------------------------------------------------
def _get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"请先设置环境变量 {name}")
    return value


def _parse_underlying(value: str | None) -> list[str] | None:
    if not value or value.strip().lower() == "all":
        return None
    symbols = [item.strip().upper() for item in value.split(",") if item.strip()]
    return symbols or None


def _batched(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]


_RATE_LIMIT_CODE = "500010"
_TOKEN_EXPIRED_CODE = "200004"


def _call_with_retry(fn, *args, max_retries: int = 6, base_wait: float = 10.0, **kwargs):
    """
    调用 fn(*args, **kwargs)，遇到限频/Token过期/网络超时等瞬时错误时退避重试。
    - Token 过期：重新登录后立即重试。
    - 限频：指数退避后重试。
    - 超时/其他瞬时网络错误（含 'timed out' / 'Unexpected error'）：指数退避后重试。
    最终仍失败才抛出。
    """
    import time

    import panda_data
    from panda_data.exceptions import ServiceError

    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except ServiceError as e:
            last_exc = e
            err = str(e)
            if attempt >= max_retries - 1:
                raise
            if _TOKEN_EXPIRED_CODE in err:
                print(f"  [Token过期] 重新登录后重试 (第 {attempt + 1}/{max_retries} 次)...")
                try:
                    panda_data.init_token()
                except Exception:
                    pass
                continue
            wait = base_wait * (2 ** attempt)
            reason = "限频" if _RATE_LIMIT_CODE in err else "网络瞬时错误"
            print(f"  [{reason}] {err[:80]} → 等待 {wait:.0f}s 后重试 (第 {attempt + 1}/{max_retries} 次)...")
            time.sleep(wait)
        except (TimeoutError, OSError, ConnectionError) as e:
            last_exc = e
            if attempt >= max_retries - 1:
                raise
            wait = base_wait * (2 ** attempt)
            print(f"  [网络超时] {str(e)[:80]} → 等待 {wait:.0f}s 后重试 (第 {attempt + 1}/{max_retries} 次)...")
            time.sleep(wait)
    if last_exc is not None:
        raise last_exc


def load_inputs(
    underlying_symbols: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """返回 (netmarg, dominant, daily, multiplier)。"""
    import time

    import panda_data

    username = _get_env("PANDA_DATA_USERNAME")
    password = _get_env("PANDA_DATA_PASSWORD")
    if underlying_symbols is None:
        underlying_symbols = _parse_underlying(os.getenv("PANDA_DATA_UNDERLYING"))
    start = _date_to_yyyymmdd(start_date or os.getenv("PANDA_DATA_START_DATE", "2024-01-01"))
    end = _date_to_yyyymmdd(end_date or os.getenv("PANDA_DATA_END_DATE", "2026-05-28"))

    panda_data.init_token(username=username, password=password)

    print("加载席位净持仓 ...")
    netmarg = _call_with_retry(
        panda_data.get_broker_netmarg,
        start_date=start, end_date=end, broker="", underlying_symbol=underlying_symbols,
    )
    if netmarg.empty:
        raise ValueError("Panda data 未返回席位净持仓数据")
    netmarg = netmarg[["date", "underlying_symbol", "broker", "net_margin"]]

    # universe 候选：netmarg 出现过的品种
    if underlying_symbols is None:
        underlying_symbols = sorted(netmarg["underlying_symbol"].astype(str).str.upper().unique().tolist())

    dom_chunks = []
    dom_batches = list(_batched(underlying_symbols, _BATCH))
    for i, batch in enumerate(dom_batches):
        print(f"加载主力合约 batch {i + 1}/{len(dom_batches)}: {batch}")
        chunk = _call_with_retry(
            panda_data.get_future_dominant, underlying_symbol=batch, start_date=start, end_date=end
        )
        if not chunk.empty:
            dom_chunks.append(chunk)
        if i < len(dom_batches) - 1:
            time.sleep(2.0)
    if not dom_chunks:
        raise ValueError("Panda data 未返回主力合约数据")
    dominant = pd.concat(dom_chunks, ignore_index=True)

    contracts = sorted(dominant["symbol"].dropna().astype(str).unique().tolist())
    daily_chunks = []
    daily_batches = list(_batched(contracts, _BATCH))
    for i, batch in enumerate(daily_batches):
        print(f"加载日线数据 batch {i + 1}/{len(daily_batches)}: {batch}")
        chunk = _call_with_retry(
            panda_data.get_future_daily, symbol=batch, start_date=start, end_date=end, fields=[]
        )
        if not chunk.empty:
            daily_chunks.append(chunk)
        if i < len(daily_batches) - 1:
            time.sleep(2.0)
    if not daily_chunks:
        raise ValueError("Panda data 未返回期货日线数据")
    daily = pd.concat(daily_chunks, ignore_index=True)

    print("加载合约乘数 ...")
    # 只查 dominant 里实际用到的合约，避免请求全市场触发套餐限额(600003)
    target_contracts = sorted(dominant["symbol"].dropna().astype(str).unique().tolist())
    multiplier = pd.DataFrame(columns=["underlying_symbol", "multiplier"])
    if target_contracts:
        mul_chunks = []
        mul_batches = list(_batched(target_contracts, _BATCH))
        for i, batch in enumerate(mul_batches):
            print(f"加载合约乘数 batch {i + 1}/{len(mul_batches)}: {batch}")
            chunk = _call_with_retry(
                panda_data.get_future_detail, symbol=batch, fields=[], is_trading=None
            )
            if not chunk.empty and "multiplier" in chunk.columns:
                mul_chunks.append(chunk[["underlying_symbol", "multiplier"]])
            if i < len(mul_batches) - 1:
                time.sleep(2.0)
        if mul_chunks:
            multiplier = pd.concat(mul_chunks, ignore_index=True).drop_duplicates("underlying_symbol")

    return netmarg, dominant, daily, multiplier


if __name__ == "__main__":
    import pathlib

    netmarg, dominant, daily, multiplier = load_inputs()
    result = calculate_factor(
        netmarg, dominant, daily, multiplier_data=multiplier,
        update_time=datetime.now().isoformat(timespec="seconds"),
    )
    print(result.to_string(index=False))
    out = (
        pathlib.Path(__file__).parent.parent.parent
        / "alpha-f6-v2-family-timing-reverse-production"
        / "database.parquet"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(out, index=False)
    print(f"写出 {len(result)} 行 → {out}")
