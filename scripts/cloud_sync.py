"""cloud_sync.py — 数据云同步（火山引擎 TOS，S3 兼容，boto3）.

模型：TOS 权威持久层 ⇄ 本地工作副本。
- 上传（默认）：SQLite 一致性快照 / 报告 / 持仓 / 日志 / OpenViking 数据
- 下载（--download）：从 TOS 恢复本地工作副本（报告/日志纯下载；SQLite/持仓/OpenViking 拉最新）

配置（机器特定，勿提交）——优先环境变量，其次 scripts/config/cloud.json：
  CLOUD_AK / CLOUD_SK / CLOUD_ENDPOINT / CLOUD_BUCKET / CLOUD_REGION

用法：
  python scripts/cloud_sync.py                  # 上传
  python scripts/cloud_sync.py --download       # 恢复（拉取到本地工作路径）
  python scripts/cloud_sync.py --dry-run        # 试跑（上传/下载均打印不执行）
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
DAILY_REVIEW = REPO_ROOT / "my_doc" / "每日复盘"

CONFIG_FILE = SCRIPT_DIR / "config" / "cloud.json"
DEFAULT_ENDPOINT = "https://tos-s3-cn-beijing.volces.com"  # S3 兼容端点
DEFAULT_BUCKET = "astock-data"

# 上传映射：本地路径 -> 云前缀；下载时按前缀回填同一本地路径
SYNC_MAP = [
    (ETF_DIR / "report", "report"),
    (DAILY_REVIEW / "reports", "daily-reports"),
    (ETF_DIR / "automation" / "logs", "logs/etf"),
    (DAILY_REVIEW / "harness" / "automation" / "logs", "logs/harness"),
    # 持仓权威文件（单文件，walk 即处理）
    (DAILY_REVIEW / "每日调仓.md", "holdings/每日调仓.md"),
    (DAILY_REVIEW / "harness" / "config" / "持仓.md", "holdings/持仓.md"),
]

# 需要一致性快照的 SQLite（下载时回填到工作路径）
SQLITE_DBS = [
    (ETF_DIR / "dashboard" / "data" / "cache.db", "cache.db"),
    (ETF_DIR / "agent" / "data" / "agent.db", "agent.db"),
]
SQLITE_PREFIX = "sqlite/"


def load_config():
    cfg = {
        "ak": os.environ.get("CLOUD_AK", ""),
        "sk": os.environ.get("CLOUD_SK", ""),
        "endpoint": os.environ.get("CLOUD_ENDPOINT", DEFAULT_ENDPOINT),
        "bucket": os.environ.get("CLOUD_BUCKET", DEFAULT_BUCKET),
        "region": os.environ.get("CLOUD_REGION", "cn-beijing"),
    }
    if CONFIG_FILE.exists():
        try:
            f = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in f.items() if v})
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def _client(cfg):
    try:
        import boto3
        from botocore.client import Config
    except ImportError:
        print("错误：需要 boto3。安装：python -m pip install --user boto3", file=sys.stderr)
        sys.exit(2)
    return boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        region_name=cfg["region"],
        aws_access_key_id=cfg["ak"],
        aws_secret_access_key=cfg["sk"],
        config=Config(s3={"addressing_style": "virtual"}, retries={"max_attempts": 3}),
    )


def sqlite_snapshot(src: Path) -> Path | None:
    """一致性快照（WAL 下直接 copy 主文件会不一致）。

    目标库强制 journal_mode=DELETE：WAL 模式的快照无法被 sqlite3
    deserialize() 载入（严格零本地内存库恢复依赖非 WAL 快照）。
    """
    if not src.exists():
        return None
    snap_dir = SCRIPT_DIR / ".snapshots" / datetime.now().strftime("%Y%m%d-%H%M%S")
    snap_dir.mkdir(parents=True, exist_ok=True)
    dst = snap_dir / src.name
    s = sqlite3.connect(str(src))
    d = sqlite3.connect(str(dst))
    try:
        d.execute("PRAGMA journal_mode=DELETE")
        s.backup(d)
    finally:
        d.close()
        s.close()
    return dst


def list_prefix(s3, bucket, prefix):
    """列出前缀下全部 key（翻页）。"""
    keys = []
    token = None
    while True:
        kw = dict(Bucket=bucket, Prefix=prefix)
        if token:
            kw["ContinuationToken"] = token
        r = s3.list_objects_v2(**kw)
        keys += [o["Key"] for o in r.get("Contents", [])]
        if r.get("IsTruncated"):
            token = r.get("NextContinuationToken")
        else:
            break
    return keys


def latest_sqlite_snapshot(s3, bucket):
    """返回 {本地文件名: 云key} —— sqlite/<最新时间戳>/{cache.db, agent.db}。"""
    keys = list_prefix(s3, bucket, SQLITE_PREFIX)
    if not keys:
        return {}
    by_ts = {}
    for k in keys:
        rel = k[len(SQLITE_PREFIX):]
        if "/" not in rel:
            continue
        ts, name = rel.split("/", 1)
        by_ts.setdefault(ts, {})[name] = k
    if not by_ts:
        return {}
    latest_ts = max(by_ts)
    return by_ts[latest_ts]


def upload_mode(cfg, s3, bucket, dry_run):
    ok_all = True

    def upload(local: Path, key: str):
        nonlocal ok_all
        if dry_run:
            print(f"[dry-run] {key}")
            return
        try:
            s3.upload_file(str(local), bucket, key)
            print(f"ok: {key}")
        except Exception as e:
            print(f"FAIL: {key}: {e}", file=sys.stderr)
            ok_all = False

    # 1. SQLite 一致性快照 → sqlite/<stamp>/
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for src, name in SQLITE_DBS:
        snap = sqlite_snapshot(src)
        if snap:
            upload(snap, f"{SQLITE_PREFIX}{stamp}/{name}")
            if not dry_run:
                snap.unlink(missing_ok=True)

    # 2. 目录/文件增量（walk）
    for local, prefix in SYNC_MAP:
        if not local.exists():
            print(f"skip: {local} (not exist)")
            continue
        for f in sorted(local.rglob("*")) if local.is_dir() else [local]:
            if not f.is_file():
                continue
            rel = f.relative_to(local).as_posix() if local.is_dir() else f.name
            upload(f, f"{prefix}/{rel}")

    # 3. 日志零持久：上传成功后清空本地日志（云已存档；配置 LOGS_PURGE_LOCAL=0 关闭）
    if os.environ.get("LOGS_PURGE_LOCAL", "1") == "1" and ok_all:
        for local, prefix in SYNC_MAP:
            if prefix.startswith("logs/") and local.is_dir() and local.exists():
                for f in local.rglob("*"):
                    if f.is_file():
                        try:
                            f.unlink()
                        except OSError:
                            pass
                print(f"本地日志已清空（云端存档）: {prefix}")

    print("上传完成。" if ok_all else "上传部分失败，见上。")
    return 0 if ok_all else 1


def download_mode(cfg, s3, bucket, dry_run):
    ok_all = True

    def download(key: str, dest: Path):
        nonlocal ok_all
        if dry_run:
            print(f"[dry-run] {key} -> {dest}")
            return
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(dest))
            print(f"ok: {key} -> {dest}")
        except Exception as e:
            print(f"FAIL: {key}: {e}", file=sys.stderr)
            ok_all = False

    # 1. SQLite 最新快照 → 工作 DB
    latest = latest_sqlite_snapshot(s3, bucket)
    for src, name in SQLITE_DBS:
        key = latest.get(name)
        if key:
            download(key, src)
        else:
            print(f"skip: 云端无 sqlite 快照 {name}")

    # 2. 各前缀回填
    for local, prefix in SYNC_MAP:
        keys = list_prefix(s3, bucket, prefix + "/")
        if not keys:
            print(f"skip: 云端无 {prefix}/")
            continue
        for k in keys:
            rel = k[len(prefix) + 1:]
            download(k, local / rel)

    print("恢复完成。" if ok_all else "恢复部分失败，见上。")
    return 0 if ok_all else 1


def main():
    ap = argparse.ArgumentParser(description="数据云同步（TOS）")
    ap.add_argument("--download", action="store_true", help="从 TOS 恢复本地（默认是上传）")
    ap.add_argument("--dry-run", action="store_true", help="只打印不执行")
    args = ap.parse_args()

    cfg = load_config()
    if not cfg["ak"] or not cfg["sk"]:
        print("错误：未配置 CLOUD_AK/CLOUD_SK。设置环境变量或 scripts/config/cloud.json"
              "（火山控制台 → 访问控制 → AccessKey）", file=sys.stderr)
        sys.exit(2)

    s3 = _client(cfg)
    bucket = cfg["bucket"]
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"桶可用: {bucket} @ {cfg['endpoint']} (region={cfg['region']})")
    except Exception as e:
        print(f"警告：head_bucket 失败：{e}", file=sys.stderr)

    if args.download:
        return download_mode(cfg, s3, bucket, args.dry_run)
    return upload_mode(cfg, s3, bucket, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
