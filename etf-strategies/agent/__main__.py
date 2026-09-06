"""python -m agent — 拟人 Agent「小满」常驻进程入口.

独立于 dashboard Web 存活（方案 §5.4）：崩溃看门狗由外层（docker/systemd）
负责重启；进程内 AgentLoop 自愈单轮异常。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 加载 etf-strategies/.env（DB_MODE 等在 agent.db 模块 import 前生效）
try:
    from load_env import load_env_file
    load_env_file()
except ImportError:
    pass

from agent import db as agent_db
from agent.core import lifecycle


def main():
    print("[agent] 小满常驻进程启动（tick 间隔见 config）")
    # ── 初始化 agent.db：file 模式建表/迁移；memory 模式在此从 TOS 载入最新快照，
    #    保证台账/会话在每次启动后都能看到云端最新数据（含上次登录产生的内容）──
    try:
        agent_db.init_db()
    except Exception as e:
        print(f"[agent]   WARNING: agent.db init failed: {e}")
    # ── 云恢复：CLOUD_RESTORE_ON_START=1 时先拉取 TOS 最新数据 ──
    import os
    import subprocess
    if os.environ.get("CLOUD_RESTORE_ON_START", "").lower() in ("1", "true"):
        print("[agent] Restoring data from cloud (TOS)...")
        try:
            repo = Path(__file__).resolve().parent.parent.parent
            r = subprocess.run(
                [sys.executable, "scripts/cloud_sync.py", "--download"],
                cwd=str(repo), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=600)
            print(f"[agent]   restore exit={r.returncode}: {(r.stdout or '')[-200:]}")
        except Exception as e:
            print(f"[agent]   WARNING: cloud restore failed: {e}")
    loop = lifecycle.AgentLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("[agent] 收到退出信号，停止")


if __name__ == "__main__":
    main()
