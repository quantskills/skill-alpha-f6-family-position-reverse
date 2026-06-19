---
name: alpha-f6-v2-family-timing-reverse
description: 当需要开发、计算、验证家人择时反向（时序）因子时，使用此 skill。在每日成交最热门的 Top10 品种上，滚动计算家人席位净持仓变化与下一期收益的相关系数（家人滚动 IC），取负、做时序 Z-score，输出连续方向数值信号；支持无未来函数检测、IC/ICIR 回测评估和多空信号输出。
tags: [quant, alpha, development, future]
---

# 家人择时反向（时序）Alpha

## 适用场景

- 当用户需要计算「家人席位择时能力反向」时序因子时
- 当用户需要验证家人席位（东方财富、徽商期货、平安期货）在热门品种上的反向择时是否有效时
- 当用户需要在每日热门 Top10 品种上生成多空双向候选信号时

## 因子逻辑

- 核心因果链：品种放量持续热门 → 赚钱效应吸引散户 → 家人席位高位追多 → 主力派发反转 → 散户套牢。散户只在已经热起来的品种大量参与，故「热门」是反向有效性的前提。
- 因子本质：在每个热门品种上滚动计算 `corr(家人净持仓变化, 下一期收益)`，即家人席位的滚动 IC。家人是散户特征，长期应负相关（踩反）；`factor_value = -rollIC`，固定反向。`rollIC` 越负 → 因子越高 → 越看多。
- 热门 universe：每日按近 20 日均成交额排序取 Top 10，滞后到 t-1，无未来函数；非 universe 品种不发信号。
- 时序标准化：每品种独立 60 日滚动 Z-score（min_periods=20），不使用横截面。
- 信号：`signal = clip(factor_value, -3, +3)`，`|factor_value| < 0.5` 时置 0；`>0` 做多、`<0` 做空、`=0` 观望，绝对值为仓位强度。
- 排序方向：`factor_value` 越大越好。
- 适用市场：商品期货日频时序，热门 Top10。

## 与原 F6 的区别

| 维度 | F6 家人仓位反向 | F6_V2 家人择时反向（本因子） |
|---|---|---|
| 信息源 | 当日家人持仓占全市场比例（静态截面） | 家人持仓变化与下一期收益的滚动相关（动态择时） |
| universe | 全部品种 | 仅热门 Top 10 |
| 信号生成 | 横截面百分位排名 | 时序 Z-score 阈值 |
| signal | `buy/sell/hold` 字符串 | 连续方向数值 `clip(fv,-3,3)`，多空双向 |
| 性质 | 横截面因子 | 纯时序因子 |

## 输入数据

因子计算必须使用 Panda data SDK，不读取本地表格作为正式输入。

| 字段 | 说明 | 来源 |
|---|---|---|
| date / underlying_symbol / broker / net_margin | 席位净持仓保证金 | `panda_data.get_broker_netmarg` |
| date / underlying_symbol / symbol | 每日主力合约 | `panda_data.get_future_dominant` |
| date / symbol / close / volume / amount | 主力合约日线 | `panda_data.get_future_daily` |
| symbol / underlying_symbol / multiplier | 合约乘数 | `panda_data.get_future_detail` |

## 输出结果

| 字段 | 说明 |
|---|---|
| trade_date | `YYYY-MM-DD` 交易日 |
| asset_type | 固定为 `future` |
| symbol | 期货品种代码 |
| factor_id | 固定为 `F6_V2` |
| factor_name | 固定为 `家人择时反向` |
| factor_value | `-rollIC` 经 60 日时序 Z-score，无固定范围 |
| score | factor_value 的时序滚动百分位（该品种自身历史，非横截面），`[0,100]` |
| rank | 当日热门 universe 内排名，1=factor 最高（弱化字段，仅参考） |
| signal | 连续方向数值 `clip(factor_value,-3,3)`，`\|fv\|<0.5` 置 0 |
| confidence | `\|signal\| / 3`，范围 `[0,1]` |
| data_version | 固定为 `real-v1` |
| update_time | ISO8601 生成时间 |

