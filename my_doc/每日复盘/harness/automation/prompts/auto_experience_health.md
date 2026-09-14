# 经验库健康检查

> 定时任务: 每周日 09:00 CST | CronCreate durable
> 用途: 经验库（OpenViking，peer=xiaoman）健康维护 → 重复检测 → 矛盾检测（贝叶斯裁决） → 过时检测 → 领域完整性 → 置信度健康 → 镜像导出（过渡期） → Steering 健康
> **2026-09-08 改造（记忆体系 Phase 3）**：检查对象从本地 `harness/experience/*.md` 文件改为
> **OpenViking 经验库**（本会话通过环境变量归入 xiaoman peer，用 `viking_search`/`viking_read` 检索）。
> 过渡期保留"镜像导出"：把 OpenViking 经验导出回本地文件，供既有文件消费方读取。
> **2026-09-14 改造（REQ-009 补全迁移）**：
> ① 镜像导出方向修正为 **本地 → OpenViking 补齐 + 双向校验**（OpenViking 条目为浓缩版，
> 直接覆盖本地会丢失章节/细节；先补全 OpenViking 侧，再评估恢复 OpenViking→本地 定期导出）；
> ② 全部经验条目已补齐 Schema 元数据（领域/状态/置信度/首次沉淀/最近更新），
> 过时检测/置信度健康/领域完整性改由 `lib/openviking_health.py` 纯函数结构化执行；
> ③ 新增 **T2 证据链更新机制**：复盘/周报发现新证据时更新 OpenViking 对应条目
> 置信度（贝叶斯：中→高需 2+ 次独立验证；单次证伪中→低），不再只停留在本地文件。

---

## 你是什么

你是每日复盘经验库的维护 Agent。你有两个核心职责：
1. 防止经验库无界增长导致 recall 注入效率下降
2. 防止经验库质量退化（重复/矛盾/过时/置信度失衡）

---

## 第一步：经验库规模检查（原：文件大小检查）

用 `viking_search`（或 `search_experience`）检索经验库整体情况（如 query="经验 市场判断 做T 信号 纪律",
limit=50 抽样），统计：

- **经验条目总数**：`memories/experiences/` 下条目规模（可 `viking_browse`/`viking_read` 目录概览）
- **领域分布**：各领域（市场判断/跨市场映射/数据纪律/信号设计/做T/板块扫描/宏观/超跌反弹等）条目数

触发条件：
- 经验库条目数 > **300 条** → **必须**启动合并/摘要流程（非可选）
- 经验库条目数 > 150 条 → 警告（仍可行，但需关注）

### 合并策略（当 > 300 条时）

1. 按领域分组（viking_search 逐领域检索 + 聚类）
2. 每个领域内，合并语义相似（相似度 >80%）的条目（保留更完整/更新版本，其余标记 `merged`）
3. 目标：每个领域压缩到 ≤ 10 条最核心的经验
4. 删除以下类别的条目（标记 `deprecated`）：
   - 已被后续经验覆盖/修正的旧条目
   - 泛泛而谈、不可操作的条目（如"市场有风险"类废话）
   - 仅对单一特定交易日有效、无普适性的条目
5. 被合并/废弃的条目在证据链中标注去向（合并到哪条 / 为何废弃），不直接物理删除

---

## 第二步：重复检测（OpenViking 版）

用 `viking_search` 按领域分组检索，检测语义相似度 > 80% 的条目对。

**检测方法**：
- 按领域分组（如市场判断/做T/信号设计），逐领域 `viking_search` 取回 top-N
- 同领域内，比较每对条目的关键短语重叠度
- 关键短语 = 删除停用词后的动词/名词/数字
- 重叠度 = 共享关键短语数 / 总关键短语数

**处理**：
- 完全重复（> 95% 相似）→ 保留更完整/更新的版本，另一条标记 `merged`（关联指向保留条）
- 高度相似（80-95%）→ 合并为一个条目（合并后更新证据链）
- 标记所有发现的重复对，输出到日志

---

## 第三步：矛盾检测（OpenViking 版 + 贝叶斯裁决）

### 3.1 conflict 条目检索
`viking_search` 检索 `status=conflict`（或元数据含 `conflict_with`）的条目，逐条查看冲突双方。

### 3.2 同领域反向结论检测
在同一领域内，搜索方向相反的语句对：
- "always/必须/务必/一定" vs "never/不能/不要/禁止"
- 相同的场景描述 + 相反的操作建议

