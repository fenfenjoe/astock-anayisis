# 复盘自动化修复 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 5 bugs in the evening review automation: simplify idempotency check, fix staging generation order, add final verification, remove auto_evening_review_verify.md

**Architecture:** Three file changes: (1) modify auto_evening_review.md to fix Step 1.3 idempotency check, reorder Steps 10/11, add final verification; (2) delete auto_evening_review_verify.md; (3) remove the task entry from task_schedule.json

**Tech Stack:** Markdown prompts, JSON config

## Global Constraints

- All changes must preserve existing functionality — only fix the bugs
- Keep the Generator-Evaluator separation principle intact
- Do not modify the 复盘分析-模板.md (the template itself is correct)

---

### Task 1: Simplify Step 1.3 (Idempotency Check) + Remove auto_evening_review_verify.md references

**Files:**
- Modify: `my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md` lines 56-125

**Problem:** Current Step 1.3 has a 3-layer check that's too complex. The `completed_at` date comparison logic has a bug where a stale `completed` status from a previous day blocks execution for the current day.

**Fix:** Replace the complex 3-layer check with a single file-existence check:
- If `reports/{today}/复盘报告.md` exists AND its mtime is today → skip (幂等)
- Otherwise → always execute (regardless of task_state)

- [ ] **Step 1: Replace Step 1.3 idempotency check**

Replace the current complex Step 1.3 (lines 56-125) with a simpler version:

Current lines 56-125 contain:
```
### 1.3 幂等性检查（三层门禁，防止漏生成）
...
早盘分析执行状态（三重检测，任一满足即为"已执行"）：
...
```

Replace with:
```markdown
### 1.3 幂等性检查

> 🚨 检查 `reports/{today}/复盘报告.md` 是否存在且为今日生成。是则跳过，否则强制执行。

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import os, json
from datetime import datetime

today_str = datetime.now().strftime('%Y-%m-%d')
today_ymd = datetime.now().strftime('%Y%m%d')
report_path = f'my_doc/每日复盘/reports/{today_ymd}/复盘报告.md'

# 文件存在性检查（最高优先级）
if os.path.exists(report_path):
    mtime = datetime.fromtimestamp(os.path.getmtime(report_path))
    if mtime.strftime('%Y-%m-%d') == today_str:
        print('复盘报告已存在且为今日生成 -> 幂等跳过 ✅')
        exit(0)
    elif datetime.now().hour >= 15 and datetime.now().minute >= 30:
        print(f'复盘报告存在但非今日生成 -> 收盘后强制覆盖重生成')
    else:
        print(f'复盘报告存在但非今日生成 -> 收盘前跳过，等待收盘后重新生成')
        exit(0)

# 收盘后强制检查
if datetime.now().hour >= 15 and datetime.now().minute >= 30:
    print(f'收盘后复盘报告不存在 -> 强制执行')
else:
    print(f'收盘前复盘报告不存在 -> 等待收盘后执行')
    exit(1)

# 早盘分析执行状态（用于后续步骤参考）
for f in ['my_doc/每日复盘/reports/{today}/早盘报告.md', 'my_doc/每日复盘/reports/{today}/每日信号.md']:
    print(f'{f}: {\"EXISTS\" if os.path.exists(f) else \"MISSING\"}')
"
```

**判断规则**（严格按 python 输出，禁止凭推理覆盖）：
- 输出 `幂等跳过` → 退出复盘流程（已完成）
- 输出 `强制执行` → 继续执行所有步骤
- 输出 `早盘报告.md: EXISTS` 或 `每日信号.md: EXISTS` → **早盘分析已执行**
- 两者皆 MISSING → **早盘分析确实未执行**（降级模式）
```

- [ ] **Step 2: Verify the edit is correct**

Read the modified section to confirm the replacement looks right.

- [ ] **Step 3: Commit**

```bash
cd E:/ideaworkspace/astock-anayisis
git add my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md
git commit -m "fix(evening-review): simplify Step 1.3 idempotency check

- Replace complex 3-layer check with single file-existence check
- Remove task_state-based logic that caused false skip

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Reorder Steps — Move 持仓同步 before Staging

**Files:**
- Modify: `my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md` (Step 10 and Step 11 sections)

**Problem:** Current order is Step 10 (生成Staging) → Step 11 (持仓同步). Staging needs to use the latest 持仓, so sync should happen first.

