# Harness 测试基础设施与流程闭环设计

- **创建时间**: 2026-07-27
- **状态**: 已确认，待实施
- **关联 REQ**: REQ-001, REQ-002

## 一、问题诊断

每日复盘 harness 的 Steering 系统中，REQ-001（信号收益追踪）和 REQ-002（信号设计质量提升）均卡在 IMPLEMENTED 状态超过 3 天，无法推进到 CLOSED。根因是 **4 层流程设计缺陷**：

| 层面 | 问题 | 严重度 |
|------|------|--------|
| 基础设施缺失 | `my_doc/` 下无测试框架、测试目录、测试模板；隔壁 `etf-strategies/` 有完整 pytest 体系 | 高 |
| 流程执行漏洞 | `auto_req_implement.md` 第 3 步写了 TDD，但 REQ-001/002 通过 CHAT.md 内联实施，绕过了自动执行器的强制检查 | 高 |
| 修复机制缺失 | `auto_evening_review` 第 13 步能检测"无测试→卡 IMPLEMENTED"，但没有自动化任务去修复 | 中 |
| 首次暴露 | Steering 系统第一次有 REQ 走到 IMPLEMENTED，整个生命周期从未被完整走过 | 低 |

## 二、方案概述

采用 **中等力度：可提取逻辑测试** 策略。将嵌入在 prompt 中的 Python 逻辑提取为独立可测试模块，建立 pytest 测试框架，并在 3 个自动化 prompt 中增加 TDD 门禁与补测机制。

## 三、新增文件

```
my_doc/每日复盘/harness/automation/
├── lib/                                    # NEW: 可测试 Python 包
│   ├── __init__.py
│   ├── signal_tracking.py                  # REQ-001: P&L计算/结算规则/聚合统计
│   ├── signal_design.py                    # REQ-002: 窗口计算/紧急度排序/过期判定
│   └── state_machine.py                    # REQ状态机: 转换验证/测试门禁/滞留检测
├── tests/                                  # NEW: pytest 测试目录
│   ├── __init__.py
│   ├── conftest.py                         # 共享 fixtures（交易日历 mock、信号样本）
│   ├── test_REQ_001.py                     # 测试: signal_tracking.py + state_machine.py
│   ├── test_REQ_002.py                     # 测试: signal_design.py + state_machine.py
│   └── test_state_machine.py               # 测试: state_machine.py（流程门禁通用）
├── pytest.ini                              # NEW: pytest 配置
├── bugs/                                   # NEW: Harness 独立 BUG 跟踪系统
│   ├── BUG_INDEX.md                        #     BUG 索引（状态汇总+列表+巡检历史）
│   ├── BUG_TEMPLATE.md                     #     BUG 创建模板
│   ├── open/                               #     待修复 BUG
│   └── closed/                             #     已关闭 BUG
└── prompts/
    └── auto_bug_fix.md                     # NEW: Harness BUG 自动修复 prompt
```

### 命名约定

- 测试文件以 REQ 编号命名：`test_REQ_001.py`、`test_REQ_002.py`
- 每个测试文件头部注释标注被测源码文件和覆盖要点

## 四、lib/ 模块接口设计

### 4.1 `signal_tracking.py` — 信号收益追踪（REQ-001）

从 `auto_evening_review.md` §7.6 的嵌入式 Python 提取：

```python
# === P&L 计算 ===
def calc_buy_pnl(entry_price: float, exit_price: float, shares: int) -> float
def calc_sell_pnl(sell_price: float, cost_basis: float, shares: int) -> float
def calc_avoided_loss(sell_price: float, price_after_n_days: float, shares: int) -> float

# === 结算与归档判定 ===
def calc_settlement_date(trigger_date: date, urgency: str) -> date
    # urgency='high' → trigger_date + 2个交易日
    # urgency='low'  → trigger_date + 5个交易日
def is_archived(signal_date: date, current_date: date, archive_days: int = 90) -> bool

# === 聚合统计 ===
def update_aggregation(tracking: dict) -> dict
    # 输入 signal_tracking.json 的完整 dict
    # 重算 by_urgency / by_priority / by_trade_type / by_ticker
    # 返回更新后的 dict（不写磁盘）

# === 信号结算 ===
def settle_signal(signal: dict, current_price: float) -> dict
    # 填充 pnl / avoided_loss / settled_date / status='settled'

# === Schema 校验 ===
def validate_signal_record(signal: dict) -> list[str]
    # 返回缺失/非法字段列表，空列表=合法
```

