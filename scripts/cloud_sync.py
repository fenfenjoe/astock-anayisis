"""cloud_sync.py — 数据上云（火山引擎 TOS，S3 兼容，boto3）.

同步内容：SQLite 一致性快照 / 回测报告 / 每日复盘报告 / 日志 / OpenViking 数据。

配置（机器特定，勿提交）——优先环境变量，其次 scripts/config/cloud.json：
  CLOUD_AK       火山引擎 AccessKey
  CLOUD_SK       火山引擎 SecretKey
  CLOUD_ENDPOINT 默认 https://tos-cn-beijing.volces.com
  CLOUD_BUCKET   默认 astock-data

用法：python scripts/cloud_sync.py [--dry-run]
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
ETF_DIR = REPO_ROOT / "etf-strategies"

CONFIG_FILE = SCRIPT_DIR / "config" / "cloud.json"
DEFAULT_ENDPOINT = "https://tos-cn-beijing.volces.com"
DEFAULT_BUCKET = "astock-data"

# 同步映射：本地路径 -> 云桶内前缀
SYNC_MAP = [
    (ETF_DIR / "report", "report"),
    (REPO_ROOT / "my_doc" / "每日复盘" / "reports", "daily-reports"),
    (ETF_DIR / "automation" / "logs", "logs/etf"),
    (REPO_ROOT / "my_doc" / "每日复盘" / "harness" / "automation" / "logs", "logs/harness"),
    (REPO_ROOT / "data", "openviking"),
]

# 需要一致性快照的 SQLite
SQLITE_DBS = [
    (ETF_DIR / "dashboard" / "data" / "cache.db", "cache.db"),
    (ETF_DIR / "agent" / "data" / "agent.db", "agent.db"),
]


def load_config():
    cfg = {
        "ak": os.environ.get("CLOUD_AK", ""),
        "sk": os.environ.get("CLOUD_SK", ""),
        "endpoint": os.environ.get("CLOUD_ENDPOINT", DEFAULT_ENDPOINT),
        "bucket": os.environ.get("CLOUD_BUCKET", DEFAULT_BUCKET),
    }
    if CONFIG_FILE.exists():
        try:
            f = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in f.items() if v})
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def sqlite_snapshot(src: Path) -> Path | None:
    """VACUUM INTO 一致性快照（WAL 下直接 copy 主文件会不一致）。"""
    if not src.exists():
        return None
    snap_dir = SCRIPT_DIR / ".snapshots" / datetime.now().strftime("%Y%m%d-%H%M%S")
    snap_dir.mkdir(parents=True, exist_ok=True)
    dst = snap_dir / src.name
    s = sqlite3.connect(str(src))
    d = sqlite3.connect(str(dst))
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    return dst


def walk_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file():
            yield p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印将上传的文件，不真正上传")
    args = ap.parse_args()
    cfg = load_config()
    if not cfg["ak"] or not cfg["sk"]:
        print("错误：未配置 CLOUD_AK/CLOUD_SK。请设置环境变量或 scripts/config/cloud.json"
              "（从火山引擎控制台 → 访问控制 → AccessKey 获取）", file=sys.stderr)
        sys.exit(2)

    try:
        import boto3
        from botocore.client import Config
    except ImportError:
        print("错误：需要 boto3。安装：python -m pip install --user boto3", file=sys.stderr)
        sys.exit(2)

    s3 = boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["ak"],
        aws_secret_access_key=cfg["sk"],
        config=Config(s3={"addressing_style": "virtual"}, retries={"max_attempts": 3}),
    )
    bucket = cfg["bucket"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    def upload(local: Path, key: str):
        if args.dry_run:
            print(f"[dry-run] {key}")
            return True
        try:
            s3.upload_file(str(local), bucket, key)
            print(f"ok: {key}")
            return True
        except Exception as e:
            print(f"FAIL: {key}: {e}", file=sys.stderr)
            return False

    ok_all = True

    # 1. SQLite 一致性快照 → sqlite/<stamp>/
    for src, name in SQLITE_DBS:
        snap = sqlite_snapshot(src)
        if snap:
            ok_all &= upload(snap, f"sqlite/{stamp}/{name}")
            snap.unlink(missing_ok=True)  # 上传后删除本地临时快照（云端即存档）

    # 2. 目录增量同步（按 大小+时间 跳过未变更）
    for local, prefix in SYNC_MAP:
        if not local.exists():
            print(f"skip: {local} (not exist)")
            continue
        for f in walk_files(local):
            rel = f.relative_to(local).as_posix()
            ok_all &= upload(f, f"{prefix}/{rel}")

    print("完成。" if ok_all else "部分失败，见上。")


if __name__ == "__main__":
    main()