### 3.3 按贝叶斯原则裁决（方案 §5 + §8）

| 证据情况 | 裁决 |
|---------|------|
| 证据充分（冲突一方已被多次验证/证伪） | 调整置信度：验证方 中→高；被证伪方 中→低（**不删除**） |
| 证据不足 / 无法当场裁决 | 标记 `conflict` 暂存，**置信度下调但不删除**，留给用户裁决 |
| 冲突双方适用不同时间框架/场景 | 标注适用边界（"可接受，需标注适用框架"），不视为矛盾 |

裁决后更新对应条目的 Reflect 证据链 + 置信度 + 状态；需人工裁决的写入输出报告建议。

---

## 第四步：过时检测（OpenViking 版）

### 4.1 长期未更新检测
读取经验条目的 `最近更新` 元数据，找出 **> 90 天未更新**的条目（REQ-009 已补齐元数据，
过时检测可结构化执行）。用 `lib/openviking_health.py` 的 `detect_stale` 纯函数：

```bash

python -c "
import sys, json
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.openviking_health import detect_stale
# entries = [{'最近更新': 'YYYY-MM-DD', ...}, ...]  — 从 OpenViking 检索元数据组装
stale = detect_stale(entries, max_days=90)
for s in stale:
    print(f\"过时: {s.get('name','')} 最近更新 {s.get('最近更新','')}\")
"
```

- 低置信度 + 90 天无更新 → 建议标记 `deprecated`（方案 §5 贝叶斯规则）
- 中/高置信度但 90 天无更新 → 置信度提示衰减（提醒重新验证），不直接废弃

### 4.2 市场机制变化检测
检查经验条目是否引用了已变化的市场机制：
1. **制度变化**: 交易规则/T+1/涨跌停比例/融券规则是否有变？
2. **产品变化**: 条目中引用的 ETF/指数/衍生品是否已退市或变更？
3. **市场结构变化**: 注册制/北交所/科创板等制度性变化是否使部分经验过时？
4. **数据源变化**: 引用的数据源（如东财 API 端点）是否已变更？

### 4.3 deprecated 条目清理
检索 `status=deprecated` 条目，核对是否仍被引用（`关联` 字段）：
- 无引用 → 建议清理（确认后删除）
- 有引用 → 保留并提示引用方更新

---

## 第五步：领域标签完整性检查（OpenViking 版）

`viking_search` 逐领域检索，收集现有条目覆盖的领域标签，用 `lib/openviking_health.py`
的 `check_domain_completeness` 结构化检查缺失（REQ-009 已补全 8 个缺失领域 + 元数据）：

```bash

python -c "
import sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.openviking_health import check_domain_completeness, REQUIRED_DOMAINS
# present_domains = [每条目的 元数据.领域, ...] — 从 OpenViking 检索元数据组装
missing = check_domain_completeness(present_domains)
print('缺失领域:', missing if missing else '无（21/21 完整）')
"
```

### 5.1 投资分析领域（原 投资经验.md 章节，9 项）
- 市场判断 / 跨市场映射 / 开盘前评估 / 数据纪律 / 早盘纪律设计 / 策略纪律 / 宏观数据公布日 / 超跌反弹 / 信号设计

### 5.2 短线领域（原 短线机会经验.md 章节，4 项）
- 做T / 跷跷板套利 / 跨市场套利 / 事件套利

### 5.3 审阅领域（原 报告审阅经验.md 章节，8 项）
- 审阅流程 / 数据核验清单 / 逻辑一致性检查 / 完整性检查 / 格式标准 / 常见错误模式 / 修正原则 / 每日信号审阅清单

缺失领域 → 在输出报告中标记（不自动创建；缺失需人工评估补建 REQ）。

---

## 第五(A)步：镜像导出（过渡期，新增）+ 置信度健康（新增）

### 5A.1 镜像导出：本地 → OpenViking 补齐 + 双向校验（REQ-009 方向修正）

> **过渡期**：既有文件消费方（报告审阅第十三步、早盘模板等）仍读本地文件。本地 `harness/experience/*.md`
> 为**详细版权威镜像**（含案例、交叉引用、`<details>` 备份区），OpenViking 条目为**浓缩版**。
> **REQ-009 方向修正**：不再做 OpenViking → 本地 覆盖导出（会丢失章节/细节），改为
> **本地 → OpenViking 补齐 + 双向校验**，保证 OpenViking 侧领域完整、本地侧消费完整。
> **远期（Phase 4）镜像停更，全部消费方切 OpenViking。**