### 4.2 `signal_design.py` — 信号设计质量（REQ-002）

从 `早盘分析-模板.md` 规则 1-4 + `盘中分析-模板.md` 过期逻辑提取：

```python
# === 时间窗口计算 ===
def calc_window_milestones(start: datetime, end: datetime) -> dict
    # → {"pct50": datetime, "pct75": datetime, "total_minutes": int}

# === 50%窗口自检 ===
def is_price_reachable(current: float, target: float,
                       remaining_minutes: int,
                       daily_volatility_pct: float = 3.0) -> bool

# === 75%强制过期 ===
def should_expire(signal: dict, current_time: datetime) -> bool
    # P0信号 → False（豁免）

# === 紧急度排序 ===
def sort_by_urgency(signals: list[dict]) -> list[dict]
    # 高+P0 > 高+P1 > 低+P1 > 低+P2

# === 规则存在性检查 ===
def check_main_backup_paths(signal: dict) -> tuple[bool, str]
def generate_graded_thresholds(strict: dict) -> dict
```

### 4.3 `state_machine.py` — 状态机与流程门禁

```python
VALID_TRANSITIONS = {
    'OPEN':        ['IN_PROGRESS', 'REJECTED'],
    'IN_PROGRESS': ['IMPLEMENTED', 'OPEN', 'REJECTED'],
    'IMPLEMENTED': ['CLOSED', 'IN_PROGRESS', 'REJECTED'],
    'CLOSED':      [],
    'ADOPTED':     [],
    'REJECTED':    [],
}

def validate_transition(from_status: str, to_status: str) -> tuple[bool, str]
def check_test_exists(req_id: str, tests_dir: str) -> bool
def run_tests(req_id: str, tests_dir: str) -> tuple[bool, str]
def tdd_gate_check(req_id: str, tests_dir: str) -> dict
def detect_stuck(req_index: list[dict], tests_dir: str) -> list[dict]
```

## 五、流程修改（5 个文件）

### 5.1 `auto_req_implement.md` — 新增第 3.5 步"TDD 门禁"

插入在第 3 步（TDD）和第 4 步（executing-plans）之间：

```
### 第3.5步 — TDD 门禁（强制）

**在代码实施完成后、推进到 IMPLEMENTED 之前执行：**

1. 检查 harness/automation/tests/test_{REQ-ID}.py 是否存在
   - 不存在 → 实施不完整，回退到 IN_PROGRESS，输出"缺少测试文件"
2. 运行 python -m pytest harness/automation/tests/test_{REQ-ID}.py -v --tb=short
   - 失败 → 修复代码或测试，最多 3 轮
   - 3 轮后仍失败 → 回退到 IN_PROGRESS，追加处理记录"TDD门禁失败"
3. 通过 → 继续推进到 IMPLEMENTED

铁律：没有通过 TDD 门禁的 REQ 不得标记为 IMPLEMENTED。
```

### 5.2 `auto_evening_review.md` — 第 13.3 步增强

```
13.3 判定：
  - 运行 pytest harness/automation/tests/test_{REQ-ID}.py
  - 测试通过 + 复盘数据确认效果 → CLOSED
  - 测试通过但效果不明确 → 保持 IMPLEMENTED，追加观察备注
  - 测试失败或效果为负 → 保持 IMPLEMENTED，创建 BUG
  - 无测试文件 → 保持 IMPLEMENTED，自动创建补测子 REQ 写入 steering/open/
    （REQ-{NNN}-TEST，标题"补测: {原标题}"，优先级继承原 REQ）
```

