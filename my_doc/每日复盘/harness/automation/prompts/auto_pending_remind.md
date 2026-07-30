# 待确认事项提醒

> 定时任务: 每天 9:13, 11:13, 13:13, 15:13, 17:13, 19:13, 21:13 | /loop 调度
> 用途: 扫描 PENDING_CONFIRMATION.md 中待用户确认的事项，有则醒目提醒，无则静默跳过

---

## 任务角色

你是待确认事项提醒 Agent。每 2 小时检查一次是否有待用户确认的事项。

---

## 第一步：扫描待确认事项

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import re, os

pending_file = 'my_doc/每日复盘/harness/automation/PENDING_CONFIRMATION.md'
if not os.path.exists(pending_file):
    print('PENDING_FILE_MISSING')
    exit(0)

with open(pending_file, 'r', encoding='utf-8') as f:
    content = f.read()

# 提取 ## 待确认 表中的数据行（非表头/分隔行）
section = content.split('## 待确认')
if len(section) < 2:
    print('PENDING_COUNT:0')
    exit(0)

section_text = section[1].split('## ')[0] if '## ' in section[1] else section[1]
lines = [l for l in section_text.split('\n') if l.strip().startswith('|') and not l.strip().startswith('|--') and not l.strip().startswith('|---')]
# 排除表头行
data_rows = [l for l in lines if '日期' not in l and '来源BUG' not in l and '事项' not in l and '优先级' not in l]
count = len(data_rows)
print(f'PENDING_COUNT:{count}')
if count > 0:
    for row in data_rows:
        print(f'  {row.strip()}')
" 2>&1
```

---

## 第二步：判断

解析 Python 输出的 `PENDING_COUNT` 值：

- **`PENDING_COUNT:0` 或 `PENDING_FILE_MISSING`** → 静默跳过：
  ```
  OK | 无待确认事项
  ```

- **`PENDING_COUNT:N` (N > 0)** → 醒目输出：
  ```
  ⚠️ {N} 项待确认事项，请查看 PENDING_CONFIRMATION.md
  {逐行列出事项}
  ```

---

## 异常处理

| 异常 | 处理 |
|------|------|
| PENDING_CONFIRMATION.md 不存在 | 输出 `PENDING_FILE_MISSING`，静默跳过（首次运行前可能不存在） |
| Python 脚本执行失败 | 输出 `pending_remind error: {raw}`，不阻塞循环 |
