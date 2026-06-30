# F6 Data Guide

## Required Panda Data

| Data | Interface | Required Fields |
|---|---|---|
| Broker net margin | `panda_data.get_broker_netmarg` | `date`, `underlying_symbol`, `broker`, `net_margin` |
| Dominant contract | `panda_data.get_future_dominant` | `date`, `underlying_symbol`, `symbol` |
| Futures daily | `panda_data.get_future_daily` | `date`, `symbol`, `close` |

## Environment Variables

- `PANDA_DATA_USERNAME`: required.
- `PANDA_DATA_PASSWORD`: required.
- `PANDA_DATA_START_DATE`: optional, default `2024-01-01`.
- `PANDA_DATA_END_DATE`: optional, default `2026-05-28`.
- `PANDA_DATA_UNDERLYING`: optional comma-separated symbols; unset or `all` means all available symbols.

## Broker Semantics

- `net_margin > 0`: net long margin.
- `net_margin < 0`: net short margin.
- Missing family brokers are treated as zero family net exposure.
- Rows with `total_margin = 0` are excluded from the factor cross-section.

## 因子计算

```text
# 1. 家人席位净持仓保证金
family_margin(t, u) = sum(net_margin for broker in FAMILY_BROKERS)

# 2. 全市场席位保证金规模
total_margin(t, u) = sum(abs(net_margin) for all brokers where underlying_symbol = u)

# 3. 原始权重
raw_weight(t, u) = -family_margin(t, u) / total_margin(t, u)

# 4. 因子值（当日截面百分位映射到 [-1, 1]，非时序）
factor_value(t, u) = rank_pct(raw_weight, 当日全品种) * 2 - 1
```

排序方向：`factor_value` 越大越好。家人净空越大，反向后的因子值越高；家人净多越大，反向后的因子值越低。

## 信号规则

```text
rank <= ceil(n * 0.1)          -> buy
rank > n - ceil(n * 0.1)       -> sell
其余                            -> hold
# rank=1 为 factor_value 最高；total_margin=0 的品种当日排除
```

## 清洗规则

- `date` 输出为 `YYYY-MM-DD`。
- `underlying_symbol` 转大写后输出为 `symbol`。
- `broker` 按字符串精确匹配。
- `net_margin` 必须为数值。
- 家人席位当日全部未出现时，`family_margin = 0`，保留该品种记录。
- 当日某品种 `total_margin = 0` 时，剔除该品种当日记录。

## 回测口径

Method A 使用同一合约收益：

```text
c_t = dominant(t, u)
forward_return(t, u) = close(t+1, c_t) / close(t, c_t) - 1
```

即使 `t+1` 日主力切换到新合约，本期收益仍使用 `t` 日主力合约 `c_t` 在 `t+1` 的收盘价。换月价差不计入研究口径收益；可交易口径显式扣除换月成本。
