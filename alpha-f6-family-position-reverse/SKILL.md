---
name: alpha-f6-family-position-reverse
description: Use when developing, computing or validating the F6 commodity futures family-position reverse factor in a local Panda data environment.
license: GPL-3.0-only
tags: [quant, alpha, development, future]
---

# 家人仓位反向 Alpha

## 适用场景

- 计算商品期货 F6 家人仓位反向因子。
- 验证东方财富、徽商期货、平安期货等家人席位净仓位的反向截面信号。
- 生成商品期货截面 `buy` / `sell` / `hold` 候选信号。

## 因子逻辑

- 家人席位：`东方财富`、`徽商期货`、`平安期货`，按精确字符串匹配。
- 市场总规模：当日该品种所有席位 `abs(net_margin)` 之和（`total_margin`）。
- 家人净仓位：`family_margin = sum(net_margin for broker in FAMILY_BROKERS)`。
- 原始权重：`raw_weight = -family_margin / total_margin`。
- 因子值：横截面百分位映射到 `[-1, 1]`，`factor_value = rank_pct(raw_weight) * 2 - 1`（当日全品种截面，非时序）。
- 信号门槛：`rank <= ceil(n * 0.1)` -> buy；`rank > n - ceil(n * 0.1)` -> sell；其余 -> hold。
- 排序方向：`factor_value` 越大越好（rank=1 为最高）。

## 使用方式

```bash
python test.py
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

运行前需要设置 `PANDA_DATA_USERNAME` 和 `PANDA_DATA_PASSWORD`。可选设置 `PANDA_DATA_START_DATE`、`PANDA_DATA_END_DATE` 和 `PANDA_DATA_UNDERLYING`。

## 成功标准

- `test.py` 使用合成数据离线验证截面公式、无未来函数、回测可导入和可交易口径输出。
- `factor.py` 输出非空，包含 12 个必需字段，`factor_id=F6`，`data_version=real-v1`。
- `validate.py` 输出验证通过信息，且家人席位至少出现一家。
- `backtest.py` 输出研究口径和可交易口径两组指标，包含 1D-20D IC 衰减、Bootstrap IC 95% CI、成本四档分析和可交易 ARR/IR。
- 数据来源为 Panda data SDK，不读取本地文件作为正式输入。

## 边界

本 skill 仅用于研究和验证，不构成投资建议，不承诺收益，不代表任何平台或组织的官方背书。不得记录、提交或传播 Panda data 凭据。
