"""cloud_store.py — TOS 对象读写抽象层测试（mock boto3，不连真实 TOS）。"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from botocore.exceptions import ClientError

from cloud_store import (bucket_name, delete_object, get_object, get_text,
                         invalidate, list_objects, put_object, put_text)


class FakeClient:
    def __init__(self):
        self.objects = {}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = bytes(Body)

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        contents = [{"Key": k} for k in self.objects if k.startswith(Prefix)]
        return {"Contents": contents, "IsTruncated": False}


@pytest.fixture(autouse=True)
def _fake_client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr("cloud_store._get_client", lambda: fake)
    monkeypatch.setattr("cloud_store._client", fake)
    monkeypatch.setattr("cloud_store._cache", {})
    return fake


def test_put_get_text_roundtrip():
    put_text("holdings/持仓.md", "可用金额：10000\n")
    assert get_text("holdings/持仓.md") == "可用金额：10000\n"


def test_get_missing_returns_none():
    assert get_object("no/such/key") is None
    assert get_text("no/such/key") is None


def test_put_overwrites():
    put_text("a/b.txt", "v1")
    put_text("a/b.txt", "v2")
    assert get_text("a/b.txt") == "v2"


def test_delete():
    put_text("x/y", "data")
    delete_object("x/y")
    assert get_object("x/y") is None


def test_list_prefix():
    put_text("report/a.html", "a")
    put_text("report/b.html", "b")
    put_text("logs/c.log", "c")
    keys = list_objects("report/")
    assert set(keys) == {"report/a.html", "report/b.html"}
    assert list_objects("nope/") == []


def test_cache_used_when_enabled():
    put_text("k/v", "hello")
    fake = _get_client_fixture()
    # 命中缓存后不再访问 client
    assert get_text("k/v", use_cache=True) == "hello"
    fake.objects.pop("k/v", None)  # 云端删了，缓存仍命中
    assert get_text("k/v", use_cache=True) == "hello"
    invalidate("k/v")
    assert get_text("k/v", use_cache=True) is None


def test_bucket_name_from_config(monkeypatch, tmp_path):
    cfg = tmp_path / "cloud.json"
    cfg.write_text(json_dumps({"bucket": "my-bucket"}), encoding="utf-8")
    monkeypatch.setattr("cloud_store.CONFIG_FILE", cfg)
    assert bucket_name() == "my-bucket"


def json_dumps(d):
    import json
    return json.dumps(d, ensure_ascii=False)


def _get_client_fixture():
    # 取当前 fixture 的 fake（简化：直接重查 monkeypatch 不可行，这里用模块级替换）
    import cloud_store
    return cloud_store._client
