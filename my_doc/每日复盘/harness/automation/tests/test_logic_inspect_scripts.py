"""
BUG-010 回归测试 — auto_logic_inspect.md 检查脚本可执行性

背景: 2026-08-27 逻辑巡检发现 auto_logic_inspect.md 中 C1/C2/C3 的
`f = 'f'my_doc/...''` 为 SyntaxError（编译即失败），C4/D2 的 `python -c` 缺
`-X utf8` 导致 Windows GBK 下读取 UTF-8 的 task_state.json 报
UnicodeDecodeError（误报"文件不存在/读取失败"）。

本测试保证 prompt 内检查脚本满足:
1. C1/C2/C3 的 Python 源码语法合法（可 compile）
2. C4/D2 的命令含 `-X utf8`（UTF-8 模式，规避 Windows GBK 默认编码）
3. C4/D2 按 prompt 原样可真实执行且不崩溃（exit 0）
"""

import re
import subprocess
import sys
from pathlib import Path

PROMPT = Path(__file__).resolve().parent.parent / "prompts" / "auto_logic_inspect.md"
# 仓库根目录（prompt 内脚本以相对路径引用 my_doc/...，需以仓库根为 cwd）
REPO_ROOT = Path(__file__).resolve().parents[5]

TARGETS_SYNTAX = ("C1", "C2", "C3")  # 引号语法缺陷段
TARGETS_UTF8 = ("C4", "D2")          # 缺 -X utf8 段


def _section_block(section: str) -> str:
    """提取 `### {section}:` 到下一个 `### ` 标题之间的原文"""
    text = PROMPT.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith(f"### {section}:"):
            start = i
            break
    assert start is not None, f"auto_logic_inspect.md 中不存在 {section} 段"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("### "):
            end = j
            break
    return "\n".join(lines[start:end])


def _bash_cmd(section: str) -> str:
    """提取段内第一个 bash 代码块中的 `python ... -c "..."` 命令原文"""
    blk = _section_block(section)
    m = re.search(r'python (-X utf8 )?-c "(.*)"\s*2>&1', blk, re.S)
    assert m, f"{section} 段未找到 `python -c \"...\"` 命令"
    return "python " + (m.group(1) or "") + '-c "' + m.group(2) + '" 2>&1'


def _python_source(section: str) -> str:
    """提取 `python ... -c "..."` 内部的 Python 源码"""
    m = re.search(r'python (-X utf8 )?-c "(.*)"\s*2>&1', _section_block(section), re.S)
    assert m, f"{section} 段未找到 `python -c \"...\"` 命令"
    return m.group(2)


class TestSyntaxValid:
    """C1/C2/C3 的 Python 源码必须语法合法（BUG-010: 'f'my_doc/...'' 曾为 SyntaxError）"""

    def test_c1_c2_c3_compile(self):
        for sec in TARGETS_SYNTAX:
            src = _python_source(sec)
            # 必须可 compile；SyntaxError 会使检查脚本编译即失败
            compile(src, f"<auto_logic_inspect {sec}>", "exec")

    def test_report_path_uses_fstring(self):
        """报告路径必须用 f-string（f'...{today}...'），不得出现 'f' 拼接残留"""
        for sec in TARGETS_SYNTAX:
            src = _python_source(sec)
            assert "f'my_doc/每日复盘/reports/{today}/" in src, (
                f"{sec} 报告路径未使用 f-string 语法"
            )
            assert "'f'my_doc" not in src, f"{sec} 仍存在 'f' 引号拼接残留"


class TestUtf8Flag:
    """C4/D2 必须带 -X utf8，否则 Windows GBK 读 UTF-8 task_state.json 崩溃"""

    def test_c4_d2_has_utf8_flag(self):
        for sec in TARGETS_UTF8:
            cmd = _bash_cmd(sec)
            assert "-X utf8" in cmd, (
                f"{sec} 段缺少 `-X utf8`：Windows 默认 GBK 读取 UTF-8 "
                f"task_state.json 会 UnicodeDecodeError，导致误报"
            )

    def test_c4_d2_executes_without_crash(self):
        """按 prompt 原样执行 C4/D2，不得崩溃（exit code 0）"""
        for sec in TARGETS_UTF8:
            cmd = _bash_cmd(sec)
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(REPO_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
            assert proc.returncode == 0, (
                f"{sec} 段执行失败 (exit {proc.returncode})：脚本按原样不可运行"
            )
