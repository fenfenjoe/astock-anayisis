# 信号字段枚举值权威定义

> 用途：`每日信号` 生成/入库/前端下拉的**唯一枚举来源**。
> 实现落点：`my_doc/每日复盘/harness/automation/lib/signal_tracking.py` `validate_signal_record()` /
> `signal_tracking_cloud.py`（复用）→ `GET /api/signal-enums`。
> 变更本文件时，必须同步修改上述两处代码（或由代码反推本文档）。

## 枚举表

| 字段 | 存储值 | 前端显示映射 | 说明 |
|---|---|---|---|
| `trade_type` 操作类型 | `buy` / `sell` | 买入 / 卖出 | 生成严格用 buy/sell |
| `status` 状态 | `open` / `triggered` / `executed` / `partial_executed` / `settled` / `expired` | 未触发 / 已触发 / 已执行 / 部分执行 / 已结算 / 已过期 | **追踪库/云库用英文内部值**；markdown 显示层中文状态（未触发/已触发/已执行/已过期/已取消）映射：未触发→open、已触发→triggered、已执行→executed、部分执行→partial_executed、已过期→expired（v3.0 新增，盘中"触发后回落离开交易价"或"75%窗口过期"写入云库） |
| `direction` 方向 | `buy` / `sell` | 多 / 空 | 存储 buy/sell |
| `priority` 优先级 | `P0` / `P1` / `P2` | 同左 | |
| `urgency` 紧急度 | `high` / `low` | 高 / 低 | |
| `source` 来源 | `morning_analysis` / `intraday_check` / `evening_review` | 早盘/盘中/复盘 | |
| `outcome` 结果 | `hit` / `stopped` / `miss` | 命中/止损/未达标 | |

## 校验规则

- `trade_type` / `direction` / `priority` / `urgency` / `source` / `outcome` / `status` 必须 ∈ 上表；非法值抛 `ValueError`，入库中断（不落脏数据）。
- 数值字段（`trade_price` / `target_price` / `stop_price` / `entry_price` / `trigger_price` / `expected_trigger_rate` / `target_pct` / `stop_pct`）做类型规整为 float。
- 触发/回填语义：
  - `trade_price`（交易价）：信号生成时填写，= 触发条件里的关键执行价位（买入=计划买入价，卖出=计划卖出价）；v3.0 起所有信号必填，买入信号另必填 `target_price`/`stop_price`；
  - `trigger_price` / `trigger_time`：盘中分析记录触发价 / 触发时间（`HH:MM`）；
  - `entry_price` / `entry_time`：复盘分析关联"录入交易"记录买入价 / 买入时间。
- 状态流转（v3.0，盘中自动更新）：
  - 初始 = 未触发（`open`）；
  - 标的现价达交易价（买入现价≥交易价、卖出现价≤交易价）→ 已触发（`triggered`）；
  - 已触发后现价回落离开交易价且未执行（买入跌破/卖出升破）→ 已过期（`expired`）；
  - 75% 窗口过期（P0 豁免）→ 已过期（`expired`）。
