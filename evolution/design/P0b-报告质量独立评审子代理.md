# P0b 设计：报告质量独立评审子代理

> 自进化框架 P0b（第一阶段第二步）
> 依据：《基于 DeepSeek Harness 的 Agent 自进化框架研究.md》第 5 节（Generator-Evaluator 分离）+ 用户决策「报告质量分全部由独立评审子代理打分」
> 目标：把"生成者自评"升级为"独立只读评审者打分"，产出**可比的报告质量分数序列**（结算器升级）。
> 日期：2026-09-24 | 状态：**已实施（代码+测试+冒烟通过）**

## 〇、实施结果

**验收标准达成：**
1. 全量测试 **557 passed, 1 skipped**（含新增 18 项 P0b）✅
2. `auto_evening_review.md` 第十三步行为不变（仅加职责声明，生成者自检仍执行）✅
3. 手工冒烟：用 20260922 复盘报告（28KB，316 行）走通"评分→存档→读取→周度聚合"全链路 ✅
4. 调度任务已注册（`task_schedule.json` 19 个任务，17:20 无冲突）✅

**实施产物清单：**
- `lib/report_quality.py`：新增（validate_score / parse_score_markdown / save_report_score / load_scores / recent_scores / weekly_report_quality）
- `tests/test_report_quality.py`：新增（18 项）
- `prompts/auto_report_quality_review.md`：新增只读评审 prompt（四维评分表 + 只读铁律 + JSON 输出 + 缺失保护）
- `scripts/task_schedule.json`：新增 `report_quality_review`（交易日 17:20）
- `prompts/auto_evening_review.md`：第十三步加 Generator-Evaluator 职责声明
- `config/report_quality_history.json`：**已生成首条真实质量分（2026-09-24，total 15）**

**冒烟观察（20260922 复盘报告）：** 数据时点标注/Generator-Evaluator 三节/T2 验证/审阅节齐全，质量较高（模拟评审 15/20）。

## 一、背景与缺口

现有链路：`auto_evening_review.md` 第十三步「报告审阅（2-3轮自检）」在**复盘任务内部**执行——生成者自己审自己的报告。

三个问题（与 P0a 同构）：

| # | 缺口 | 后果 |
|---|------|------|
| 1 | **Generator-Evaluator 未分离**：审阅在生成进程内完成，同一上下文，无法独立找茬 | 自产自评，盲区难暴露（报告审阅经验.md 已记载"同一 AI 既写又查，写错必然查不出"） |
| 2 | **无分数产出**：第十三步只"发现问题→修正"，不产生结构化质量分 | 没有质量曲线，无法做趋势/差距分析 |
| 3 | **无历史存档**：质量无时间序列 | gap_analysis 无报告质量维度的原料 |

## 二、设计

### 2.1 总体架构（进程级分离）

```
生成侧（执行者）                        评估侧（结算器）
auto_evening_review（15:52）            report_quality_review（17:20，独立任务）
  └─ 第十三步：生成者自检（保留）          └─ 只读评审子代理（headless 独立进程）
      修正报告质量（第一道防线）              读：复盘报告.md + 报告审阅经验.md + 评分表
      不产分数                              写：四维分数 JSON → report_quality_history.json
```

- **进程级分离**：独立 headless 进程（零上下文共享），评审者看不到生成者的思考过程
- **只读**：评审 prompt 只允许读文件，禁止写/改报告——它只能"看"不能"动"
- **评分表**：四维 0-5 分（数据校验/逻辑一致性/完整性/格式），总分 20，锚点来自 `报告审阅经验.md`

### 2.2 `lib/report_quality.py`（纯函数，可测试）

```python
SCORE_DIMENSIONS = ['data_validation', 'logic_consistency', 'completeness', 'format']
MAX_PER_DIM = 5

def validate_score(score: dict) -> dict
    # 校验/规整分数：四维必填、0-5 范围、总分=求和；非法抛 ValueError

def parse_score_markdown(md_text: str) -> dict
    # 从评审子代理输出的 JSON 代码块中解析分数（容忍 markdown 包裹）

def save_report_score(score: dict, path=None) -> Path
    # 存档：{date, report_path, scores: {...}, total, issues: [...], reviewer_model, scored_at}
    # 幂等：同 date 覆盖；原子写 + .bak 备份

def load_scores(path=None) -> list
def recent_scores(n, path=None) -> list
def weekly_report_quality(scores: list, week_start: str, week_end: str) -> dict
    # 周度聚合：四维均值 + 总分均值 + 样本数（gap_analysis 消费）
```

