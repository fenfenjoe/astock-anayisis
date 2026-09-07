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
    # ── 初始化 agent.db：file 模式建表/迁移；cloud 模式直接连云（见 agent/db.py USE_CLOUD）──
    try:
        agent_db.init_db()
    except Exception as e:
        print(f"[agent]   WARNING: agent.db init failed: {e}")
    loop = lifecycle.AgentLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("[agent] 收到退出信号，停止")


if __name__ == "__main__":
    main()
