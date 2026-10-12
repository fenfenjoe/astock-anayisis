"""
同步小满 persona — P1（自进化框架：小满解耦）

从单一事实源 ~/.dsh/personas/xiaoman/persona.md 提取 RUNTIME 标记块，
重写运行时配置 ~/.dsh/profiles/xiaoman/cordis.patch.yml 的 config.persona。

背景：dsh system-prompt 的 persona 是纯字符串（z.string()，不支持文件路径加载），
所以"文件引用模式"落地为：源文件上移 + 本脚本从源文件重生成内联 persona。

用法：
    python scripts/sync_xiaoman_persona.py            # 同步（自动备份）
    python scripts/sync_xiaoman_persona.py --dry-run  # 预览不写
    python scripts/sync_xiaoman_persona.py --check    # 检查是否一致（exit 0=一致，1=不一致）

安全：
    - 改前自动备份 cordis.patch.yml → cordis.patch.yml.bak
    - 幂等：重复运行结果一致
    - --check 用于 CI / 门禁
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

USER_HOME = Path.home()
PERSONA_SOURCE = USER_HOME / ".dsh" / "personas" / "xiaoman" / "persona.md"
PROFILE_PATCH = USER_HOME / ".dsh" / "profiles" / "xiaoman" / "cordis.patch.yml"

RUNTIME_START = "<!-- RUNTIME:START -->"
RUNTIME_END = "<!-- RUNTIME:END -->"


def extract_runtime_persona(source_text: str) -> str:
    """从 persona.md 提取 RUNTIME 标记之间的内容（含首行"你是「小满」"）。"""
    start = source_text.find(RUNTIME_START)
    end = source_text.find(RUNTIME_END)
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"persona.md 缺少 RUNTIME 标记（{RUNTIME_START} / {RUNTIME_END}）")
    body = source_text[start + len(RUNTIME_START):end]
    # 去掉首尾空行，保持内部缩进
    return body.strip("\n") + "\n"


def _indent_persona_block(persona: str, indent: str) -> str:
    """把 persona 文本转成 YAML 块内缩进行（每行前缀 indent）。"""
    return "".join(f"{indent}{line}\n" for line in persona.split("\n"))


def build_new_patch(patch_text: str, persona: str) -> str:
    """在现有 cordis.patch.yml 中替换 system-prompt 的 config.persona 块。

    识别 `- id: system-prompt` 段内的 `    persona: |`，替换其后续缩进行直到
    第一个非 6 空格缩进的行（保留顶格注释/后续段）。其他段保持不变。
    """
    marker = "    persona: |"
    idx = patch_text.find(marker)
    if idx == -1:
        raise ValueError("cordis.patch.yml 找不到 `    persona: |` 块")
    after = idx + len(marker)
    # 逐行找 persona 块结尾：persona 内容行缩进为 6 空格（"      ..."）；
    # 空行属于块内；顶格注释（#）或 `- id:` 或任何非 6 空格行 = 块外。
    lines = patch_text[after:].split("\n")
    consumed = 0
    for line in lines:
        stripped = line.strip()
        if stripped == "":
            consumed += 1
            continue
        if line.startswith("      "):
            consumed += 1
            continue
        break  # 顶格注释 / 新段 / 其他 → persona 块结束
    block_end = after + sum(len(l) + 1 for l in lines[:consumed])
    new_block = marker + "\n" + _indent_persona_block(persona, "      ")
    return patch_text[:idx] + new_block + patch_text[block_end:]


def current_persona(patch_text: str) -> str:
    """从现有 patch 提取当前 persona 文本（用于 diff）。"""
    marker = "    persona: |"
    idx = patch_text.find(marker)
    if idx == -1:
        return ""
    after = idx + len(marker)
    next_seg = patch_text.find("- id:", after)
    if next_seg == -1:
        next_seg = len(patch_text)
    block = patch_text[after:next_seg]
    lines = []
    for line in block.split("\n"):
        if line.startswith("      "):
            lines.append(line[6:])
        elif line.strip() == "":
            lines.append("")
        else:
            break
    return "\n".join(lines).strip("\n") + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="同步小满 persona 到运行时配置")
    ap.add_argument("--dry-run", action="store_true", help="预览不写")
    ap.add_argument("--check", action="store_true", help="检查是否一致（0=一致 1=不一致）")
    args = ap.parse_args()

    if not PERSONA_SOURCE.exists():
        print(f"[ERROR] 源文件不存在: {PERSONA_SOURCE}", file=sys.stderr)
        return 2
    if not PROFILE_PATCH.exists():
        print(f"[ERROR] 目标文件不存在: {PROFILE_PATCH}", file=sys.stderr)
        return 2

    source_text = PERSONA_SOURCE.read_text(encoding="utf-8")
    patch_text = PROFILE_PATCH.read_text(encoding="utf-8")

    persona = extract_runtime_persona(source_text)
    new_patch = build_new_patch(patch_text, persona)
    cur = current_persona(patch_text)

    if cur == persona:
        print("[OK] persona 已同步（无差异）")
        return 0

    if args.check:
        print("[CHECK] persona 不一致，需要同步")
        print("--- 当前 persona 尾部 ---")
        print(cur[-200:])
        return 1

    if args.dry_run:
        print("[DRY-RUN] 将同步以下内容（未写入）:")
        print(f"  源: {PERSONA_SOURCE}")
        print(f"  目标: {PROFILE_PATCH}")
        print(f"  persona 长度: {len(cur)} -> {len(persona)}")
        return 0

    # 备份
    bak = PROFILE_PATCH.with_suffix(".yml.bak")
    bak.write_text(patch_text, encoding="utf-8")
    PROFILE_PATCH.write_text(new_patch, encoding="utf-8")
    print(f"[OK] 已同步 persona 到 {PROFILE_PATCH}")
    print(f"[BAK] 备份: {bak}")
    print(f"      persona 长度: {len(cur)} -> {len(persona)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
