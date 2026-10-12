# P0a 设计：信号结算分维度切片 + 周度时间序列存档

> 自进化框架 P0a（第一阶段第一步）
> 依据：《基于 DeepSeek Harness 的 Agent 自进化框架研究.md》第 5 节「执行回路 × 改进回路」+ 第 6 节 G8「版本化生效与回滚」
> 目标：把"体检式"结算升级为"训练式"结算——让结算器产出**分维度的可比指标序列**，为 gap_analysis（P0c）提供原料。
> 日期：2026-09-24 | 状态：**已实施（代码+测试+冒烟通过）**

## 一、背景与缺口定位

现有信号质量链路（`my_doc/每日复盘/harness/automation/`）：

```
signal_tracking.json/云库表 → lib/signal_quality.py (8项指标) → generate_quality_dashboard()
   → auto_signal_quality_weekly.md（每周三）→ reports/weekly/信号质量周报.md + OpenViking T1/T2 沉淀
```

三个结构性缺口（进化无法启动的根因）：

| # | 缺口 | 后果 |
|---|------|------|
| 1 | **账户级指标不支持按维度切片**：`calc_target_hit_rate`/`calc_direction_accuracy`/`calc_signal_expected_value` 等只接受"全部 settled"；仅 `calc_trigger_rate` 支持 priority | 无法回答"哪类信号拖后腿"——P1 操作命中率 vs 观察雷达命中率不可比 |
| 2 | **无结构化时间序列存档**：周报是 Markdown 文档，环比靠 LLM 读上一篇文档（易漂移、不可计算） | 没有"命中率曲线"，无法做趋势/差距分析 |
| 3 | **gap_analysis 无原料**（P0c 前置依赖） | 定向 REQ 无数据支撑，只能靠复盘随机发现 |

## 二、改造范围（纯增量，不动现有逻辑）

### 2.1 `lib/signal_quality.py` — 新增维度切片

新增纯函数 `dimension_dashboard(signals, settled, today='')`，**保留** `generate_quality_dashboard()` 原样（向后兼容）。

```python
def dimension_dashboard(signals, settled, today='') -> dict:
    """按维度切片的指标集，供差距分析（gap_analysis）使用。
    返回:
    {
      'date': today,
      'overall': {...指标集...},          # 全口径（与 dashboard 口径一致）
      'dimensions': {
        'priority':   {'P0': {...}, 'P1': {...}, 'P2': {...}},
        'source':     {'morning_analysis': {...}, ...},
        'trade_type': {'buy': {...}, 'sell': {...}},
      }
    }
    每个切片指标集 = { n_signals, n_settled, n_executed,
                       trigger_rate, target_hit_rate, direction_accuracy,
                       signal_expected_value, max_loss, avg_profit_loss_ratio,
                       simulated_count, simulated_pnl_amount }
    口径（REQ-006 保持一致）：账户级指标仅基于"已执行样本"；
    未执行模拟样本单独披露（simulated_*）。维度取值取"信号+已结算中实际出现的值"，
    排序稳定（按枚举顺序）。
    """
```

- 内部复用 `split_executed_simulated()` 与全部 `calc_*` 纯函数，不重复造轮子
- 维度键与 `docs/signal-enums.md` 一致：`priority` / `source` / `trade_type`

### 2.2 新增 `lib/signal_quality_history.py` — 周度快照存档

新增模块（可测试纯 IO），提供：

```python
DEFAULT_HISTORY_PATH = config/signal_quality_history.json

def save_weekly_snapshot(snapshot: dict, path=None) -> Path
    # 追加当周快照 {week_key, cohort_start, cohort_end, dashboard, dims, saved_at}
    # 幂等：同 week_key 重复保存 → 覆盖（重跑不产生重复周）
    # 原子写（临时文件 + replace）+ 损坏时 .bak 备份

def load_history(path=None) -> list[dict]
    # 读全部快照（按 week_key 排序），文件缺失/损坏返回 [] 并备份损坏文件

def recent_weeks(n: int, path=None) -> list[dict]
    # 最近 n 周快照（按 week_key 取最后 n 个），gap_analysis 直接消费
```

- `week_key` 用 cohort 周的 ISO 周（如 `2026-W37`），`cohort_start/end` 为周一/周五
- 存档含 `dashboard`（整份 `generate_quality_dashboard` 输出）+ `dims`（整份 `dimension_dashboard` 输出）——一次存档同时支撑趋势图与差距分析
- 文件位置：`automation/config/signal_quality_history.json`（与 signal_tracking.json 同目录，云库化前先本地）

