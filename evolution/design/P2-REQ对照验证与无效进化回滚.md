# P2 设计：REQ 对照验证（关联指标/基线/观察期 + 无效进化回滚）

> 自进化框架 P2（第二阶段）
> 依据：《基于 DeepSeek Harness 的 Agent 自进化框架研究.md》第 5 节（对照验证）+ 第 7 节（负反馈/回滚）
> 目标：把"改了但不知道有没有变好"升级为"指标前后对比证明变好"——进化闭环的最后一段。
> 日期：2026-09-24 | 状态：**已实施（代码+测试+冒烟通过）**

## 〇、实施结果

**验收标准达成：**
1. 全量测试 **590 passed, 1 skipped**（+16 项 P2）✅
2. `render_req_markdown` 渲染进化字段（缺省降级 N/A 不报错）✅
3. 手工冒烟：render→parse→evaluate 三分支（improved/no_change/insufficient）全正确 ✅

**实施产物清单：**
- `lib/req_evolution.py`：新增（parse_evolution_fields / extract_window / evaluate_improvement / suggest_action）
- `tests/test_req_evolution.py`：新增（16 项）
- `steering/REQ_TEMPLATE.md`：新增"进化契约"节（关联指标/基线值/预期改善/观察期）
- `lib/issue_tracker.py`：`render_req_markdown` 增加进化契约渲染（向后兼容）
- `prompts/auto_gap_analysis.md`：新增"三·五 待验证 REQ 对照验证（P2）"步骤

**冒烟验证（模拟 8 周历史）：**
```
before=33.3 after=43.75 exp=45.0 → no_change  → rollback（无改善→无效进化建议回滚）
before=33.3 after=46.0  exp=45.0 → improved   → close（达预期→CLOSED）
before=33.3 after=35.0  exp=45.0 → no_change  → rollback
before=None after=43.75 exp=45.0 → insufficient → extend（数据不足→延观察）
```

> **进化闭环全链路闭合**：结算（P0a/P0b 快照）→ 差距（P0c gap_analysis）→ 定向 REQ（P0c）→ 对照验证（P2，本步）。"无效进化回滚"只给建议，实际回滚走人工（MANUAL_REVIEW）。

## 一、背景与缺口

现有 REQ 生命周期：OPEN → IN_PROGRESS → IMPLEMENTED（代码写完+测试通过）→ CLOSED（测试通过+用户确认）。
验证的是"**工程门禁**"（代码对不对），不是"**进化验证**"（指标变没变好）。

P0c 的 gap_analysis 已生成带 `关联指标/基线值/预期改善` 的定向 REQ 建议（prompt 里写了），但：
1. **REQ 模板不认这些字段**（REQ_TEMPLATE.md / render_req_markdown 都没有）
2. **没有观察期与前后对比逻辑**——IMPLEMENTED 后直接 CLOSED，无指标验证
3. **没有"无效进化"回滚**——改了没变好，只能靠人发现

## 二、设计

### 2.1 REQ 进化契约字段（模板 + render 函数）

REQ_TEMPLATE.md 头部新增（gap_analysis 生成时自动填）：

```markdown
- **关联指标**: {metric_id}: {field}      （如 G-A: dims.overall.target_hit_rate）
- **基线值**:   {before}（实施前 N 周均值，N=观察期）
- **预期改善**: {target}                  （目标值，通常=goals.md 目标）
- **观察期**:   {4} 周                    （IMPLEMENTED 后等待周数再对比）
```

`render_req_markdown` 增加对应字段渲染（缺省降级为 "N/A"）。

### 2.2 `lib/req_evolution.py`（纯函数，可测试）

```python
def parse_evolution_fields(req_md: str) -> dict
    # 解析 REQ 正文的 关联指标/基线值/预期改善/观察期；缺失字段返回 None

def extract_window(sq_history: list, field: str, weeks: int) -> float | None
    # 取最近 N 周快照该字段均值（复用 gap_analysis 的取值逻辑）

def evaluate_improvement(before, after, direction='higher', expected=None) -> str
    # 返回 'improved'（改善）/ 'no_change'（无改善）/ 'insufficient'（数据不足）
    # 判定：after 相对 before 向 direction 移动即改善；expected 给定则须达到

def suggest_action(eval_result: str, observations: int) -> str
    # 'close'（改善→CLOSED）/ 'extend'（数据不足→延观察）/ 'rollback'（无改善→标记无效+回滚建议）
```

### 2.3 REQ 生命周期扩展

```
OPEN → IN_PROGRESS → IMPLEMENTED → [观察期 4 周] → 对照验证：
  ├─ 改善（after vs before 达预期）→ CLOSED + 沉淀经验
  ├─ 无改善 → 标记"无效进化" + 回滚建议（REQ 处理记录 + 回滚变更）
  └─ 数据不足 → 延长观察期（最多再延 4 周）
```

### 2.4 验证触发点（复用现有任务）

- **gap_analysis（周一）**：对 IMPLEMENTED 且观察期到期的 REQ，调用 `evaluate_improvement`，输出到差距周报"待验证 REQ 表"
- **人工确认仍保留**：CLOSED 需要用户最终确认（现有纪律不变）；"无效进化"回滚建议交人工执行（回滚涉及代码变更，MANUAL_REVIEW）

## 三、测试计划（TDD）

新增 `tests/test_req_evolution.py`：
- parse_evolution_fields：完整字段 / 缺字段返回 None / 无正文
- extract_window：N 周均值 / 不足 N 周取可用 / 空历史 None
- evaluate_improvement：改善 / 无改善 / 数据不足 / expected 约束
- suggest_action：close / extend / rollback 三分支

## 四、验收标准

1. 全量测试通过（新增 + 既有无回归）
2. `render_req_markdown` 能渲染进化字段（缺省降级不报错）
3. 手工冒烟：造一个带进化字段的 REQ 正文 + 模拟历史，跑 evaluate_improvement 三分支

## 五、后续衔接

- **P3**：领域包抽取 + 框架插件化（本模块与 gap_analysis 一起可抽为"进化引擎"）
- 云库化：REQ 验证记录可入 `req_evolution_log` 表（本地先行）

## 六、风险与回滚

- 全为新增（模板字段 + 新 lib + 新测试）+ render 函数向后兼容（缺省降级）→ 回滚 = 删除新增
- "无效进化"只**建议**回滚，实际回滚走人工（MANUAL_REVIEW）——自动化不改代码
- 观察期时长与方向判定在模板里显式化，避免口径漂移