### 5.3 `auto_experience_health.md` — 第五(B)步新增

```
(C) IMPLEMENTED 无测试滞留检测:
  - 扫描所有 IMPLEMENTED REQ，检查 tests/test_{REQ-ID}.py 是否存在
  - 无测试且停留 > 3 交易日 → 告警 + 建议手动处理
  - 无测试且停留 > 7 交易日 → 自动创建补测子 REQ
```

### 5.4 `auto_bug_fix.md` — NEW: Harness BUG 自动修复 prompt

新建 `harness/automation/prompts/auto_bug_fix.md`，结构与 `etf-strategies/automation/prompts/bug_auto_fix.md` 一致，但作用于 harness 项目：

```
Harness BUG 自动修复流程：

第0步 — 扫描:
  - 读取 harness/automation/bugs/BUG_INDEX.md
  - 过滤 OPEN 状态且 auto_fix_eligible=true 的 BUG
  - MANUAL_REVIEW BUG 仅报告不处理

第1步 — 诊断:
  - 读取 BUG 文件，理解预期行为 vs 实际行为
  - 定位受影响的源文件

第2步 — 修复:
  - 走 superpowers 流程：systematic-debugging → TDD → 修复
  - 确定性修复可直接修改
  - 涉及金融计算 → 标记 MANUAL_REVIEW，跳过自动修复

第3步 — 回归测试（强制）:
  - python -m pytest harness/automation/tests/ -v --tb=short
  - 全量通过 → 继续
  - 失败 → 回滚 + 标记 MANUAL_REVIEW

第4步 — 归档:
  - BUG 状态 → FIXED
  - 更新 BUG_INDEX.md
  - BUG 文件移入 closed/
  - 写入修复日志
```

### 5.5 `task_schedule.json` — 新增调度条目

在 `tasks` 数组中新增 `harness_bug_auto_fix` 任务（详细定义见 §8.9）。同时现有 `bug_auto_fix` 任务不变，两者独立运行。

## 六、REQ_TEMPLATE.md 修改

新增"测试交付物清单"必填节（在"期望结果"和"约束/注意事项"之间）：

```markdown
## 测试交付物

- [ ] 测试文件: `harness/automation/tests/test_REQ-{NNN}.py`
- [ ] 被测模块: `harness/automation/lib/{模块名}.py`（如适用）
- [ ] TDD 门禁通过: `python -m pytest harness/automation/tests/test_REQ-{NNN}.py -v`
- [ ] 回归测试: 全量 `python -m pytest harness/automation/tests/ -v` 通过
```

## 七、测试策略

### 7.1 `test_REQ_001.py`（~15 条）

| 被测函数 | 测试用例 |
|---------|---------|
| `calc_buy_pnl` | 正收益 / 负收益 / 零收益 / 大额 shares |
| `calc_sell_pnl` | 卖价>成本（赚钱卖出）/ 卖价<成本（亏损卖出） |
| `calc_avoided_loss` | 卖出后上涨（避免了损失）/ 卖出后下跌（没避免） |
| `calc_settlement_date` | 高紧急度=2交易日 / 低紧急度=5交易日 / 跨周末 |
| `is_archived` | 恰好 90 天 / 91 天 / 89 天 |
| `settle_signal` | 买入信号完整结算 / 卖出信号完整结算（含 avoided_loss） |
| `update_aggregation` | 空库 / 单信号 / 多信号多维度 / 汇总一致性 |
| `validate_signal_record` | 完整合法 / 缺失 entry_price / 非法 urgency 值 |

### 7.2 `test_REQ_002.py`（~15 条）