### 2.3 `config/report_quality_history.json`（存档）

```json
[
  {
    "date": "2026-09-24",
    "report_path": "my_doc/每日复盘/reports/20260924/复盘报告.md",
    "scores": {"data_validation": 4, "logic_consistency": 3, "completeness": 4, "format": 5},
    "total": 16,
    "issues": [{"severity": "high", "dimension": "logic_consistency", "desc": "..."}],
    "reviewer_model": "deepseek-v4-flash",
    "scored_at": "2026-09-24T17:20:00"
  }
]
```

### 2.4 调度任务 `report_quality_review`（task_schedule.json 新增）

```json
{
  "task_id": "report_quality_review",
  "target_time": "17:20",
  "days_of_week": [0, 1, 2, 3, 4],
  "trading_day_required": true,
  "prompt_file": "my_doc/每日复盘/harness/automation/prompts/auto_report_quality_review.md",
  "window_minutes": 7,
  "description": "报告质量独立评审 (每日17:20)"
}
```

- 17:20 = 复盘（15:52）完成后 + logic_inspect（17:07）之后，不冲突
- `trading_day_required: true`：非交易日无复盘报告，跳过

### 2.5 `prompts/auto_report_quality_review.md`（只读评审 prompt）

核心约束：
1. **只读**：只允许 `read` 复盘报告.md + 报告审阅经验.md + 评分表；**禁止**任何写/改/执行命令
2. **四维评分**：按评分表锚点逐维打分（0-5 整数）
3. **问题清单**：每个问题标注维度 + 严重级（high/medium/low）+ 描述
4. **JSON 输出**：按 `lib/report_quality.py` 的 schema 输出到 stdout 的代码块，并调 `save_report_score` 存档
5. **样本不足保护**：报告缺失/为空 → 不评分，记录 skipped 并退出（不伪造分数）

### 2.6 复盘第十三步降级（最小改动）

`auto_evening_review.md` 第十三步标题下加一句：
> 本节为**生成者自检**（修正报告质量，不产分数）；质量分由独立任务 `report_quality_review`（17:20）产出，二者职责分离（Generator-Evaluator）。

## 三、测试计划（TDD）

新增 `tests/test_report_quality.py`：
- `validate_score`：合法通过 / 缺维度抛错 / 越界抛错 / 总分计算
- `parse_score_markdown`：裸 JSON / 带 ```json 包裹 / 非法 JSON 返回 None
- `save_report_score` + `load_scores`：往返一致 / 同 date 覆盖幂等 / 排序
- `recent_scores(n)`：取最后 n 个
- `weekly_report_quality`：周均值计算 / 空输入
- 损坏文件 → .bak 备份 + []（不崩溃）

## 四、验收标准

1. `python -m pytest tests/ -v` 全绿（新增 + 既有）
2. `auto_evening_review.md` 第十三步行为不变（生成者自检仍执行，仅加职责声明）
3. 手工冒烟：用最新复盘报告（20260922）跑一次评审流程，产出分数 + 存档
4. 调度任务注册后，下一个交易日 17:20 自动触发

## 五、后续衔接

- **P0c**：`gap_analysis` 读 `recent_scores(4周)` → 报告质量维度差距 → 定向 REQ
- **P2**：REQ 关联"报告质量分"指标做前后对比
- 云库化：`report_quality_history` 表（本地先行，同 P0a）

## 六、风险与回滚

- 全为新增（新模块/新 prompt/新调度项）+ 1 处只读注释 → 回滚 = 删除新增
- 评审只读，不触碰报告文件 → 无写破坏风险
- 分数波动受"评审模型 + 评分表稳定性"影响：评分表锚点固化后分数才可比（v1 先固化锚点，v2 再考虑评审模型校准，对齐 dsh-eval-harness 的 judge 校准思想）
