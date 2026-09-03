"""etf-strategies/cloud_store.py — TOS 对象存储读写抽象层（严格零本地）.

数据读写全部走云端（火山引擎 TOS，S3 兼容）：
- get_object / put_object / delete_object / list_objects
- 文本辅助 get_text / put_text
- 进程内内存缓存（可选，默认关闭；高频读场景再启用）

配置：环境变量 CLOUD_AK/SK/ENDPOINT/BUCKET/REGION 或 scripts/config/cloud.json
（与 cloud_sync.py 共用）。
"""
import json
import os
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

CONFIG_FILE = Path(__file__).resolve().parent.parent / "scripts" / "config" / "cloud.json"
DEFAULT_ENDPOINT = "https://tos-s3-cn-beijing.volces.com"
DEFAULT_BUCKET = "astock-data"

_client = None
_cache: dict[str, bytes] = {}


def _load_config() -> dict:
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


def bucket_name() -> str:
    return _load_config()["bucket"]


def _get_client():
    """懒加载 boto3 client（测试可 monkeypatch）。"""
    global _client
    if _client is None:
        cfg = _load_config()
        if not cfg["ak"] or not cfg["sk"]:
            raise RuntimeError(
                "未配置 CLOUD_AK/CLOUD_SK（环境变量或 scripts/config/cloud.json）")
        _client = boto3.client(
            "s3",
            endpoint_url=cfg["endpoint"],
            region_name=cfg["region"],
            aws_access_key_id=cfg["ak"],
            aws_secret_access_key=cfg["sk"],
            config=Config(
                connect_timeout=5,      # 连不上 5s 快速失败，不再无限阻塞
                read_timeout=20,        # 读响应超 20s 报错（慢网络/坏请求快速失败）
                s3={"addressing_style": "virtual"},
                retries={"max_attempts": 2}),
        )
    return _client


def invalidate(key: str) -> None:
    """清除缓存（写入后调用，保证读到新值）。"""
    _cache.pop(key, None)


def get_object(key: str, use_cache: bool = False) -> bytes | None:
    """读对象；不存在返回 None。use_cache=True 时命中进程内缓存。"""
    if use_cache and key in _cache:
        return _cache[key]
    try:
        r = _get_client().get_object(Bucket=bucket_name(), Key=key)
        data = r["Body"].read()
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "NoSuchKey":
            return None
        raise
    if use_cache:
        _cache[key] = data
    return data


def put_object(key: str, data: bytes) -> None:
    """写对象（覆盖）。写后清缓存。"""
    _get_client().put_object(Bucket=bucket_name(), Key=key, Body=data)
    invalidate(key)


def delete_object(key: str) -> None:
    """删除对象。"""
    _get_client().delete_object(Bucket=bucket_name(), Key=key)
    invalidate(key)


def list_objects(prefix: str) -> list[str]:
    """列出前缀下全部 key（翻页）。"""
    client = _get_client()
    bucket = bucket_name()
    keys, token = [], None
    while True:
        kw = dict(Bucket=bucket, Prefix=prefix)
        if token:
            kw["ContinuationToken"] = token
        r = client.list_objects_v2(**kw)
        keys += [o["Key"] for o in r.get("Contents", [])]
        if r.get("IsTruncated"):
            token = r.get("NextContinuationToken")
        else:
            break
    return keys


def get_text(key: str, use_cache: bool = False) -> str | None:
    data = get_object(key, use_cache=use_cache)
    return data.decode("utf-8") if data is not None else None


def put_text(key: str, text: str) -> None:
    put_object(key, text.encode("utf-8"))
