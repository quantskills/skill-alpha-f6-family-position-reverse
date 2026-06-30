---
name: alpha-f6-family-position-reverse-production
description: Use when reading the local F6 commodity futures family-position reverse factor parquet output without recomputing the factor.
license: GPL-3.0-only
tags: [quant, alpha, production, future]
---

# 家人仓位反向 Alpha 生产结果

## 适用场景

- 当用户需要查询家人仓位反向 Alpha 最新结果时。
- 当交易 agent 需要使用该因子辅助商品期货截面多空判断时。

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
| factor_id | string | 固定为 `F6` |
| factor_name | string | 固定为 `家人仓位反向` |
| factor_value | float | 截面百分位映射到 `[-1, 1]` |
| score | float | 截面百分位评分 `[0, 100]` |
| rank | int | 当日截面排名，1 为最高 |
| signal | string | `buy` / `sell` / `hold` |
| confidence | float | `score / 100` |
| data_version | string | 固定为 `real-v1` |
| update_time | string | ISO8601 生成时间 |

## 读取规则

交易 agent 读取 `database.parquet`，筛选 `asset_type == "future"` 且 `factor_id == "F6"`，优先使用最新有效交易日结果。若最新结果不存在，可回退最近有效交易日，但必须说明数据日期。

## 信号解释

- `buy`: 家人席位净空比例较高，反向看多。
- `sell`: 家人席位净多比例较高，反向看空。
- `hold`: 横截面处于中间区间。

## 禁止行为

- 不允许在 agent 调用时重新拉取原始行情。
- 不允许在 agent 调用时重新计算因子。
- 不允许手工修改 Parquet 结果。
- 不允许将结果表述为投资建议、收益承诺或官方背书。
