# Staging 过期检测与自动重建 — 设计文档

> 日期：2026-08-10
> 状态：已获用户确认（方案 A）
> 关联系统：每日复盘 Harness（`my_doc/每日复盘/`）

## 一、背景与问题

每日复盘系统的 staging 文件（`harness/staging/今日-早盘分析.md` + `今日-复盘分析.md`）由每晚复盘生成，头部标注"执行日期"。正常节奏下每天使用，staging 持续更新。

**问题场景**：用户可能隔几天才使用每日复盘项目。此时 staging 仍是数天前生成的，内容（预判回顾/板块扫描/做T建议/跨品种约束/事件日历）已过时失效，但早盘分析仍会读取使用——**用失效 staging 生成错误的早盘报告**。

**现状缺陷（三层）**：
1. **过期检测实际未生效（bug）**：`auto_morning_analysis.md` 1.3c 有 `STALE DATE` 检测，但正则 `re.search(r'(\d{4}-\d{2}-\d{2})', staging.split('\n')[0])` 只匹配第一行（`# 每日复盘上下文`，无日期）→ 返回 None → 日期检查被静默跳过。
2. **检测到过期也不重建**：现有逻辑只"忽略 staging 持仓表、用 config 覆盖"，但分析内容（预判回顾等）仍用旧日期的。
3. **手动触发完全无检测**：`daily-review-harness` skill 早盘模式第 1 步直接读 staging，无任何新鲜度检查。

## 二、设计决策（已确认）

| 决策点 | 结论 |
|--------|------|
| 过期判定标准 | 按 **staging 头部"执行日期"** 判定：执行日 < 今天 → 过期 |
| 过期后行为 | **自动重建 staging**（不中断早盘流程） |
| 重建深度 | **轻量重建**：基于最近一次可用复盘报告 + 当前持仓 + 模板框架，标注"补生成" |

## 三、方案选择

| 方案 | 做法 | 结论 |
|------|------|------|
| **A（采纳）** | 新增 `lib/staging_freshness.py` 纯函数库 + pytest + 自动/手动两入口集成 + 轻量重建流程 | 可测试、逻辑单点、两入口复用 |
| B | 只改 `auto_morning_analysis.md` 内联 bash | 不可测试、手动不覆盖、逻辑重复 |
| C | 过期时自动补跑 N 天复盘再重建 | 耗时超早盘窗口，已否决 |

## 四、组件设计

### 4.1 新增 `lib/staging_freshness.py`（纯函数，全部可单测）

```python
# 定位：my_doc/每日复盘/harness/automation/lib/staging_freshness.py

def parse_staging_execution_date(text: str) -> date | None:
    """
    解析 staging 头部"执行日期"。
    匹配模式：`执行日期：**YYYY-MM-DD（周X）早盘前**` 或类似格式。
    # 修复现有 bug：旧代码只匹配第一行（无日期）。
    返回 date；找不到返回 None。
    """

def is_staging_stale(exec_date: date, today: date) -> tuple[bool, dict]:
    """
    过期判定：exec_date < today → 过期。
    Returns: (is_stale, {exec_date, days_old, reason})
    边界：exec_date == today → 新鲜；exec_date > today → 新鲜（提前生成，不判过期）。
    """

def find_latest_review_report(reports_root: str | Path) -> date | None:
    """
    扫 reports/{yyyyMMdd}/ 目录，找最近一个含 复盘报告.md 的日期。
    用于轻量重建的输入定位。找不到返回 None。
    """

def staging_health_check(
    staging_text: str | None,
    today: date,
    reports_root: str | Path,
) -> dict:
    """
    综合健康检查入口。
    staging_text=None 表示文件缺失。
    Returns:
        {
            'exists': bool,
            'exec_date': date | None,
            'stale': bool,
            'latest_review_date': date | None,
            'action': 'use' | 'rebuild' | 'missing',
        }
    判定规则：
      - staging 缺失 → action='missing'
      - 存在且执行日解析失败（None）→ action='rebuild'（保守：宁重建不静默用旧，见第七节）
      - 存在且执行日 >= 今天 → action='use'
      - 存在但执行日 < 今天（过期）→ action='rebuild'
    """
```