### 2.3 `prompts/auto_signal_quality_weekly.md` — 周报任务改造

在现有步骤上增量追加（不改原有步骤）：

1. **计算维度切片**：`dimension_dashboard(week, settled)` 内联 Python 调用
2. **存档**：`save_weekly_snapshot(...)` 写入历史（幂等）
3. **周报新增「分维度指标表」**：按 priority / source / trade_type 三张子表渲染（样本数 + 命中率 + 方向准确率 + 期望价值），标注样本数 <3 的切片为"样本不足"
4. 保留原有：环比、P0 执行率、校准建议、T1/T2 经验沉淀

## 三、测试计划（TDD，先红后绿）

新增测试：
- `tests/test_signal_quality.py` 增加 `TestDimensionDashboard`：
  - 按 priority 切片：P1 与 P0 命中率不同且与全口径一致
  - 按 trade_type 切片：buy/sell 分组
  - 空输入返回空维度
  - 账户级指标只算已执行（模拟样本入 simulated_*）
  - 维度值只含实际出现的（无 P2 信号则不出现 P2 键）
- 新增 `tests/test_signal_quality_history.py`：
  - save → load 往返一致
  - 同 week_key 覆盖（幂等）
  - 不同 week_key 追加 + 排序
  - recent_weeks(n) 取最后 n 个
  - 损坏文件 → 备份 .bak + 返回 []（不崩溃）

## 四、验收标准

1. `python -m pytest tests/ -v` 全绿（新增 + 既有）→ **✅ 539 passed, 1 skipped（含新增 15 项）**
2. `generate_quality_dashboard` 行为不变（向后兼容，既有测试通过即证明）→ **✅ 既有 524 项全通过**
3. 手工冒烟：用当前 `signal_tracking.json` 跑一次 `dimension_dashboard`，输出三个维度的切片表 → **✅ 全库 23 信号/5 结算，三维切片正常**
4. 周报任务 prompt 更新后，下个周三（或手工触发）产出含维度表的周报 + 生成第一条历史快照 → **✅ 已用真实数据生成 2026-W38 首条历史快照并端到端验证存档链路**

**实施产物清单：**
- `lib/signal_quality.py`：新增 `dimension_dashboard()` / `_slice_metrics()` / `_dim_values()`（纯增量，`generate_quality_dashboard` 未动）
- `lib/signal_quality_history.py`：新增（`save_weekly_snapshot` / `load_history` / `recent_weeks`，原子写+幂等+损坏备份）
- `tests/test_signal_quality.py`：新增 `TestDimensionDashboard`（7 项）
- `tests/test_signal_quality_history.py`：新增（8 项）
- `prompts/auto_signal_quality_weekly.md`：新增"二·五分维度切片+历史存档"步骤 + 周报"分维度指标表"
- `config/signal_quality_history.json`：**已生成首条真实快照（2026-W38）**

**冒烟揭示的进化痛点（真实数据）：**
- 2026-W38：4 个已结算信号**全部为模拟样本（执行=0）**——印证 09-16 周报"执行率 0%"，P0 执行机制失效持续
- P0 触发率 33.3% < P1 66.7%（反直觉，P0 条件可能过严或标注问题）
- 早盘信号（morning_analysis）触发率 0%——**连续两周为 0**，稳定短板维度，是 gap_analysis 首个定向目标
- 全维度 `n_executed=0` → "信号生成→不执行"是当前系统最大病灶

## 五、后续衔接

- **P0c**：`gap_analysis` 读 `recent_weeks(4)` → 差距 = 目标(goals.md) − 现状 → 生成定向 REQ
- **P2**：REQ 加"关联指标/基线/观察期"，前后对比直接读历史快照
- 云库化：历史快照表 `signal_quality_weekly`（本地 JSON 先行，迁移逻辑参考 `migrate_signal_tracking.py`）

## 六、风险与回滚

- 改动全为**新增函数/新增文件**，不修改既有函数签名与行为 → 回滚 = 删除新增代码
- 历史文件写入用原子写 + .bak 备份，损坏不阻塞周报任务
- 若 `signal_tracking` 数据本身口径不全（如 source 缺失），切片表会显示"样本不足"，不阻断整体
