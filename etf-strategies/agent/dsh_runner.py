"""dsh_runner.py — 通过 dsh headless 执行小满任务（Agent 2 = dsh --profile xiaoman）.

替代原 llm.py 直连通道：一切 LLM 生成走 dsh，凭据统一由 dsh 管理
（本地 ~/.dsh/.credentials.yaml / Docker 环境变量 DEEPSEEK_API_KEY）——key 单点。

定位/执行模式照抄 dashboard/scheduler.py 的 _find_dsh/_exec_dsh：
Windows 直接调 node + @deepseek-ai/dsh/lib/bin.js（规避 dsh.ps1 wrapper），
任务为单字符串 positional（headless 会 join）。
"""
import os
import shutil
import subprocess
from pathlib import Path

from agent import config

DEFAULT_PROFILE = "xiaoman"

# OpenViking 隔离（②）：小满任务显式声明 actor peer + 按 actor 隔离召回，
# 与报告 Agent（headless，不设这些变量 → 默认 peer）记忆互不混淆。
XIAOMAN_OV_ENV = {
    "OPENVIKING_PEER_ID": "xiaoman",
    "OPENVIKING_RECALL_PEER_SCOPE": "actor",
}


class DshRunnerError(Exception):
    """dsh 执行失败（未找到/超时/非零退出）。"""


def find_dsh_bin():
    """返回 (node_exe, dsh_bin.js) 或 None（与 scheduler._find_dsh 同构）。

    候选：which node 同目录 + nvm 各版本目录。
    """
    candidates: list[tuple[Path, Path]] = []
    node = shutil.which("node")
    if node and Path(node).exists():
        node_p = Path(node)
        candidates.append((node_p, node_p.resolve().parent / "node_modules"
                           / "@deepseek-ai" / "dsh" / "lib" / "bin.js"))
    nvm_dir = Path.home() / "AppData" / "Roaming" / "nvm"
    if nvm_dir.exists():
        for bin_js in sorted(
                nvm_dir.glob("*/node_modules/@deepseek-ai/dsh/lib/bin.js")):
            ver_dir = bin_js.parents[4]  # .../nvm/{ver}/node_modules/... → {ver}
            node_exe = ver_dir / "node.exe"
            if node_exe.exists():
                candidates.append((node_exe, bin_js))
    for node_exe, bin_js in candidates:
        if node_exe.exists() and bin_js.exists():
            return (node_exe, bin_js)
    return None


def run_task(task, profile=DEFAULT_PROFILE, cwd=None, timeout=None,
             run=None, env=None):
    """执行一个 dsh headless 任务 → (status, output)。

    status: success | not_found | timeout | failed。
    task: directive 文本（人设由 profile 注入，task 只含业务内容）。
    env: 子进程环境变量覆盖；None 时默认注入小满的 OpenViking 隔离变量。
    run: 依赖注入 subprocess.run（测试 mock 用）。
    """
    run = run or subprocess.run
    found = find_dsh_bin()
    if found is None:
        return "not_found", "未找到 dsh（node + @deepseek-ai/dsh）。请安装 DSH。"
    node_exe, bin_js = found
    cmd = [str(node_exe), str(bin_js), "--profile", profile, task]
    timeout = timeout or config.DSH_TIMEOUT_SECONDS
    proc_env = os.environ.copy()
    proc_env.update(env if env is not None else XIAOMAN_OV_ENV)
    try:
        proc = run(cmd, cwd=str(cwd or config.REPO_ROOT),
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=timeout, env=proc_env)
    except subprocess.TimeoutExpired:
        return "timeout", f"dsh 执行超时（>{timeout}s）"
    except OSError as e:
        return "failed", f"dsh 启动失败: {e}"
    if proc.returncode != 0:
        return "failed", (proc.stderr or proc.stdout or "").strip()
    return "success", (proc.stdout or "").strip()