| 被测函数 | 测试用例 |
|---------|---------|
| `calc_window_milestones` | 4h 窗口 / 1h 窗口 / 跨午休窗口 |
| `is_price_reachable` | 距离 1% 剩 30min（可到达）/ 距离 5% 剩 5min（不可到达） |
| `should_expire` | P0 不触发 / 非 P0 在 75% 前 / 非 P0 在 75% 后 / 恰好 75% |
| `sort_by_urgency` | 混合排序 / 同紧不同优 / 同优不同紧 |
| `check_main_backup_paths` | 有备选 / 无备选 / 备选路径为空字符串 |
| `generate_graded_thresholds` | 严格版字段完整 / 宽松版价格递减 / 宽松版量递减 |

### 7.3 `test_state_machine.py`（~10 条）

| 被测函数 | 测试用例 |
|---------|---------|
| `validate_transition` | 全部合法路径 / 非法 IMPLEMENTED→OPEN / 终态不可转出 |
| `check_test_exists` | 文件存在 / 文件不存在 / REQ-ID 带连字符 |
| `tdd_gate_check` | 测试存在且通过 / 存在但失败 / 不存在 |
| `detect_stuck` | 空列表 / 1 个滞留 / 多个滞留 / 无滞留（有测试） |

## 八、测试发现问题的处理流程

测试的价值不仅在"通过"，更在"发现偏差"。本节定义测试失败时的完整处理链路。

### 8.1 四种失败场景与路由

```
测试失败
  ├── 场景S1: TDD门禁阶段失败
  │     时机: auto_req_implement 第3.5步
  │     表现: 新写的测试不通过
  │     路由: 就地修复（未标记IMPLEMENTED，仍在实施阶段）
  │
  ├── 场景S2: 回归测试发现退化
  │     时机: 任意 pyteset 全量运行
  │     表现: 之前通过的测试现在失败
  │     路由: 创建 BUG → bug_auto_fix 认领
  │
  ├── 场景S3: 复盘验证阶段失败
  │     时机: auto_evening_review 第13.3步
  │     表现: IMPLEMENTED→CLOSED 时测试不通过
  │     路由: 退回 IN_PROGRESS + 创建 BUG
  │
  └── 场景S4: 补测发现既有bug ★
        时机: 为已 IMPLEMENTED 的 REQ 补写测试时
        表现: 测试写对了但代码行为不符合 REQ 期望
        路由: 就地修复 + REQ 追加处理记录（不退回状态）
```

### 8.2 场景 S1：TDD 门禁阶段失败

**触发条件**：`auto_req_implement` 第 3.5 步运行 `pytest test_REQ_{id}.py` 返回非零。

**处理流程**：

```
测试失败
  → Step 1: 分类诊断（判断是测试错了还是代码错了）
      - 对照 REQ 文档的期望结果，确认哪个才是正确的
      - 测试断言错误 → 修测试，不修代码
      - 代码行为错误 → 修代码，不修测试
  → Step 2: 修复（最多 3 轮）
      - 每轮修复后重跑测试
      - 在 REQ 处理记录中追加"TDD门禁第N轮修复: {问题} → {修复}"
  → Step 3: 判定
      - 3 轮内通过 → 继续推进到 IMPLEMENTED
      - 3 轮后仍失败 → 回退到 IN_PROGRESS，处理记录追加"TDD门禁失败: {最终状态}"
        → 同时创建 BUG 到 harness/automation/bugs/open/
        → 按 BUG_TEMPLATE.md 模板创建 BUG-{NNN}.md
        → 标题: "[REQ-{id}] TDD门禁失败: {简要描述}"
        → 等待下一轮 harness_bug_auto_fix 或手动处理
```

**诊断辅助**：在测试失败输出中，`auto_req_implement` 须打印：
- 哪个测试函数失败
- 期望值 vs 实际值
- 对照的 REQ 需求原文（从 REQ 文件"期望结果"节提取）
- 初步分类建议（"疑似代码问题" / "疑似测试断言错误"）

### 8.3 场景 S2：回归测试发现退化

**触发条件**：任何触发全量测试的场景（bug_auto_fix 回归验证、auto_evening_review 第 13 步全量运行、手动 `pytest`）中，之前通过的测试现在失败。

**处理流程**：

