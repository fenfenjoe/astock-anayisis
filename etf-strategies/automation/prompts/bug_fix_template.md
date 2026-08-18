# BUG 修复模板

> 触发方式: 人工审查 BUG 报告后手动触发
> 用途: 标准化的 BUG 修复工作流，含分支创建、修复、测试、提交

---

## 前提

本 prompt 需要接收一个具体的 BUG ID（从 BUG_INDEX.md 中选择）。触发时指定：

```
BUG-ID: BUG-{NNN}
```

---

## 第一步：加载 BUG 报告

读取 `etf-strategies/automation/bugs/open/BUG-{NNN}.md`，确认：
- BUG 状态为 OPEN
- 复现步骤仍然有效（重新运行复现步骤确认）
- 如果无法复现 → 更新 BUG 状态为 CANNOT_REPRODUCE，移动至 `bugs/closed/`，退出

---

## 第二步：创建修复分支

```bash

git checkout master
git checkout -b bugfix/BUG-{NNN}-{short-desc}
```

`{short-desc}` 使用英文 3-5 词，以连字符连接。

---

## 第三步：根因分析

在 BUG 报告中追加根因分析：

```markdown
## 根因分析

{为什么会出现这个 BUG？是编码错误、逻辑遗漏、还是 API 变更？}

{如何定位到根因的？}
```

---

## 第四步：实施修复

1. 读取受影响的文件
2. 实现对预期行为的修复
3. 确保修复是最小变更（不引入无关改动）

---

## 第五步：运行测试

```bash
cd etf-strategies

# 1. 运行 BUG 关联的测试
python -m pytest tests/ -v -k "{关联的测试名}" --tb=short

# 2. 运行受影响的模块的全部测试
python -m pytest {受影响的测试文件} -v --tb=short

# 3. 运行全量回归测试（如果修改了核心模块）
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

如果任何测试失败 → 修复后重新运行，直到全部通过。

---

## 第六步：验证修复

在 BUG 报告中追加验证章节：

```markdown
## 验证

- [x] 复现步骤不再触发 BUG
- [x] 关联测试通过: {test_name}
- [x] 全量回归测试: {PASS}/{TOTAL} 通过
- [x] 无新增警告
```

---

## 第七步：提交修复

```bash


git add {修改的文件列表}
git commit -m "fix(BUG-{NNN}): {一句话修复描述}

- 正确性定义: {DEF-ID}
- 根因: {1-2行根因说明}
- 验证: test_{name} 通过

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 第八步：更新 BUG 状态

1. 更新 `bugs/open/BUG-{NNN}.md`：状态改为 FIXED，补充修复信息
2. 移动到 `bugs/closed/BUG-{NNN}.md`
3. 更新 `BUG_INDEX.md`：状态从 OPEN → FIXED，更新统计
4. 追加修复分支到分支索引表

---

## 第九步：合并建议

输出：
```
BUG-{NNN} 修复完成。

分支: bugfix/BUG-{NNN}-{short-desc}
修改文件: {列表}

建议操作:
- 如果修改涉及核心引擎/数据层: 建议先运行全量回测 (python run_backtest.py) 对比修复前后指标
- 如果修改仅在单个策略: 可以直接合并 (git checkout master && git merge bugfix/BUG-{NNN}-{short-desc})
- 如果修改涉及多个策略: 建议人工审查后再合并
```

---

## 异常处理

- 修复过程中发现新的关联问题 → 创建新的 BUG 报告，在当前 BUG 中标记 "Related: BUG-{new_NNN}"
- 修复导致其他测试失败 → 回滚修复，在 BUG 中记录失败的尝试，标记为 "修复受阻"
- 根因无法确定 → 标记为 "需要深度调试"，推荐人工介入
