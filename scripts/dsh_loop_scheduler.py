#!/usr/bin/env python3
"""DSH 自动化循环调度器 — 替代 Claude `/loop` 的驱动层。

由 Windows 任务计划每 7 分钟调用一次（任务名：dsh-automation-loop）。
到期任务用【独立 dsh headless 进程】执行（Start-Process 分离进程，跑完即退，
零上下文累积，崩溃自愈），与 Claude /loop 的隔离性等价且更强。

用法:
    python .claude/scripts/dsh_loop_scheduler.py          # 常规轮询（任务计划调用）
    python .claude/scripts/dsh_loop_scheduler.py --dry-run  # 只检查是否到期，不派发

依赖: task_scheduler.py（同目录）、dsh CLI（PATH 上的 dsh.ps1 垫片）、pwsh。
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# --- Paths ---
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
LOG_DIR = REPO_ROOT / ".dsh" / "logs"

sys.path.insert(0, str(SCRIPT_DIR))
import task_scheduler as ts  # noqa: E402  (复用调度/幂等/交易日逻辑)


def build_cmd(directive: str) -> list[str]:
    """构造派发命令：优先 node 直调 dsh bin（避开 cmd/pwsh 参数编码与执行策略问题）。

    本机无 PowerShell 7（pwsh），DSH 的 pwsh 工具实为 Windows PowerShell 5.1；
    且 dsh.ps1 垫片受执行策略限制。因此：
    1) node + bin.js（CreateProcess 传 UTF-16 参数，最稳）
    2) 兜底 powershell.exe + dsh.cmd
    """
    node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
    dsh_bin = Path(node).resolve().parent / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    if dsh_bin.exists():
        return [node, str(dsh_bin), "--profile", "headless", directive]
    ps = shutil.which("powershell") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    return [ps, "-NoProfile", "-Command", f'dsh.cmd --profile headless "{directive}"']


def build_directive(result: dict) -> str:
    """构造传给 dsh headless 的短指令（指向 prompt 文件，避免 32K argv 限制）。"""
    task_id = result["task_id"]
    prompt_file = result["prompt_file"]
    if result.get("self_managed_complete"):
        suffix = ""
    else:
        suffix = (
            " 任务完成后（无论成功与否），运行："
            f"python .claude/scripts/task_scheduler.py --complete {task_id}"
        )
    return f"执行 {prompt_file} 的全部内容。{suffix}"


def build_env() -> dict:
    """构造 headless 子进程环境：继承父环境并注入 OpenViking 记忆 peer 作用域。

    定时任务 agent 通过 @openviking/dsh-memory-plugin 使用记忆；所有任务会话
    统一归入 xiaoman peer（与 dashboard 小满融合），且 recall 隔离在本 peer
    （OPENVIKING_RECALL_PEER_SCOPE=actor），避免互相污染。
    """
    env = dict(os.environ)
    env["OPENVIKING_PEER_ID"] = "xiaoman"
    env["OPENVIKING_RECALL_PEER_SCOPE"] = "actor"
    return env


def dispatch(result: dict) -> str:
    """以独立 headless 进程派发任务，返回日志文件路径。

    静默关键（Windows）：不能只用 CREATE_NO_WINDOW——它只让 node 本身无窗口，
    但 headless 内部再 spawn 的 python 取数子进程会因父进程无控制台而被 Windows
    分配【新的控制台窗口】（实测 MainWindowHandle 非 0，即弹窗）。
    正确做法：STARTUPINFO + STARTF_USESHOWWINDOW + SW_HIDE，让 node 持有一个
    【隐藏的控制台】，其后代子进程继承该隐藏控制台 → 全部静默（实测为 0）。
    """
    task_id = result["task_id"]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logfile = LOG_DIR / f"{task_id}-{stamp}.log"
    directive = build_directive(result)
    cmd = build_cmd(directive)
    # 隐藏控制台而非禁用控制台：CREATE_NEW_PROCESS_GROUP 保持进程组隔离（Ctrl+C 不传播），
    # 后代继承隐藏控制台 → headless 内部 spawn 的工具子进程（python 取数等）不再弹窗。
    flags = subprocess.CREATE_NEW_PROCESS_GROUP
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    with open(logfile, "w", encoding="utf-8") as out:
        subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            env=build_env(),
            creationflags=flags,
            startupinfo=startupinfo,
        )
    return str(logfile)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    result = ts.check()
    if not result.get("should_run"):
        return 0
    task_id = result["task_id"]
    if dry_run:
        # 纯检查：不修改任何状态
        print(json.dumps({"would_run": task_id, "prompt_file": result["prompt_file"]},
                         ensure_ascii=False))
        return 0
    # 先标记完成再派发（防重复；失败则下个调度窗口自动重试）
    ts.complete(task_id)
    ts.mark_running(task_id)
    logfile = dispatch(result)
    print(json.dumps({"dispatched": task_id, "log": logfile}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
