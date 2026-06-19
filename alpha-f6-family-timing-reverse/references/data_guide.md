# 数据源与字段说明（F6_V2 家人择时反向）

## 数据来源

本因子使用 Panda data SDK 拉取期货席位净持仓、主力合约、日线行情与合约基础信息。正式开发必须使用 Panda data SDK，不得使用来源不明、字段不稳定、个人临时整理的数据文件作为正式输入。

## 环境变量

运行前设置：

```bash
export PANDA_DATA_USERNAME=你的账号
export PANDA_DATA_PASSWORD=你的密码
```

可选参数：

```bash
export PANDA_DATA_START_DATE=2024-01-01
export PANDA_DATA_END_DATE=2026-05-28
export PANDA_DATA_UNDERLYING=A,AG,AU,CU,RB,M,MA,SR,TA,Y   # 留空或 all 表示全部品种
```

## 接口

### `panda_data.get_broker_netmarg`

用途：获取期货席位净持仓保证金。

| 字段 | 口径 |
|---|---|
| date | 交易日期，`YYYYMMDD` |
| underlying_symbol | 期货品种代码 |
| broker | 席位名 |
| net_margin | 净持仓保证金额，正为净多，负为净空 |

### `panda_data.get_future_dominant`

用途：获取每个品种每日主力合约，用于 Method A forward return 的合约映射。

| 字段 | 口径 |
|---|---|
| date | 交易日期，`YYYYMMDD` |
| underlying_symbol | 期货品种代码 |
| symbol | 主力合约代码 |

### `panda_data.get_future_daily`

用途：获取主力合约 `close`（算下一期收益与成交额）、`volume` / `amount`（算成交额热度）。

| 字段 | 口径 |
|---|---|
| date | 交易日期，`YYYYMMDD` |
| symbol | 合约代码 |
| underlying_symbol | 期货品种代码 |
| close | 日频收盘价 |
| volume | 成交量（手） |
| amount | 成交额（若接口返回，优先用于热度排序） |
| open_interest | 合约当日持仓量（备用，本因子热度排序默认用 amount/volume） |

### `panda_data.get_future_detail`

用途：获取合约乘数 `multiplier`，当 `TURNOVER_MODE=vcm` 时用于把成交量换算成可比成交额。

| 字段 | 口径 |
|---|---|
| symbol | 合约代码 |
| underlying_symbol | 期货品种代码 |
| multiplier | 合约乘数 |

## 成交额口径（TURNOVER_MODE）

跨品种比成交额时合约乘数会影响可比性，提供两种口径：

- `amount`（默认，最优）：若 `get_future_daily` 直接返回 `amount` 字段，直接使用，跨品种天然可比。
- `vcm`（回退）：`turnover_raw = volume × close × multiplier`，`multiplier` 取自 `get_future_detail`；接口无 multiplier 时回退为 1.0。

> 上线前需用 `get_future_daily` / `get_future_detail` 实际返回的列名确认 `amount` 与 `multiplier` 是否存在，再设定 `factor.py` 中的 `TURNOVER_MODE`。

## 家人席位

家人席位按精确名称匹配：

```python
FAMILY_BROKERS = ["东方财富", "徽商期货", "平安期货"]
```

样本期内三家席位必须每家至少出现一次，否则验证失败。

## 因子计算（Step 1–6，纯时序，无横截面）

```text
# Step 1 热门 universe（每日滚动 Top 10）
turnover(t,u)  = amount(t,u)  或  volume × close × multiplier
hot_score(t,u) = mean(turnover[t-20 : t-1])           # 滞后到 t-1，无未来函数
universe(t)    = hot_score 排名前 10 的品种            # 每交易日重选
# 非 universe 品种当天不计算、不发信号

# Step 2 家人净持仓变化
family_margin(t,u) = Σ net_margin（东方财富/徽商/平安）
Δfamily(t,u)       = family_margin(t,u) − family_margin(t-1,u)

# Step 3 下一期收益（Method A，同合约）
c_t          = dominant(t,u)
ret_fwd(t,u) = close(t+1, c_t) / close(t, c_t) − 1

# Step 4 滚动相关（家人滚动 IC）+ 固定反向
rollIC(t,u)     = corr(Δfamily[t-20:t-1], ret_fwd[t-20:t-1])
factor_raw(t,u) = − rollIC(t,u)

# Step 5 时序 Z-score（每品种独立，60 日，min_periods=20）
factor_value(t,u) = (factor_raw − rolling_mean(factor_raw,60)) / rolling_std(factor_raw,60)

# Step 6 数值信号
signal(t,u) = clip(factor_value, -3, +3)   if |factor_value| ≥ 0.5
            = 0                             otherwise
```

**无未来函数关键点：** 算 `rollIC(t)` 时窗口结尾为 `t-1`，其 `ret_fwd(t-1)=close(t)/close(t-1)` 在 t 日收盘后可得；universe 用 t-1 滞后成交额。整条链只用 ≤ t-1 形成、≤ t 可观测的数据。

## 回测口径

Method A：`forward_return(t,u)=close(t+1,c_t)/close(t,c_t)-1`，换月价差不计入。多空组合按 `sign(signal)` 分多空、`|signal|` 加权；仅在热门 Top 10 内。MVP 不显式建模手续费、滑点、保证金占用；可交易口径下显式加 data_lag=1、换月 5bps、交易 5bps。

## 清洗规则

- `date` 内部统一 `YYYYMMDD`，输出 `YYYY-MM-DD`。
- `underlying_symbol` 转大写并输出为 `symbol`。
- `net_margin` / `close` 必须可转为数值。
- 家人席位当日全部未出现时 `family_margin = 0`。
- 非热门 universe 品种当日不发信号。
- 接口整体无数据时脚本抛错并停止。