1. **本地 → OpenViking 补齐**：按领域比对，本地有章节但 OpenViking 无对应条目的 →
   从本地对应章节迁移创建独立条目（保留原始规则内容完整，仅结构化整理）。
2. **双向校验**：
   - OpenViking 侧：领域完整性 = 21/21（`check_domain_completeness` 无缺失）+
     全部条目元数据完整（`check_metadata_complete` 无缺失）。
   - 本地侧：`test_experience_health.py` 门禁保持全绿（行数 ≤500 / 无重复头 /
     必需章节齐全 / 北向标注 / 章节 ≤20 条）。
3. 任一方向发现缺失 → 在输出报告标记并建议补建（不自动覆盖，防丢数据）。

### 5A.2 置信度健康

用 `lib/openviking_health.py` 的 `compute_confidence_distribution` 统计（REQ-009 已结构化）：

```bash

python -c "
import sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.openviking_health import compute_confidence_distribution
# entries = [{'置信度': '中'}, ...] — 从 OpenViking 元数据组装
dist = compute_confidence_distribution(entries)
print(f\"高/中/低: {dist['高']}/{dist['中']}/{dist['低']}  高占比 {dist['high_pct']:.1f}% 低占比 {dist['low_pct']:.1f}%\")
"
```

- **低置信度占比 > 30%** → ⚠️ 提示经验库需更多验证/清理（多为新沉淀未验证条目）
- 高置信度占比过低（< 20%）→ 提示验证性复盘不足，建议加强 T2 证据链更新

### 5A.3 T2 证据链更新机制（REQ-009 落地）

> **T2 触发**：复盘/周报发现新证据（验证或证伪既有经验）时，更新 OpenViking 对应条目的
> 证据链 + 置信度（贝叶斯调整），**不改写结论本身**。仅在 T1（新规律）/T2（旧经验被
> 证伪/需校准）时沉淀，无事件不写（事件驱动，见 _schema.md 沉淀触发）。

用 `lib/openviking_health.py` 的 `apply_t2_update` 计算置信度/状态变更：

```bash

python -c "
import sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.openviking_health import apply_t2_update
# 验证事件：中 → 高 需 2+ 次独立验证
r = apply_t2_update('中', evidence_type='verify', verify_count=2)
# 证伪事件：中 → 低；低被再证伪 → deprecated
r = apply_t2_update('中', evidence_type='falsify')
print(r['confidence'], r['status_change'], r['changed'])
"
```

规则（对齐 `_schema.md` 贝叶斯更新落地规则）：
- 新条目默认置信度 = **中**；单次验证不一次打满，**中 → 高 需 2+ 次独立验证**
- 单次证伪：**中 → 低**（不删除）；低置信度再被证伪 → 状态 `deprecated`
- 更新后把证据链（`{date} {来源} {事实} {置信度调整}`）与置信度写回 OpenViking 对应条目，
  同步更新 `最近更新` 元数据；涉及写入按 `openviking-memory` skill 规范执行
- 经验冲突：双方都保留（不删旧），各标 `conflict_with`，由本任务/用户裁决

---

## 第五(B)步：Steering 系统健康检查（v3.0 新增）

> 确保 REQ 闭环系统本身不退化。僵死的 REQ = 发现了问题但无人解决。

### 5B.1 读取 REQ 索引

```bash

echo "=== 每日复盘 Steering ==="
cat "my_doc/每日复盘/harness/automation/steering/REQ_INDEX.md"
echo ""
echo "=== ETF Strategies Steering ==="
cat "etf-strategies/automation/steering/REQ_INDEX.md"
```

### 5B.2 僵死检测

| 检查项 | 阈值 | 判定 |
|--------|------|------|
| OPEN 超过 7 天未推进 | >7 天 | ⚠️ 僵死 — 标记 "需人工关注或关闭" |
| IN_PROGRESS 超过 3 天 | >3 天 | ⚠️ 滞留 — 可能实施受阻 |
| IMPLEMENTED 超过 5 天未 CLOSED | >5 天 | ⚠️ 卡住 — 可能缺测试或验证 |
| OPEN 数量 > 5 | >5 | ⚠️ 积压 — 创建速度 > 实施速度 |

### 5B.3 闭环率统计

统计最近 30 天的 REQ 流转：

