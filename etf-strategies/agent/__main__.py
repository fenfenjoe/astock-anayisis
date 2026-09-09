"""python -m agent — 拟人 Agent「小满」常驻进程入口.

独立于 dashboard Web 存活（方案 §5.4）：崩溃看门狗由外层（docker/systemd）
负责重启；进程内 AgentLoop 自愈单轮异常。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 加载 etf-strategies/.env（云后端/凭据 等在 agent.db 模块 import 前生效）
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
    # ── 首次启动可访问性判定（方案 v1.10 §9.4）：写平台可达性缓存，失败不阻塞启动 ──
    try:
        from agent.core import reachability

        cache = reachability.ensure_reachability()
        n_ok = sum(1 for v in cache.values() if v.get("reachable"))
        print(f"[agent]   社交平台可访问性判定完成：{n_ok}/{len(cache)} 可达")
    except Exception as e:
        print(f"[agent]   WARNING: 社交平台可访问性判定失败（不影响启动）: {e}")
    # ── 无 Cookie 的社交平台 → 生成"请提供 Cookie"待办（REQ-002，幂等去重）──
    try:
        from agent.core import notices

        created = notices.ensure_cookie_todos()
        if created:
            print(f"[agent]   已生成 {len(created)} 条 Cookie 待办（聊天页「📌 提示与待办」可见）")
    except Exception as e:
        print(f"[agent]   WARNING: Cookie 待办生成失败（不影响启动）: {e}")
    loop = lifecycle.AgentLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("[agent] 收到退出信号，停止")


if __name__ == "__main__":
    main()
