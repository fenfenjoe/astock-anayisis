#!/usr/bin/env python3
"""一键同步：把 .claude/skills/ 的 8 个原始 skill 覆盖到 .dsh/skills/。

用途：用户在 Claude 侧更新了 skill（如 a-stock-data 修复端点），跑本脚本
即可让 DSH 侧拿到最新版。只同步两侧同名的 8 个原始 skill 目录；
不动 .dsh/skills/ 下 DSH 独有的内容（18 个命令转换版 + dev-workflow）。

用法:
    python .claude/scripts/sync_claude_skills.py            # 同步（打印差异）
    python .claude/scripts/sync_claude_skills.py --dry-run  # 只看差异，不覆盖
"""

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / ".claude" / "skills"
DST = REPO_ROOT / ".dsh" / "skills"

# 只同步这些原始 skill（与 DST 中同名目录一一对应）
SHARED = {
    "a-stock-data", "daily-review-harness", "design-critique",
    "design-explore", "frontend-design", "quant-strategy-discovery",
    "testing", "ui-ux-pro-max",
}


def main() -> int:
    dry = "--dry-run" in sys.argv
    if not SRC.exists():
        print(f"source missing: {SRC}")
        return 1
    DST.mkdir(parents=True, exist_ok=True)
    changed = []
    for name in sorted(SHARED):
        src_dir = SRC / name
        if not (src_dir / "SKILL.md").exists():
            print(f"skip {name}: no SKILL.md in source")
            continue
        dst_dir = DST / name
        if not dst_dir.exists() or not _same(src_dir / "SKILL.md", dst_dir / "SKILL.md"):
            changed.append(name)
            if not dry:
                if dst_dir.exists():
                    shutil.rmtree(dst_dir)
                shutil.copytree(src_dir, dst_dir)
    if changed:
        print(("(dry-run) " if dry else "") + "待同步: " + ", ".join(changed))
    else:
        print("两侧一致，无需同步")
    return 0


def _same(a: Path, b: Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(main())
