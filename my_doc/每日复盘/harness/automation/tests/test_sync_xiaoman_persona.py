"""
sync_xiaoman_persona.py 测试 — P1 小满 persona 同步脚本（纯函数层）

覆盖: extract_runtime_persona / build_new_patch / current_persona 的
    幂等性 / 备份语义 / 注释保留 / 标记缺失容错
"""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[5] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from sync_xiaoman_persona import (
    RUNTIME_START,
    RUNTIME_END,
    extract_runtime_persona,
    build_new_patch,
    current_persona,
)

SOURCE_OK = f"""# 小满 Persona（单一事实源）

{RUNTIME_START}
你是「小满」，18± 的元气少女财经博主。
- 会带出自己沉淀的量化经验（复盘发现/操作纪律/吃过的亏）
{RUNTIME_END}

## 元信息（不注入运行时）
- 迭代历史：略
"""

PATCH_ORIGINAL = """# 小满运行时人设
- id: system-prompt
  config:
    persona: |
      旧版 persona 内容
      旧版第二行

# ── 模型路由（小满专属）──────────────────────────────
# 背景注释：这段注释绝不能丢
- id: settings
  config:
    path: !!js dshHomePath('profiles/xiaoman/settings.yaml')

- id: llm-pi-ai
  config:
    providers:
      volcengine: {}
"""


class TestExtractRuntimePersona:
    def test_extracts_between_markers(self):
        text = extract_runtime_persona(SOURCE_OK)
        assert "你是「小满」" in text
        assert "量化经验" in text
        assert "元信息" not in text  # RUNTIME 标记外的不进

    def test_missing_markers_raises(self):
        with pytest.raises(ValueError):
            extract_runtime_persona("# 无标记\n普通内容\n")


class TestBuildNewPatch:
    def test_replaces_persona_block_keeps_rest(self):
        persona = extract_runtime_persona(SOURCE_OK)
        new = build_new_patch(PATCH_ORIGINAL, persona)
        # persona 已替换
        assert "旧版 persona 内容" not in new
        assert "你是「小满」" in new
        # 注释保留（关键：不能被吃掉）
        assert "模型路由" in new
        assert "背景注释：这段注释绝不能丢" in new
        # 后续段保留
        assert "- id: settings" in new
        assert "- id: llm-pi-ai" in new
        assert "dshHomePath" in new

    def test_roundtrip_consistency(self):
        """build 后再提取 current 应等于写入的 persona（幂等基础）。"""
        persona = extract_runtime_persona(SOURCE_OK)
        new = build_new_patch(PATCH_ORIGINAL, persona)
        cur = current_persona(new)
        assert cur.strip("\n") == persona.strip("\n")

    def test_idempotent_second_build_same(self):
        """对已同步的 patch 再 build 一次，结果不变（幂等）。"""
        persona = extract_runtime_persona(SOURCE_OK)
        once = build_new_patch(PATCH_ORIGINAL, persona)
        twice = build_new_patch(once, persona)
        assert once == twice

    def test_missing_persona_marker_raises(self):
        with pytest.raises(ValueError):
            build_new_patch("- id: other\n  config: {}\n", "x")


class TestCurrentPersona:
    def test_extracts_current(self):
        cur = current_persona(PATCH_ORIGINAL)
        assert "旧版 persona 内容" in cur
        assert "旧版第二行" in cur

    def test_missing_marker_empty(self):
        assert current_persona("- id: other\n") == ""