```
已通过测试突然失败
  → Step 1: 定位退化源
      - 用 git diff 找出 harness/ 下最近变更
      - 对照变更确定是哪个改动导致测试失败
  → Step 2: 创建 BUG
      - 写入 harness/automation/bugs/open/BUG-{NNN}.md
      - 标题: "[回归] test_REQ_{id}::{test_name} 失败: {简要}"
      - 内容: 粘贴失败输出 + git bisect 指向的可疑 commit
  → Step 3: 紧急判定
      - 影响主流程（如 P&L 计算错误）→ P0，立即修复
      - 影响辅助功能（如聚合统计显示）→ P1
      - 仅影响边界情况 → P2
  → Step 4: bug_auto_fix 认领 + 修复
  → Step 5: 修复后全量回归通过
```

**与现有 BUG 系统的对接**：退化 BUG 写入 `harness/automation/bugs/open/`，由 `harness_bug_auto_fix` 调度任务（每小时 :17）自动认领和修复。这与 CLAUDE.md §7.2 中 bug_auto_fix 的调度一致。

### 8.4 场景 S3：复盘验证阶段失败

**触发条件**：`auto_evening_review` 第 13.3 步运行 IMPLEMENTED REQ 的测试，测试不通过。

**处理流程**：

```
IMPLEMENTED REQ 测试不通过
  → Step 1: 区分失败原因
      - 测试失败 + 复盘数据也确认效果为负 → 实现有 bug，创建 BUG
      - 测试失败 + 复盘数据显示效果正常 → 测试可能过于严格，标记待校准
      - 测试通过 + 但复盘数据显示效果为负 → 测试覆盖不足，追加测试用例
  → Step 2: 路由
      - 有 BUG → REQ 退回到 IN_PROGRESS，处理记录追加"复盘验证失败，BUG-{NNN}"
      - 测试待校准 → 保持 IMPLEMENTED，处理记录追加"测试需校准: {具体问题}"
      - 覆盖不足 → 保持 IMPLEMENTED，处理记录追加"需追加测试用例: {缺口}"
  → Step 3: 创建 BUG（如适用）
      - 写入 harness/automation/bugs/open/
      - 在 BUG 中引用 REQ 编号，形成 REQ↔BUG 双向链接
```

**关键原则**：复盘验证是 Generator-Evaluator 分离的最后一道防线。测试失败 + 复盘数据交叉验证 = 双重确认问题真实存在，必须修复后才能 CLOSED。

### 8.5 场景 S4：补测发现既有 bug ★（当前 REQ-001/002 最可能触发）

**触发条件**：为已 IMPLEMENTED 但缺少测试的 REQ 补写测试时，测试按 REQ 期望结果编写正确，但代码实际行为不符。**这是 REQ-001 和 REQ-002 当前面临的核心场景。**

**处理流程**：

```
补写测试 → 测试失败 → 代码行为 ≠ REQ 期望
  → Step 1: 三重确认（防止测试本身写错）
      ① 对照 REQ 文档"期望结果"节逐条核对
      ② 对照实现代码（prompt中的Python片段）确认实际行为
      ③ 判断偏差方向：
         - 代码行为正确，REQ期望写错了 → 更新 REQ 期望结果
         - REQ期望正确，代码实现有 bug → 进入 Step 2
         - 两者都合理但语义不同 → 标记为"设计歧义"，人工裁决
  → Step 2: 就地修复代码
      - 在 REQ 处理记录中追加"补测发现Bug: {问题描述}"
      - 修复 prompt 中的 Python 片段或 lib/ 中的函数
      - 重跑测试 → 通过
  → Step 3: 判定是否需要创建独立 BUG
      - Bug 影响范围仅限于本 REQ → 仅在 REQ 处理记录中记载，不单独创建 BUG
      - Bug 影响其他 REQ 或主流程 → 创建独立 BUG（符合场景 S2 路由）
  → Step 4: 测试通过后继续推进到 CLOSED
      - REQ 状态保持 IMPLEMENTED（不退回，因为是补测发现的微调）
      - 处理记录追加: "补测通过，修复 {N} 个 bug，可推进 CLOSED"
```