**Fix:** Renumber Step 11 to Step 10 (持仓同步), and Step 10 to Step 11 (生成Staging). Also update all cross-references.

- [ ] **Step 1: Swap the sections**

In `auto_evening_review.md`:
1. Rename current `## 第十步：生成次日 Staging` → `## 第十一步：生成次日 Staging`
2. Rename current `## 第十一步：同步持仓配置` → `## 第十步：同步持仓配置`
3. Update the intro text in the new Step 10 to note it must run BEFORE staging

For the new Step 10 header (formerly Step 11):
```
## 第十步：同步持仓配置（‼️ 必须在生成Staging之前执行）

> ⚠️ 关键顺序：持仓同步必须在生成Staging（第十一步）之前完成，否则 staging 中的持仓表将使用旧数据。
```

Update the new Step 11 header (formerly Step 10):
```
## 第十一步：生成次日 Staging（‼️ 使用第十步同步后的最新持仓）

这是复盘最核心的产出——为明日生成完整的、可执行的 staging prompt。
```

- [ ] **Step 2: Update cross-references in Step 11.1**

In the new Step 11.1 (formerly 10.1), update the note about 持仓同步:
Change: `⚠️ 持仓表待运行 每日调仓.md 同步脚本后更新`
To: `持仓表已在第十步（同步持仓配置）中更新为最新数据，此处直接使用`

- [ ] **Step 3: Verify the edits**

Read the modified sections to confirm the reordering looks correct.

- [ ] **Step 4: Commit**

```bash
cd E:/ideaworkspace/astock-anayisis
git add my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md
git commit -m "fix(evening-review): reorder 持仓同步 before staging generation

- Move Step 11 (持仓同步) to Step 10
- Move Step 10 (生成Staging) to Step 11
- Update cross-references

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Add Final Verification Step

**Files:**
- Modify: `my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md`

**Problem:** No verification that the report and staging files were actually generated at the end of the process.

**Fix:** Add a new Step 16 (最终验证) after the current Step 15 (更新 task_state).

- [ ] **Step 1: Add final verification section**

Append after the current Step 15 (更新 task_state → completed):

```markdown
---

## 第十六步：最终产出验证（‼️ 硬性门禁）

> 🚨 此步骤为复盘的最后一道防线。验证所有关键产出文件是否存在、是否为今日生成。验证失败 = 复盘未完成，必须回补。

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import os, sys
from datetime import date, timedelta, datetime

today = date.today()
today_ymd = today.strftime('%Y%m%d')
today_str = today.strftime('%Y-%m-%d')
tomorrow_str = (today + timedelta(days=1)).strftime('%Y-%m-%d')

errors = []

# 1. 验证复盘报告
report_path = f'my_doc/每日复盘/reports/{today_ymd}/复盘报告.md'
if os.path.exists(report_path):
    mtime = datetime.fromtimestamp(os.path.getmtime(report_path))
    if mtime.strftime('%Y-%m-%d') == today_str:
        size_kb = os.path.getsize(report_path) / 1024
        print(f'✅ 复盘报告: {report_path} ({size_kb:.1f}KB, {mtime.strftime(\"%H:%M\")})')
    else:
        errors.append(f'复盘报告存在但非今日生成 (mtime={mtime.strftime(\"%Y-%m-%d\")})')
else:
    errors.append(f'复盘报告不存在: {report_path}')

# 2. 验证早盘分析 staging
morning_staging = 'my_doc/每日复盘/harness/staging/今日-早盘分析.md'
if os.path.exists(morning_staging):
    with open(morning_staging, 'r', encoding='utf-8') as f:
        content = f.read()
    if len(content) < 500:
        errors.append(f'早盘分析staging过小 ({len(content)}字符): {morning_staging}')
    elif tomorrow_str not in content:
        errors.append(f'早盘分析staging缺少明日日期({tomorrow_str}): {morning_staging}')
    else:
        print(f'✅ 早盘分析staging: {morning_staging} ({len(content)}字符, 目标日期={tomorrow_str})')
else:
    errors.append(f'早盘分析staging不存在: {morning_staging}')

# 3. 验证复盘分析 staging
review_staging = 'my_doc/每日复盘/harness/staging/今日-复盘分析.md'
if os.path.exists(review_staging):
    with open(review_staging, 'r', encoding='utf-8') as f:
        content = f.read()
    if len(content) < 500:
        errors.append(f'复盘分析staging过小 ({len(content)}字符): {review_staging}')
    elif tomorrow_str not in content:
        errors.append(f'复盘分析staging缺少明日日期({tomorrow_str}): {review_staging}')
    else:
        print(f'✅ 复盘分析staging: {review_staging} ({len(content)}字符, 目标日期={tomorrow_str})')