### 4.2 新增 `tests/test_staging_freshness.py`

四组测试：
1. **parse_staging_execution_date**：正常格式 / 无日期 / 不同格式（含 `**` 号、不同周几）
2. **is_staging_stale**：执行日=今天→不过期 / 执行日<今天→过期 / 执行日>今天→不过期 / 距今天数计算
3. **find_latest_review_report**：有复盘目录 / 无复盘目录 / 空目录 / 多目录取最新
4. **staging_health_check**：缺失→missing / 新鲜→use / 过期→rebuild

## 五、集成点

### 5.1 `auto_morning_analysis.md`（自动入口）

替换现有 1.3c 中的过期检测部分，新增 **1.3d Staging 过期检测与重建**：

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from datetime import date
from lib.staging_freshness import staging_health_check

with open('my_doc/每日复盘/harness/staging/今日-早盘分析.md', 'r', encoding='utf-8') as f:
    text = f.read()
result = staging_health_check(text, date.today(), 'my_doc/每日复盘/reports')
print(json.dumps(result, ensure_ascii=False))
"
```

按 `action` 分支处理：
- `use` → 正常继续
- `rebuild` → 进入"轻量重建流程"（见第六节）
- `missing` → 保留现有降级逻辑（1.3 已有）

保留 1.3b（代码-名称校验）和 1.3c 的**持仓比对部分**（config 覆盖逻辑依然有效），仅废弃 1.3c 中失效的日期正则（由 1.3d 的纯函数替代）。

### 5.2 `daily-review-harness` SKILL.md（手动入口）

早盘模式流程第 1 步（读取 staging）前，增加"staging 新鲜度检查"步骤：
- 读取 staging → 跑 `staging_health_check`
- `rebuild` → 执行轻量重建 → 再读取新 staging
- `missing` → 现有降级逻辑
- 与自动入口共用同一纯函数，不重复实现

## 六、轻量重建流程（Agent 步骤，prompt 内描述）

触发条件：`action='rebuild'`（staging 存在但执行日 < 今天）。

**步骤**（由早盘分析 Agent 执行，非纯函数）：
1. **定位最近复盘**：`find_latest_review_report()` → 得到日期 Y
2. **读取复盘报告**：`reports/{Y}/复盘报告.md` → 提取"核心矛盾/核心教训/预判回顾"
3. **生成新 staging**：
   - 执行日期更新为今天
   - 持仓表从 `config/持仓.md` 权威读取
   - "前次预测回顾/信号回顾" ← 基于复盘报告 Y 的内容（标注"基于 Y 日复盘"）
   - 核心矛盾/特别关注 ← 基于复盘 Y + 今日市场状态
   - 事件日历 ← 今日数据（解禁/宏观/海外映射）
4. **覆写** `staging/今日-早盘分析.md` + `今日-复盘分析.md`
5. **头部标注**：`⚠️ 补生成（原 staging 执行日 X 已过期，基于 Y 日复盘重建）`
6. **重建完成后**：正常走早盘流程（读新 staging）

**质量约束**：
- 重建的 staging 明确标注"补生成"，让早盘报告能追溯数据基础
- 持仓数据绝不用 staging 旧值，一律从 config 读取（沿用 4.1 铁律）
- 若 `find_latest_review_report` 返回 None（无任何复盘）→ 降级为模板早盘（现有 missing 逻辑）

## 七、错误处理

| 场景 | 处理 |
|------|------|
| staging 文件不存在 | action='missing' → 现有降级逻辑（模板+今日数据） |
| 执行日期解析失败（None） | 视为过期（保守处理：宁重建不静默用旧）→ action='rebuild' |
| 无任何复盘报告可参考 | 降级为模板早盘 |
| 重建时 config/持仓.md 缺失 | 中止并报错（持仓是硬依赖） |
| 非交易日运行 | 由现有交易日检查拦截，此逻辑不额外处理 |

## 八、测试计划

- 新增 `tests/test_staging_freshness.py`（见 4.2）
- 运行：`cd my_doc/每日复盘/harness/automation && python -m pytest tests/test_staging_freshness.py -v`
- 不依赖真实行情数据，全部合成数据（符合 conftest.py 现有约定）