**REQ-001 补测高风险点**（最可能暴露 bug 的函数）：
- `calc_avoided_loss` — 卖出信号避免损失计算符号方向容易搞反
- `calc_settlement_date` — 跨周末/节假日的交易日计数容易出错
- `update_aggregation` — 多维度聚合的汇总一致性（各维度之和=total）

**REQ-002 补测高风险点**（最可能暴露 bug 的函数）：
- `should_expire` — 75% 窗口刚好命中边界时的取舍（`>=` vs `>`）
- `sort_by_urgency` — 同紧不同优、同优不同紧的排序稳定性
- `is_price_reachable` — 波动率估算在极端值下的合理性

### 8.6 测试本身有问题的处理

测试不是不可质疑的。以下情况应修改测试而非代码：

| 情况 | 判定标准 | 处理 |
|------|---------|------|
| 断言过于严格 | 测试要求 `== 0.0` 但允许 ±0.01 是合理的 | 修改断言为 `abs(x) < 0.01` |
| 期望值基于错误理解 | 对照 REQ 文档后发现测试写错了业务规则 | 修正测试，在 commit message 中注明纠正的业务理解 |
| 测试依赖不稳定数据 | 测试用了真实日期 `date.today()` 导致跨日失败 | 改为固定日期或 fixture 注入 |
| 测试覆盖了未承诺行为 | 测试断言了 REQ 未要求的内部实现细节 | 删除该测试或标记为 `@pytest.mark.internal` |

**铁律**：修改测试前必须在 REQ 处理记录中写清楚"为什么测试错了、正确的是什么"。不允许为了让测试通过而降低断言标准（如把 `==` 改成 `≈` 而不解释容忍度来源）。

### 8.7 闭环总结

```
          测试编写
              │
              ▼
    ┌─── pytest 运行 ───┐
    │                    │
    ▼                    ▼
  通过                  失败
    │                    │
    ▼                    ▼
  推进状态          分类诊断(S1-S4)
                        │
              ┌─────────┼─────────┐
              ▼         ▼         ▼
          测试错了   代码错了   设计歧义
              │         │         │
              ▼         ▼         ▼
          修正测试   修复代码   人工裁决
              │         │         │
              └────┬────┘         │
                   ▼              │
              pytest 重跑        │
                   │              │
              ┌────┴────┐        │
              ▼         ▼        │
            通过      仍失败      │
              │      (第N轮)     │
              ▼         │        │
          推进状态  创建BUG      │
                      │         │
                      ▼         ▼
                 harness_bug_auto_fix  写入REQ处理记录
```

所有测试失败——无论哪种场景——最终只有三种出口：**测试通过推进状态**、**创建 BUG 交 harness_bug_auto_fix**、**写入 REQ 处理记录标记为已知问题**。不允许静默忽略。

### 8.8 Harness 独立 BUG 跟踪系统

Harness 测试发现的 BUG 全部路由到自身 `bugs/` 目录，不跨项目。

**目录结构**：

```
harness/automation/bugs/
├── BUG_INDEX.md          # BUG 索引（状态汇总 + 列表 + 巡检历史 + 修复分支索引）
├── BUG_TEMPLATE.md       # BUG 创建模板（对标 etf-strategies 的 BUG 模板格式）
├── open/                 # 待修复 BUG
└── closed/               # 已关闭 BUG
```

**BUG 状态机**：

```
OPEN → IN_PROGRESS → FIXED → VERIFIED → (归档 closed/)
  ↓         ↓          ↓
WONT_FIX  MANUAL_REVIEW  (直接到 VERIFIED)
```

**BUG 模板字段**（对标 etf-strategies 格式）：
- 组件：`lib/` | `tests/` | `prompts/` | `templates/` | `config/`
- 严重程度：P0(紧急) | P1(高) | P2(中) | P3(低)
- 违反的正确性定义（如有）
- auto_fix_eligible：是否适合自动修复（确定性修复=true，涉及金融计算=false → MANUAL_REVIEW）
- 发现时间 / 发现方式
- 预期行为 vs 实际行为
- 复现步骤
- 受影响文件
- 潜在影响
- 建议修复