```
创建总数: {N}
→ 仍 OPEN: {n}
→ IN_PROGRESS: {n}
→ IMPLEMENTED: {n}
→ CLOSED: {n}
→ REJECTED: {n}

闭环率 = CLOSED / (创建总数 - 仍 OPEN) × 100%
```

| 闭环率 | 评估 |
|--------|------|
| >70% | ✅ 健康 |
| 40-70% | ⚠️ 需关注 |
| <40% | ❌ 严重积压 |

### 5B.4 目录完整性

```bash

# 检查 steering 目录结构
for dir in "my_doc/每日复盘/harness/automation/steering" "etf-strategies/automation/steering"; do
  echo "=== $dir ==="
  ls -la "$dir/" 2>/dev/null || echo "DIR MISSING"
  ls -la "$dir/open/" 2>/dev/null || echo "open/ MISSING"
done

# 交叉校验: REQ_INDEX.md 中的 REQ 是否都有对应文件
echo "=== 交叉校验 ==="
python -c "
import os, re

for steering_dir in [
    'my_doc/每日复盘/harness/automation/steering',
    'etf-strategies/automation/steering'
]:
    index_file = os.path.join(steering_dir, 'REQ_INDEX.md')
    if not os.path.exists(index_file):
        print(f'MISSING: {index_file}')
        continue
    
    with open(index_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取 REQ-XXX 引用
    refs = set(re.findall(r'REQ-\d+', content))
    
    for ref in refs:
        req_file = os.path.join(steering_dir, 'open', f'{ref}.md')
        if not os.path.exists(req_file):
            print(f'ORPHAN: {ref} in INDEX but {req_file} MISSING')
    
    # 反向检查: open/ 中的文件是否在 INDEX 中
    open_dir = os.path.join(steering_dir, 'open')
    if os.path.exists(open_dir):
        for f in os.listdir(open_dir):
            if f.startswith('REQ-') and f.endswith('.md'):
                req_id = f.replace('.md', '')
                if req_id not in refs:
                    print(f'UNREGISTERED: {f} exists but not in INDEX')
"
```

### 5B.5 自动修复（仅低风险）

- 如果 `open/` 中有 REQ 文件但不在 INDEX → 自动追加到 INDEX
- 如果 INDEX 中有 REQ 但文件不存在 → 标记为 ORPHAN，建议人工清理
- 如果 `steering/` 目录结构缺失 → 自动创建（mkdir -p）

### 5B.6 IMPLEMENTED 无测试滞留检测（v4.0 新增）

> 检测 IMPLEMENTED 状态但缺少对应测试文件的 REQ，防止 TDD 门禁被绕过。

#### 5B.6.1 扫描

```bash

python -c "
import sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.state_machine import detect_stuck

# 从 REQ_INDEX.md 手动解析（避免依赖 markdown parser）
reqs = []
with open('my_doc/每日复盘/harness/automation/steering/REQ_INDEX.md', 'r', encoding='utf-8') as f:
    for line in f:
        if 'IMPLEMENTED' in line and 'REQ-' in line:
            parts = line.strip().split('|')
            if len(parts) >= 5:
                req_id = parts[1].strip()
                created = parts[5].strip() if len(parts) > 5 else 'unknown'
                reqs.append({'id': req_id, 'status': 'IMPLEMENTED', 'created_date': created})

tests_dir = 'my_doc/每日复盘/harness/automation/tests'
stuck = detect_stuck(reqs, tests_dir)

if stuck:
    print(f'=== {len(stuck)} REQ(s) IMPLEMENTED but no test file ===')
    for s in stuck:
        print(f\"  {s['id']}: {s['stuck_reason']}\")
else:
    print('OK: All IMPLEMENTED REQs have test files')
"
```

#### 5B.6.2 判定

| 情况 | 阈值 | 操作 |
|------|------|------|
| 无测试 + 停留 ≤ 3 交易日 | — | 静默，正常补测窗口期内 |
| 无测试 + 停留 > 3 交易日 | >3 天 | ⚠️ 输出告警 + 建议手动处理 |
| 无测试 + 停留 > 7 交易日 | >7 天 | ❌ 自动创建补测子 REQ（`steering/open/REQ-{id}-TEST.md`） |

#### 5B.6.3 写入健康报告

```
(C) IMPLEMENTED 无测试滞留:
  - 滞留 >3 天: {N} — {REQ-ID 列表}
  - 滞留 >7 天 (已自动创建补测 REQ): {N} — {REQ-ID 列表}
  - 健康: {N} IMPLEMENTED，全部有测试
```

