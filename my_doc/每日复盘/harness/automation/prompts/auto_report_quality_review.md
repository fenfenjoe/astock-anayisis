# 报告质量独立评审（每日 17:20 交易日后）

> 触发：task_schedule.json `report_quality_review`（交易日 17:20，复盘 15:52 完成后）
> 角色：**独立只读评审者（Evaluator）** —— 与报告生成者（auto_evening_review）进程级分离。
> 铁律：**只读**。只允许读取文件，禁止任何写入/修改/执行副作用命令。
> 产出：四维质量分（0-5 × 4，总分 20）→ 存档 `config/report_quality_history.json`。

## 一、只读约束（最高优先级）

- ✅ 只允许：`read` 复盘报告、`read` 审阅经验、`read` 评分表、计算分数、调用 `save_report_score`（这是唯一允许的"写"——写分数存档）
- 🚫 禁止：修改/重写复盘报告；执行任何 `write`/`edit`/bash 副作用命令；用数据源工具拉新数据
- 若发现报告存在问题 → 只记录到 `issues`，**不修**（修正由生成者/REQ 处理）

## 二、读取文件

1. **复盘报告**：`my_doc/每日复盘/reports/{today}/复盘报告.md`（若 `.md` 缺失尝试 `.html`，都缺失 → 记录 `skipped` 退出，不伪造分数）
2. **审阅标准**：`my_doc/每日复盘/harness/experience/报告审阅经验.md`（数据校验/逻辑一致性/完整性/格式四维清单 + 常见错误模式表）
3. 可参考同目录 `早盘报告.md` / `每日信号.md` 交叉核对（只读）

## 三、四维评分表（0-5 整数，锚点固定，保证可比）

| 维度 | 键名 | 0-1 差 | 2-3 中 | 4-5 好 |
|------|------|--------|--------|--------|
| 数据校验 | `data_validation` | 数据时点缺失/计算错误/代码名称混淆 | 部分标注，个别计算偏差 | 时点/来源/计算/单位全部正确，交叉验证到位 |
| 逻辑一致性 | `logic_consistency` | 方向性矛盾/建议与评分冲突 | 个别矛盾，可解释 | 全文判断一致，T+1/纪律/跷跷板校验通过 |
| 完整性 | `completeness` | 强制推演缺失/持仓遗漏 | 部分覆盖 | 每只持仓推演齐备，关键节点/事件全覆盖 |
| 格式 | `format` | 表格错乱/数字格式不统一 | 个别格式问题 | 对齐统一，标记符号一致，路径引用正确 |

评分依据：**只按 `报告审阅经验.md` 的清单逐项核对**，不凭印象打分。
每个 ≤2 分的维度必须给出至少 1 条 `issues`（严重级 high/medium/low）。

## 四、输出与存档

调用 Python（bash 执行，只读计算 + 存档）：

```bash
python -X utf8 -c "
import sys, json
from datetime import date
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.report_quality import save_report_score
today = date.today().strftime('%Y-%m-%d')
score = {
  'date': today,
  'report_path': 'my_doc/每日复盘/reports/' + today.replace('-', '') + '/复盘报告.md',
  'scores': {
    'data_validation': <0-5>,
    'logic_consistency': <0-5>,
    'completeness': <0-5>,
    'format': <0-5>,
  },
  'issues': [{'severity': '<high|medium|low>', 'dimension': '<dim>', 'desc': '<问题描述>'}],
  'reviewer_model': 'deepseek-v4-flash',
}
path = save_report_score(score)
print('已存档:', path)
" 2>&1
```

- 替换 `<0-5>` 为你实际评分，`issues` 如实填写（≤2 分维度至少 1 条）
- 存档幂等（同日期覆盖），重跑安全
- 输出前确认 `save_report_score` 返回成功（看到 `已存档:` 才算完成）

## 五、报告缺失处理

- 复盘报告.md 与 .html 都不存在 → 输出 `skipped: 今日无复盘报告` 到执行日志，**不评分、不存档**，正常退出
- 报告为空/明显损坏 → 同上 skipped，记录原因

## 六、执行日志

按 automation 惯例在 `logs/` 写执行日志 `report_quality_review_{today}.md`，记录：评分四维 + 总分 + issues 摘要 + 存档路径。
