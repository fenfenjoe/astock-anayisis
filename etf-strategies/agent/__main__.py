"""python -m agent — 拟人 Agent「小满」常驻进程入口.

完全独立于 Dashboard 运行，不再共享 agent.db 文件。
内嵌 HTTP API（端口默认 8020）+ 调度引擎 + 状态机 tick loop 全自主。
"""

import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from load_env import load_env_file

    load_env_file()
except ImportError:
    pass

from agent import db as agent_db
from agent.core import lifecycle


def _ensure_cloud():
    if not os.environ.get("AGENT_DB_BACKEND"):
        os.environ["AGENT_DB_BACKEND"] = "cloud"
        print(
            "[agent]   强制 AGENT_DB_BACKEND=cloud（Agent 独立运行不再支持 file 模式）"
        )


def main():
    api_port = int(os.environ.get("AGENT_API_PORT", "8020"))
    _ensure_cloud()

    print(f"[agent] 小满常驻进程启动（tick 间隔见 config，HTTP API 端口 {api_port}）")

    try:
        agent_db.init_db()
    except Exception as e:
        print(f"[agent]   WARNING: agent.db init failed: {e}")

    # 2026-09-14 架构调整：Agent 是定时任务唯一执行方。启动时回收僵尸 running 记录
    # （上次进程被中断遗留的"运行中"记录），等价于原 dashboard 的僵尸回收职责。
    try:
        from agent.core import scheduler_agent

        n = scheduler_agent.reconcile_zombies()
        if n:
            print(f"[agent]   回收 {n} 条中断遗留的 running 记录 → failed")
    except Exception as e:
        print(f"[agent]   WARNING: reconcile_zombies 失败（不影响启动）: {e}")

    try:
        from agent.core import reachability

        cache = reachability.ensure_reachability()
        n_ok = sum(1 for v in cache.values() if v.get("reachable"))
        print(f"[agent]   社交平台可访问性判定完成：{n_ok}/{len(cache)} 可达")
    except Exception as e:
        print(f"[agent]   WARNING: 社交平台可访问性判定失败（不影响启动）: {e}")

    try:
        from agent.core import notices

        created = notices.ensure_cookie_todos()
        if created:
            print(
                f"[agent]   已生成 {len(created)} 条 Cookie 待办（聊天页「📌 提示与待办」可见）"
            )
    except Exception as e:
        print(f"[agent]   WARNING: Cookie 待办生成失败（不影响启动）: {e}")

    def _start_api():
        print(f"[agent]   HTTP API 启动中...")
        from agent.api import run_api

        run_api(port=api_port)

    api_thread = threading.Thread(target=_start_api, daemon=True, name="agent-api")
    api_thread.start()

    loop = lifecycle.AgentLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("[agent] 收到退出信号，停止")


if __name__ == "__main__":
    main()
