"""
跨实例互斥运行锁 — REQ-013

解决同日同任务双实例并行（调度链路 + 手动触发 / 多会话）导致的归档覆盖、重复写入、重复消耗。
与调度器 `task_scheduler.check_running()` 互补：后者只覆盖调度器派发实例，
本模块提供**跨实例可见**的文件锁，任何入口（调度/手动/多会话）统一经此获取。

设计要点：
- 锁文件放 `config/run_locks/{task}.json`（不写 reports/，不污染产出，REQ 约束②）
- 锁含 instance_id / pid / acquired_at / hostname / task（REQ 期望结果①⑤）
- stale 超时默认 45 分钟（与调度器 check_running 一致，REQ 期望结果①）
- takeover=True 手动抢占（REQ 期望结果②），release(force=True) 兜底清理
- 写入前置校验 check_modified 提供 mtime 冲突检测（REQ 期望结果④）

CLI 用法（供 prompt bash 步骤调用）：
  python lib/run_lock.py acquire --task evening_review
  python lib/run_lock.py acquire --task evening_review --takeover
  python lib/run_lock.py status --task evening_review
  python lib/run_lock.py release --task evening_review --instance <id>
  python lib/run_lock.py release --task evening_review --force
"""

import json
import os
import socket
from datetime import datetime, timedelta

LOCK_FILE_SUFFIX = '.json'
DEFAULT_TIMEOUT_MINUTES = 45


# ============================================================
# 内部辅助
# ============================================================

def _lock_path(task: str, lock_dir: str) -> str:
    return os.path.join(lock_dir, f"{task}{LOCK_FILE_SUFFIX}")


def _now_iso() -> str:
    return datetime.now().isoformat()


def _parse_acquired_at(lock: dict):
    """解析锁文件的 acquired_at，失败返回 None。"""
    raw = lock.get('acquired_at') if isinstance(lock, dict) else None
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


# ============================================================
# 纯函数：stale 判定
# ============================================================

def is_stale(lock: dict, timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES) -> bool:
    """判定锁是否 stale（超时 / 异常锁视为 stale，不永久阻塞，REQ 约束③）。

    lock: 锁信息 dict（须含 acquired_at，缺失/非法视为 stale）
    timeout_minutes: stale 超时分钟数，默认 45
    """
    acquired = _parse_acquired_at(lock)
    if acquired is None:
        return True  # 缺时间 / 无法解析 → 视为 stale（容错，防永久阻塞）
    return (datetime.now() - acquired) >= timedelta(minutes=timeout_minutes)


# ============================================================
# 锁文件读写
# ============================================================

