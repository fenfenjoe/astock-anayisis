"""cloud_snapshot.py — SQLite 一致性快照（供 cloud_sync.ps1 调用）.

用 sqlite3 backup API 生成一致性快照（WAL 模式下直接 copy 主文件会不一致）。
用法: python cloud_snapshot.py <src_db> <dst_snapshot> [src_db2 dst2 ...]
"""
import sqlite3
import sys


def snapshot(src: str, dst: str) -> None:
    s = sqlite3.connect(src)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)  # 一致性备份（含未 checkpoint 的 WAL 内容）
    finally:
        d.close()
        s.close()


def main() -> None:
    pairs = sys.argv[1:]
    if len(pairs) % 2 != 0:
        print("usage: cloud_snapshot.py <src> <dst> [src dst ...]", file=sys.stderr)
        sys.exit(2)
    for i in range(0, len(pairs), 2):
        src, dst = pairs[i], pairs[i + 1]
        try:
            snapshot(src, dst)
            print(f"ok: {src} -> {dst}")
        except Exception as e:
            print(f"fail: {src}: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
