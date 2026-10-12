# evolution 编排层 — 框架插件化说明（P3b）

> 自进化框架 P3b：把 astock 项目内的 evolution/ 编排层抽象为**跨项目可复用的进化框架**。
> 依据：研究文档 §3 框架设计（G1-G9 机制）+ §5 三层落地模型（平台层/领域层/项目层）。
> 状态：**已实施 P3b-1（纯函数抽包）**；P3b-2/3/4/5 为后续可选路径

## 〇、已实施：P3b-1 纯函数抽包（零回归）

**平台层框架引擎已落地 `~/.dsh/evolve/engine/`：**

```
~/.dsh/evolve/engine/
├── __init__.py       版本 0.1.0
├── goals.py          目标解析（goals.md 机器结算块）
├── metrics.py        指标取值（点路径 + 近 N 周均值）
├── gaps.py           差距计算 + 定向 REQ 建议
├── verify.py         REQ 对照验证（before/after + 动作建议）
└── tests/test_engine.py   12 项独立测试（虚拟项目数据，验证跨项目复用）
```

**项目 lib 改为薄壳引用框架核心**（保持向后兼容）：
- `lib/gap_analysis.py`：保留路径默认值，`compute_gaps/gen_req_suggestion/build_gap_report/parse_goals/current_value` 从引擎引入
- `lib/req_evolution.py`：`parse_evolution_fields/evaluate_improvement/suggest_action/extract_window` 从引擎引入

**验收：**
1. 项目全量 **598 passed, 1 skipped**（零回归——薄壳行为不变）✅
2. 框架引擎 **12 passed**（独立测试，虚拟数据，验证不依赖 astock 路径）✅
3. 新项目可复用：只需 `from evolve.engine import ...` + 提供数据源 ✅

**关键技术点：**
- 引擎用包方式导入（`from evolve.engine.gaps import ...`，`~/.dsh` 加 sys.path），相对导入在 sys.path 模式会失败
- 纯函数与项目路径完全解耦（路径默认值留在项目 lib，引擎只收参数）

## 一、目标

当前 evolution/ 是 astock 项目内的编排层，机制（结算→差距→定向REQ→对照验证）与项目数据耦合。P3b 将其抽象为：

```
平台层（~/.dsh 或独立包）   → 进化框架引擎（G1-G9 机制，跨项目复用）
领域层（~/.agents/domains/）→ 领域方法论（finance 包已建，P3a）
项目层（astock evolution/） → 项目数据 + 目标 + 领域映射
```

**路由判据**：产物离开 astock 还有用吗？→ 有用 = 上移平台/领域层；仅项目相关 = 留项目层。

## 二、框架抽象（哪些机制可抽）

| 机制 | 当前实现 | 抽象为框架后 |
|------|---------|------------|
| G5 结算器 | `lib/signal_quality.py` + `lib/report_quality.py` | 通用 `score_snapshot()`：项目提供"指标提取器"，框架提供"存档/聚合/版本化" |
| G6 差距分析 | `lib/gap_analysis.py` | 通用 `compute_gaps(goals, history)`：goals 机器块已是通用格式 |
| G7 定向 REQ | `auto_gap_analysis.md` 生成 REQ | 通用 `req_from_gap(gap)`：REQ 模板进化契约字段已通用（P2） |
| G8 对照验证 | `lib/req_evolution.py` | 通用 `evaluate_improvement(before, after, direction, expected)`：已是纯函数 |
| G1-G4 记忆/错误库 | experience/ + bugs/ | 平台层"三库"（经验库/错误模式库/知识库） |

**核心洞察**：P0a-P2 已把机制实现为**纯函数 + 机器可读配置（goals.md JSON 块）**——它们本身已高度可移植。框架插件化 = 把这些纯函数抽到一个独立模块（如 `~/.dsh/evolve/` 或独立包），项目通过配置声明"数据源/指标/目标"即可复用，无需改框架代码。

## 三、落地路径（分步）

1. **P3b-1 纯函数抽包**：把 `signal_quality_history.py` / `report_quality.py` / `gap_analysis.py` / `req_evolution.py` 的**纯函数部分**（无项目路径依赖的）抽到 `~/.dsh/evolve/engine/`（或独立 Python 包），项目 `lib/` 改为引用 + 保留项目特定逻辑（数据源提取器）。
2. **P3b-2 配置驱动**：goals.md 机器块升级为框架标准格式（source/field/target/weight/direction/verifier 已是标准字段），项目只维护 goals.md + 数据提取器。
3. **P3b-3 领域映射**：finance 领域包（P3a）定义"金融领域默认指标/基线"，新金融项目可一键初始化。
4. **P3b-4 调度抽象**：task_schedule.json 的 evolution 任务（gap_analysis/report_quality_review/signal_quality_weekly）抽象为"框架自带任务"，项目只声明目标。
5. **P3b-5 可选 DSH 插件化**：若需要跨 DSH 实例分发，封装为 DSH 插件（复用 dsh-eval-harness/continual-evolve 思路）；否则保持项目内抽象层（更轻）。

## 四、验收（P3b 完整落地后）

1. 新项目只需：`goals.md` + 数据提取器 + 调度声明 → 跑起完整进化闭环
2. 框架纯函数有独立测试（不与项目数据耦合）
3. 现有 astock 实现行为不变（框架抽包后回归 598 passed）

## 五、风险与边界

- **过度抽象**：当前只服务 1 个项目，抽太重反而增加维护。→ 先抽"纯函数"（零风险），配置驱动/调度抽象按需推进
- **失同步**：抽包后项目 lib 引用框架，改框架要回归项目 → 框架版本化 + 项目锁版本
- **P3b-5 插件化是可选项**：不强求 DSH 插件形态，除非有跨 DSH 实例需求

## 六、决策点（需用户确认）

1. 框架放哪：`~/.dsh/evolve/`（跟随 DSH）？还是独立 Python 包（`pip install`）？
2. 抽包深度：仅纯函数（轻）？还是含调度抽象（中）？还是 DSH 插件（重）？
3. 时机：本轮先落地 P3b-1（纯函数抽包 + 回归），还是先出设计等审阅？