def read_lock(task: str, lock_dir: str) -> dict | None:
    """读取锁文件内容；不存在 / 损坏 → None（容错，不抛异常）。"""
    path = _lock_path(task, lock_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _write_lock(task: str, lock_dir: str, instance_id: str, pid: int,
                hostname: str) -> None:
    os.makedirs(lock_dir, exist_ok=True)
    lock = {
        'task': task,
        'instance_id': instance_id,
        'pid': pid,
        'acquired_at': _now_iso(),
        'hostname': hostname,
    }
    with open(_lock_path(task, lock_dir), 'w', encoding='utf-8') as f:
        json.dump(lock, f, ensure_ascii=False, indent=2)


# ============================================================
# 获取 / 释放
# ============================================================

def acquire_lock(task: str, lock_dir: str, instance_id: str | None = None,
                 timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES,
                 takeover: bool = False) -> dict:
    """获取跨实例互斥锁。

    返回 {acquired, reason, lock, instance_id}：
      acquired=True:
        reason='acquired'   首次获取成功
        reason='stale_taken' 原锁已 stale，自动接管
        reason='takeover'   手动 takeover 强制接管
      acquired=False:
        reason='held'       已持锁（未 stale），第二实例显式退出

    instance_id: 缺省自动生成（pid@hostname-时间戳），prompt 日志可观测。
    takeover: True → 无视当前锁状态强制接管（REQ 期望结果②，手动优先级）。
    """
    if not instance_id:
        instance_id = f"{os.getpid()}@{socket.gethostname()}-{int(datetime.now().timestamp())}"

    existing = read_lock(task, lock_dir)

    if existing is not None and not takeover:
        if not is_stale(existing, timeout_minutes):
            return {
                'acquired': False,
                'reason': 'held',
                'lock': existing,
                'instance_id': instance_id,
            }
        # stale → 自动接管
        _write_lock(task, lock_dir, instance_id, os.getpid(), socket.gethostname())
        return {
            'acquired': True,
            'reason': 'stale_taken',
            'lock': {'task': task, 'instance_id': instance_id},
            'instance_id': instance_id,
        }

    if takeover:
        _write_lock(task, lock_dir, instance_id, os.getpid(), socket.gethostname())
        return {
            'acquired': True,
            'reason': 'takeover',
            'lock': {'task': task, 'instance_id': instance_id},
            'instance_id': instance_id,
        }

    _write_lock(task, lock_dir, instance_id, os.getpid(), socket.gethostname())
    return {
        'acquired': True,
        'reason': 'acquired',
        'lock': {'task': task, 'instance_id': instance_id},
        'instance_id': instance_id,
    }


def release_lock(task: str, lock_dir: str, instance_id: str | None = None,
                 force: bool = False) -> dict:
    """释放锁。

    返回 {released, reason}：
      released=True:  成功释放（reason='released' / 'force_released'）
      released=False: 无锁可释放（'no_lock'）/ 释放他人锁被拒（'not_owner'）
    """
    existing = read_lock(task, lock_dir)
    if existing is None:
        return {'released': False, 'reason': 'no_lock'}

    if force:
        os.remove(_lock_path(task, lock_dir))
        return {'released': True, 'reason': 'force_released'}

    if instance_id and existing.get('instance_id') != instance_id:
        return {'released': False, 'reason': 'not_owner'}

    os.remove(_lock_path(task, lock_dir))
    return {'released': True, 'reason': 'released'}


# ============================================================
# 写入前置校验（REQ 期望结果④）
# ============================================================

def check_modified(path: str, snapshot_mtime_ns: int | None) -> bool:
    """检测文件在读取后是否被他人修改（mtime 比对）。

    用于"读-改-写"前置校验：读文件时记录 st_mtime_ns，写回前调用本函数；
    返回 True = 文件被他人修改（需输出冲突告警并保留 .conflict 副本，不静默覆盖）。

    snapshot_mtime_ns: 读取时记录的 mtime_ns；None（首次写入前）→ 不判冲突。
    """
    if snapshot_mtime_ns is None:
        return False
    try:
        current = os.stat(path).st_mtime_ns
    except OSError:
        return True  # 文件被删除 → 视为修改（冲突）
    return current != snapshot_mtime_ns


def snapshot_mtime(path: str) -> int | None:
    """读取文件 mtime_ns（写入前置校验快照）；文件不存在 → None。"""
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


# ============================================================
# CLI 入口（供 prompt bash 步骤调用）
# ============================================================

def _default_lock_dir() -> str:
    """默认锁目录：harness/automation/config/run_locks/（REQ 约束②）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, '..', 'config', 'run_locks'))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description='跨实例互斥运行锁 (REQ-013)')
    sub = parser.add_subparsers(dest='command', required=True)

    p_acq = sub.add_parser('acquire', help='获取锁')
    p_acq.add_argument('--task', required=True)
    p_acq.add_argument('--lock-dir', default=_default_lock_dir())
    p_acq.add_argument('--instance', default=None)
    p_acq.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT_MINUTES)
    p_acq.add_argument('--takeover', action='store_true', help='强制接管（手动优先级）')
    p_acq.set_defaults(handler='acquire')

    p_rel = sub.add_parser('release', help='释放锁')
    p_rel.add_argument('--task', required=True)
    p_rel.add_argument('--lock-dir', default=_default_lock_dir())
    p_rel.add_argument('--instance', default=None)
    p_rel.add_argument('--force', action='store_true')
    p_rel.set_defaults(handler='release')

    p_st = sub.add_parser('status', help='查看锁状态')
    p_st.add_argument('--task', required=True)
    p_st.add_argument('--lock-dir', default=_default_lock_dir())
    p_st.set_defaults(handler='status')

    args = parser.parse_args(argv)

    if args.handler == 'acquire':
        result = acquire_lock(args.task, args.lock_dir, instance_id=args.instance,
                              timeout_minutes=args.timeout, takeover=args.takeover)
        if result['acquired']:
            print(f"LOCK_ACQUIRED task={args.task} instance={result['instance_id']} "
                  f"reason={result['reason']}")
            return 0
        lock = result.get('lock') or {}
        print(f"LOCK_HELD task={args.task} 检测到运行中实例 "
              f"{lock.get('instance_id', '?')}（{lock.get('acquired_at', '?')}），本次退出")
        return 1

    if args.handler == 'release':
        result = release_lock(args.task, args.lock_dir, instance_id=args.instance,
                              force=args.force)
        if result['released']:
            print(f"LOCK_RELEASED task={args.task} reason={result['reason']}")
            return 0
        print(f"LOCK_RELEASE_SKIP task={args.task} reason={result['reason']}")
        return 0 if result['reason'] == 'no_lock' else 1

    if args.handler == 'status':
        lock = read_lock(args.task, args.lock_dir)
        if lock is None:
            print(f"LOCK_FREE task={args.task}")
            return 0
        stale = is_stale(lock, args.timeout) if hasattr(args, 'timeout') else is_stale(lock)
        print(f"LOCK_HELD task={args.task} instance={lock.get('instance_id')} "
              f"acquired_at={lock.get('acquired_at')} pid={lock.get('pid')} "
              f"stale={stale}")
        return 0

    return 2


if __name__ == '__main__':
    raise SystemExit(main())