**关键规则**：
- 涉及金融计算公式/信号逻辑/策略判断的 BUG → `auto_fix_eligible: false` → 标记 `MANUAL_REVIEW` → BUG_INDEX 中列入待人工审核表
- 纯代码/配置/测试断言错误 → `auto_fix_eligible: true` → `harness_bug_auto_fix` 自动处理
- BUG 中引用来源 REQ 编号，REQ 处理记录中引用 BUG 编号，形成双向链接

### 8.9 调度任务新增：`harness_bug_auto_fix`

在 `.claude/scripts/task_schedule.json` 中新增一条调度任务：

```json
{
  "task_id": "harness_bug_auto_fix",
  "hourly": true,
  "target_minute": 17,
  "hourly_range": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
  "days_of_week": [0, 1, 2, 3, 4],
  "trading_day_required": false,
  "prompt_file": "my_doc/每日复盘/harness/automation/prompts/auto_bug_fix.md",
  "window_minutes": 7,
  "description": "Harness BUG自动修复 (每小时 :17)"
}
```

**设计决策**：
- **与 etf-strategies bug_auto_fix 错开 10 分钟**（etf :07，harness :17），避免两个自动修复任务在同一个 7 分钟窗口内争抢上下文
- **不合并到同一个 prompt**：两个项目的 BUG 跟踪完全独立，合并会增加 prompt 复杂度且违反"厨房与菜分离"的架构原则
- **非交易日也运行**：BUG 修复不需要交易时段，工作日即可
- `auto_bug_fix.md` 的 Prompt 结构与 etf-strategies 的 `bug_auto_fix.md` 一致：扫描 `harness/automation/bugs/open/` → 判定 auto_fix_eligible → superpowers 修复 → 回归测试（必须包含 `python -m pytest harness/automation/tests/ -v`）→ 更新 BUG_INDEX → 移入 closed/

### 8.10 全量回归测试触发点

以下自动化任务均需在完成后运行全量回归测试：

| 触发任务 | 运行时机 | 范围 |
|---------|---------|------|
| `harness_bug_auto_fix` | 每次 BUG 修复后 | `pytest harness/automation/tests/ -v` |
| `auto_req_implement` | 第 3.5 步 TDD 门禁 | `pytest harness/automation/tests/test_REQ_{id}.py -v` |
| `auto_evening_review` | 第 13.3 步 CLOSED 验证 | `pytest harness/automation/tests/ -v`（全量） |
| `auto_experience_health` | 第五(C)步滞留检测后 | `pytest harness/automation/tests/ -v --tb=line`（快速模式） |

## 九、边界条件与兼容性

- `lib/` 只做**纯计算**，不读写磁盘、不调 a-stock-data、不修改 prompt
- `auto_evening_review.md` §7.6 的 Python 脚本改为 `from lib.signal_tracking import ...`，逻辑不重复
- `trading_calendar.py` 被 `calc_settlement_date` 导入，复用现有交易日判断
- `pytest.ini` 独立配置，不与 `etf-strategies/pytest.ini` 冲突
- 测试使用合成数据，不依赖真实行情
- `signal_tracking.json` 的写入仍在 prompt 中执行（lib 只做纯计算，保证 prompt 对数据的控制权）

## 十、不修改的文件

以下文件保持原样，不做任何改动：

- `早盘分析-模板.md` — 规则描述保留，lib 提取其逻辑但不删除原文
- `盘中分析-模板.md` — 同上
- `复盘分析-模板.md` — 同上
- `signal_tracking.json` — 数据文件，schema 不变
- `task_state.json` — 数据文件，schema 不变
- `trading_calendar.py` — 被导入但不修改
- `CLAUDE.md` — 待全部实施完成后统一更新（在 finishing-a-development-branch 阶段）