## 关键参数

| 参数 | 值 | 说明 |
|---|---|---|
| FAMILY_BROKERS | 东方财富 / 徽商期货 / 平安期货 | 家人席位，精确匹配 |
| TOP_K | 10 | 热门 universe 品种数 |
| HOT_WINDOW | 20 | 近 N 日均成交额（滞后 t-1） |
| CORR_WINDOW | 20 | 滚动相关系数窗口 |
| ZSCORE_WINDOW | 60 | 时序 Z-score 窗口 |
| MIN_ZSCORE_PERIODS | 20 | Z-score 最小样本 |
| SIGNAL_THRESHOLD | 0.5 | 进场 Z 阈值 |
| SIGNAL_CLIP | 3.0 | signal 裁剪范围 ±3 |
| TURNOVER_MODE | amount / vcm | 成交额口径，amount 优先，vcm 回退 |

## 因子评价标准

| 分类 | 指标 | 方向 | 说明 |
|---|---|---|---|
| Factor Predictive Power | IC / Rank IC | 越高越好 | 因子值与下一期收益的相关 |
| Factor Predictive Power | ICIR / Rank ICIR | 越高越好 | IC 均值 / IC 标准差 |
| Strategy Performance | IR | 越高越好 | 多空组合信息比率 |
| Strategy Performance | CR | 越高越好 | 累计收益 / 最大回撤绝对值 |
| Strategy Performance | ARR(%) | 越高越好 | 年化收益率 |
| Strategy Performance | MDD(%) | 越低越好 | 最大回撤 |

硬性要求：

- 不允许未来函数：`t` 日因子只用 ≤ t-1 形成、≤ t 可观测的席位净持仓与行情。
- 回测收益使用 Method A：`t` 日主力同一合约的 `t+1 close / t close - 1`，换月价差不计入。
- MVP 研究口径不计手续费、滑点、保证金占用；可交易口径显式加 data_lag=1、换月 5bps、交易 5bps。

## 使用方式

在开发产物目录下执行：

```bash
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

运行前设置 `PANDA_DATA_USERNAME` 和 `PANDA_DATA_PASSWORD`。可选 `PANDA_DATA_START_DATE` / `PANDA_DATA_END_DATE` / `PANDA_DATA_UNDERLYING`。

离线开发时可运行单测验证纯逻辑：`python -m pytest tests/ -v`（11 项）。

## Agent 执行规则

1. 先运行 `scripts/factor.py`，确认 Panda data 返回真实数据，因子结果非空且每日 universe ≤ 10。
2. 再运行 `scripts/validate.py`，确认无未来函数（截断法检验）、字段完整、取值范围合法、家人席位齐全、跨年份样本外可用。
3. 最后运行 `scripts/backtest.py`，输出研究口径（IC/ICIR/RankIC/RankICIR/IC_p/Bootstrap CI/多周期 IC 衰减/ARR/MDD/CR/多空收益/换手率/成本敏感性）与可交易口径（tradeable_ARR/tradeable_IR）。
4. 任一步失败必须报告失败命令、错误信息和数据日期，不得进入生产。

## 成功标准

- `factor.py` 输出非空，含 12 个必需字段，每日 universe ≤ 10。
- `validate.py` 输出「验证通过」并退出码 0。
- `backtest.py` 输出研究口径与可交易口径两组指标。
- 数据来源为 Panda data SDK，`data_version` 为 `real-v1`。

## 与生产产物的关系

开发产物用于计算、验证和回测；生产查询时使用 `alpha-f6-v2-family-timing-reverse-production`，不临时重算。

## 验收要求

- 不允许未来函数。
- 必须有样本外验证。
- 必须有回测指标。
- 必须使用 Panda data 实现。
- 不通过验证不得进入生产。

## 依赖

- Python 3.10+
- panda-data
- pandas
- scipy
- pyarrow 或 fastparquet
