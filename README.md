# alpha-f6-family-position-reverse

商品期货家人择时反向（时序）Alpha（Factor ID: F6_V2）。在每日成交最热门的 Top10 品种上，滚动计算家人席位净持仓变化与下一期收益的相关系数（家人滚动 IC），取负、做时序 Z-score，输出连续方向数值信号。

## 目录结构

```
alpha-f6-family-timing-reverse/                开发产物（计算、验证、回测）
  scripts/
    factor.py       因子计算，输出 Parquet 结果
    validate.py     无未来函数检测、字段完整性验证
    backtest.py     IC/ICIR/ARR/MDD/多空收益等回测指标
  references/
    data_guide.md   数据源与字段说明、因子公式、信号规则

alpha-f6-family-timing-reverse-production/     生产产物（只读）
  database.parquet  每日收盘后更新的因子结果
  SKILL.md          生产 skill 说明

README.md           本文件
```

## 因子逻辑

- **核心因果链**：品种放量持续热门 → 赚钱效应吸引散户 → 家人席位高位追多 → 主力派发反转 → 散户套牢。「热门」是反向有效性的前提。
- **家人席位**：东方财富、徽商期货、平安期货（精确名称匹配）
- **热门 universe**：每日按近 20 日均成交额排序取 Top 10，滞后到 t-1，无未来函数；非 universe 品种不发信号
- **家人滚动 IC**：`rollIC(t,u) = corr(Δfamily[t-20:t-1], ret_fwd[t-20:t-1])`
- **固定反向**：`factor_raw = -rollIC`（家人是散户特征，长期应负相关）
- **时序标准化**：每品种独立 60 日滚动 Z-score（`min_periods=20`），不使用横截面
- **数值信号**：`signal = clip(factor_value, -3, +3)`，`|factor_value| < 0.5` 时置 0

## 与原 F6 的区别

| 维度 | F6 家人仓位反向 | F6_V2 家人择时反向（本因子） |
|------|----------------|------------------------------|
| 信息源 | 当日家人持仓占全市场比例（静态截面） | 家人持仓变化与下一期收益的滚动相关（动态择时） |
| universe | 全部品种 | 仅热门 Top 10 |
| 信号生成 | 横截面百分位排名 | 时序 Z-score 阈值 |
| signal | `buy/sell/hold` 字符串 | 连续方向数值 `clip(fv,-3,3)` |
| 性质 | 横截面因子 | 纯时序因子 |

## 信号解释

| signal | 含义 |
|--------|------|
| `> 0` | 家人近期踩反（rollIC 偏负），反向看多；绝对值越大仓位越重 |
| `< 0` | 家人近期踩对（rollIC 偏正），反向看空 |
| `= 0` | 时序 Z 强度不足（`\|factor_value\| < 0.5`），观望 |

仅在每日成交最热门的 Top10 品种上有信号，非热门品种无记录。

## 关键参数

| 参数 | 值 | 说明 |
|------|----|------|
| `FAMILY_BROKERS` | 东方财富 / 徽商期货 / 平安期货 | 家人席位，精确匹配 |
| `TOP_K` | 10 | 热门 universe 品种数 |
| `HOT_WINDOW` | 20 | 近 N 日均成交额（滞后 t-1） |
| `CORR_WINDOW` | 20 | 滚动相关系数窗口 |
| `ZSCORE_WINDOW` | 60 | 时序 Z-score 窗口 |
| `MIN_ZSCORE_PERIODS` | 20 | Z-score 最小样本 |
| `SIGNAL_THRESHOLD` | 0.5 | 进场 Z 阈值 |
| `SIGNAL_CLIP` | 3.0 | signal 裁剪范围 ±3 |
| `TURNOVER_MODE` | amount / vcm | 成交额口径，amount 优先，vcm 回退 |

## 数据源

使用 Panda data SDK，不读取本地表格作为正式输入。

| 接口 | 用途 |
|------|------|
| `get_broker_netmarg` | 席位净持仓保证金 |
| `get_future_dominant` | 每日主力合约映射 |
| `get_future_daily` | 主力合约日线（close / volume / amount） |
| `get_future_detail` | 合约乘数（TURNOVER_MODE=vcm 时使用） |

| 环境变量 | 说明 |
|----------|------|
| `PANDA_DATA_USERNAME` | 必填 |
| `PANDA_DATA_PASSWORD` | 必填 |
| `PANDA_DATA_START_DATE` | 可选，格式 `YYYY-MM-DD` |
| `PANDA_DATA_END_DATE` | 可选，格式 `YYYY-MM-DD` |
| `PANDA_DATA_UNDERLYING` | 可选，逗号分隔品种代码，留空表示全部 |

## 运行方式

```bash
cd alpha-f6-family-timing-reverse
python scripts/factor.py
python scripts/validate.py
python scripts/backtest.py
```

离线验证纯逻辑（无需数据连接）：

```bash
python -m pytest tests/ -v
```

## 输出字段

| 字段 | 说明 |
|------|------|
| `trade_date` | 交易日期 `YYYY-MM-DD` |
| `asset_type` | 固定 `future` |
| `symbol` | 期货品种代码 |
| `factor_id` | 固定 `F6_V2` |
| `factor_name` | 固定 `家人择时反向` |
| `factor_value` | `-rollIC` 经 60 日时序 Z-score，无固定范围 |
| `score` | factor_value 的时序滚动百分位（自身历史），`[0, 100]` |
| `rank` | 当日热门 universe 内排名，1=最高（弱化字段，仅参考） |
| `signal` | 连续方向数值 `clip(factor_value,-3,3)`，`\|fv\|<0.5` 置 0 |
| `confidence` | `\|signal\| / 3`，范围 `[0, 1]` |
| `data_version` | 固定 `real-v1` |
| `update_time` | ISO8601 生成时间 |

## 验收标准

- `factor.py` 输出非空，含 12 个必需字段，每日 universe ≤ 10，`factor_id=F6_V2`，`data_version=real-v1`
- `validate.py` 输出「验证通过」并退出码 0（无未来函数、字段完整、家人席位齐全、跨年份样本外可用）
- `backtest.py` 输出研究口径与可交易口径两组指标，含多周期 IC 衰减（1D-20D）、Bootstrap IC 95% CI、成本四档分析
- 不通过验证不得进入生产

## 生产查询

交易 agent 使用 `alpha-f6-v2-family-timing-reverse-production` skill 读取 `database.parquet`，筛选 `factor_id == "F6_V2"`，不在调用时重新计算因子。

## 依赖

- Python 3.10+
- panda-data
- pandas
- scipy
- pyarrow 或 fastparquet
