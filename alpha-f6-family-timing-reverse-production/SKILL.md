---
name: alpha-f6-v2-family-timing-reverse-production
description: 当需要读取家人择时反向（时序）Alpha 的生产计算结果时，使用此 skill。该 skill 只读取已生成的 Parquet 结果，不在调用时重新计算因子。
tags: [quant, alpha, production, future]
---

# 家人择时反向（时序）Alpha 生产结果

## 适用场景

- 当用户需要查询家人择时反向（时序）Alpha 最新结果时
- 当交易 agent 需要使用该因子辅助商品期货热门品种多空判断时

## 结果文件

- 文件路径：`database.parquet`
- 数据格式：Parquet
- 更新频率：每日收盘后
- 生成方式：开发产物 `scripts/factor.py` 通过验证后生成

## 主键

- `trade_date`
- `factor_id`
- `symbol`

## 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| trade_date | string | 交易日期，`YYYY-MM-DD` |
| asset_type | string | 固定为 `future` |
| symbol | string | 期货品种代码 |
| factor_id | string | 固定为 `F6_V2` |
| factor_name | string | 固定为 `家人择时反向` |
| factor_value | float | `-rollIC` 经 60 日时序 Z-score，无固定范围 |
| score | float | factor_value 的时序滚动百分位（自身历史），范围 `[0,100]` |
| rank | int | 当日热门 universe 内排名，1=最高（弱化字段，仅参考） |
| signal | float | 连续方向数值 `clip(factor_value,-3,3)`，`\|fv\|<0.5` 置 0 |
| confidence | float | `\|signal\| / 3`，范围 `[0,1]` |
| data_version | string | 固定为 `real-v1` |
| update_time | string | ISO8601 生成时间 |

## 读取规则

交易 agent 读取 `database.parquet`，筛选 `asset_type == "future"` 且 `factor_id == "F6_V2"`，优先使用最新有效交易日结果。若最新结果不存在，可回退最近有效交易日，但必须说明数据日期。该因子仅在每日热门 Top10 品种上有记录，非热门品种当日无行。

## 信号解释（数值方向）

- `signal > 0`：家人近期踩反（rollIC 偏负），反向看多；绝对值越大仓位越重。
- `signal < 0`：家人近期踩对（rollIC 偏正），反向看空。
- `signal = 0`：时序 Z 强度不足（`|factor_value| < 0.5`），观望。
- 仅在每日成交最热门的 Top10 品种上有信号，非热门品种无记录。

## 禁止行为

- 不允许在 agent 调用时重新拉取原始行情。
- 不允许在 agent 调用时重新计算因子。
- 不允许手工修改 Parquet 结果。
