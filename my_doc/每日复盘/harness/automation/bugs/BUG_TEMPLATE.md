# BUG-{NNN}: {简要标题}

- **组件**: lib/ | tests/ | prompts/ | templates/ | config/
- **严重程度**: P0(紧急) | P1(高) | P2(中) | P3(低)
- **违反的正确性定义**: {如有，引用 etf-strategies/automation/config/ 或 harness 正确性定义}
- **状态**: OPEN
- **auto_fix_eligible**: true | false
  - 判定理由：{确定性修复=true / 涉及金融计算=false→MANUAL_REVIEW}
- **发现时间**: YYYY-MM-DDTHH:MM CST
- **发现方式**: 测试失败 | 代码巡检 | 复盘验证 | 回归测试 | 手动发现
- **来源 REQ**: {如 REQ-001，没有则写 N/A}
- **预期行为**: {应该发生什么}
- **实际行为**: {实际发生了什么}
- **复现步骤**:
  1. {步骤1}
  2. {步骤2}
- **受影响文件**:
  - `{path/to/file1}`（{改动说明}）
- **潜在影响**: {对自动化流水线/复盘/早盘分析的影响}
- **建议修复**: {简要修复方向}

## 测试证据
```
{粘贴 pytest 失败输出}
```

## 附注
- {额外说明}