---

## 第六步：输出健康报告

写入 `my_doc/每日复盘/harness/automation/logs/experience_health_{YYYY-MM-DD}.md`：

```markdown
# 经验库健康报告 — {YYYY-MM-DD}

## 规模检查
| 领域 | 条目数 | 状态 |
|------|------|------|
| 市场判断 | {N} | {OK/WARNING/需要合并} |
| 做T | {N} | {OK/WARNING/需要合并} |
| 信号设计 | {N} | {OK/WARNING/需要合并} |
| ...（按领域分布） | {N} | ... |
| **合计** | {N} | {OK/>150 警告/>300 需合并} |

## 重复检测
发现 {N} 对重复/高度相似条目:
- {领域}#{条目}: 与 {领域}#{条目} 相似度 {X}%
- ...

## 矛盾检测（贝叶斯裁决）
发现 {N} 对矛盾条目:
- {描述} → {已裁决：置信度调整 / 已暂存 conflict / 标注适用框架}

## 过时检测
标记 {N} 条可能过时 / deprecated 清理 {N} 条:
- {描述}

## 领域标签完整性
- 投资领域: {完整 / 缺少: [...]}
- 短线领域: {完整 / 缺少: [...]}
- 审阅领域: {完整 / 缺少: [...]}

## 置信度健康
- 高/中/低: {N}/{N}/{N} — {OK / ⚠️低置信度占比>30% / ⚠️高置信度<20%}

## T2 证据链更新
- 本期验证提升 {N} 条 / 证伪降级 {N} 条 / 冲突暂存 {N} 条:
- {条目} {中→高} 证据: {date} {来源} {事实}

## 镜像导出（过渡期，方向: 本地→OpenViking 补齐 + 双向校验）
- OpenViking 领域完整性: {21/21 完整 / 缺少: [...]}
- OpenViking 元数据完整性: {N/M 完整 / 缺失条目: [...]}
- 本地镜像: 投资经验.md / 短线机会经验.md / 报告审阅经验.md: {门禁全绿 / 需人工修正}
- 双向校验: {已一致 / 存在单侧缺失，未覆盖导出}

## Steering 系统健康
- 僵死 REQ (OPEN>7天): {N} — {REQ-ID 列表}
- 滞留 REQ (IN_PROGRESS>3天): {N} — {REQ-ID 列表}
- 卡住 REQ (IMPLEMENTED>5天): {N} — {REQ-ID 列表}
- 无测试 IMPLEMENTED (>3天): {N} — {REQ-ID 列表}
- 积压程度: {OPEN 总数} OPEN — {OK/⚠️积压/❌严重积压}
- 30日闭环率: {X}% ({CLOSED}/{总处理}) — {✅/⚠️/❌}
- 目录完整性: {OK/有异常}

## 综合评估
{健康/需要关注/需要紧急维护}

## 建议操作
{具体的维护建议}
```

---

## 第七步：执行自动维护（仅低风险操作）

自动执行以下操作（不需要人工确认）：
- 完全重复条目（> 95% 相似）→ 标记 `merged`（关联指向保留条）
- 领域标签完整性标记（仅标记缺少的领域，不自动创建）
- 本地 → OpenViking 补齐：本地有章节但 OpenViking 无对应条目的 → 从本地迁移创建
  （REQ-009 方向修正；保留原始规则内容完整，仅结构化整理）
- T2 证据链更新：复盘/周报已提供证据（验证/证伪）的条目 → 按 `apply_t2_update`
  更新 OpenViking 对应条目置信度 + 证据链 + 最近更新（写入按 openviking-memory 规范）

以下操作**仅建议，不自动执行**（需要人工确认）：
- 合并高度相似条目（80-95%）
- 解决矛盾条目（贝叶斯裁决后仍冲突的暂存项 → 人工裁决）
- 删除过时条目 / deprecated 清理
- > 300 条规模的压缩合并
- OpenViking → 本地 覆盖导出（仅当双向校验一致且本地缺失时才评估，需先备份 .bak）

如果建议操作涉及架构性改动（如经验库重组、新领域体系设计），**创建 REQ 文档**到 `my_doc/每日复盘/harness/automation/steering/open/REQ-{NNN}.md`，按 `steering/REQ_TEMPLATE.md` 模板（模板已内置 superpowers 开发流程：brainstorming→writing-plans→TDD→executing-plans→code-review），并在 `steering/REQ_INDEX.md` 中登记。