else:
    errors.append(f'复盘分析staging不存在: {review_staging}')

# 4. 验证归档
archive_dir = f'my_doc/每日复盘/harness/archive/{today_ymd}'
if os.path.isdir(archive_dir):
    files = os.listdir(archive_dir)
    print(f'✅ 归档目录: {archive_dir} ({len(files)}个文件)')
else:
    errors.append(f'归档目录不存在: {archive_dir}')

# 输出结果
if errors:
    print(f'\n❌ 最终验证失败 ({len(errors)}个错误):')
    for e in errors:
        print(f'  ❌ {e}')
    print('\n*** 必须回补缺失文件后重新验证 ***')
    sys.exit(1)
else:
    print(f'\n✅ 最终验证通过 — 所有产出文件已正确生成')
" 2>&1
```

**如果验证失败**：必须回到对应步骤重新生成缺失文件，重新运行验证直到通过。**禁止在验证失败的情况下标记 task_state 为 completed。**

**如果验证通过**：继续执行第十五步（更新 task_state → completed）或确认已完成。
```

- [ ] **Step 2: Commit**

```bash
cd E:/ideaworkspace/astock-anayisis
git add my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md
git commit -m "feat(evening-review): add final verification step (Step 16)

- Validate 复盘报告, staging files, and archive after completion
- Hard gate: fail = must re-generate before marking completed

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Delete auto_evening_review_verify.md + Remove from Schedule

**Files:**
- Delete: `my_doc/每日复盘/harness/automation/prompts/auto_evening_review_verify.md`
- Modify: `.claude/scripts/task_schedule.json`

**Problem:** User explicitly requested removal of auto_evening_review_verify.md. The verification responsibility moves into auto_evening_review.md itself (Task 3 adds Step 16).

- [ ] **Step 1: Delete the file**

```bash
cd E:/ideaworkspace/astock-anayisis
git rm my_doc/每日复盘/harness/automation/prompts/auto_evening_review_verify.md
```

- [ ] **Step 2: Remove the task from schedule**

In `.claude/scripts/task_schedule.json`, remove the `evening_review_verify` entry (lines 193-200):

```json
    {
      "task_id": "evening_review_verify",
      "target_time": "16:17",
      "days_of_week": [0, 1, 2, 3, 4],
      "trading_day_required": true,
      "prompt_file": "my_doc/每日复盘/harness/automation/prompts/auto_evening_review_verify.md",
      "window_minutes": 7,
      "description": "收盘复盘验证 (收盘后检查复盘报告是否存在)"
    }
```

- [ ] **Step 3: Commit**

```bash
cd E:/ideaworkspace/astock-anayisis
git add .claude/scripts/task_schedule.json
git rm my_doc/每日复盘/harness/automation/prompts/auto_evening_review_verify.md
git commit -m "refactor(evening-review): remove auto_evening_review_verify.md

- Delete the standalone verification prompt file
- Remove evening_review_verify task from task_schedule.json
- Verification responsibility moved into auto_evening_review.md Step 16

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Final Integration Check

- [ ] **Step 1: Verify all changes are consistent**

```bash
cd E:/ideaworkspace/astock-anayisis
# Check the verify file is gone
test -f "my_doc/每日复盘/harness/automation/prompts/auto_evening_review_verify.md" && echo "VERIFY_FILE_STILL_EXISTS" || echo "VERIFY_FILE_DELETED"

# Check schedule no longer references it
grep -n "evening_review_verify" ".claude/scripts/task_schedule.json" || echo "NO_SCHEDULE_REFERENCE"

# Check auto_evening_review.md has the new Step 16
grep -c "第十六步：最终产出验证" "my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md" || echo "MISSING_STEP_16"

# Check Step 1.3 is simplified (no longer has "三层门禁")
grep -c "三层门禁" "my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md" || echo "OLD_CHECK_REMOVED"

# Check ordering: 第十步 should now be 持仓同步
grep -A1 "## 第十步：" "my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md" | head -5

# Check git status
git status
```

- [ ] **Step 2: Report results to user**

Output the verification results so the user can confirm all changes are correct.
