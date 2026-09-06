"""小满 LIVE2D 桌宠前端一致性回归（模板挂载 / ID 契约 / 状态样式覆盖 / 事件契约）。

无需资产/外网：校验 dashboard.html 挂载点齐全、pet.js 引用的元素 ID 均存在、
pet.css 覆盖 pet.js 会设置的全部 data-state / data-posture、跨模块 CustomEvent
契约成立，以及 GET / 能渲染出桌宠挂载点（防模板被改坏）。

数据纪律：本测试只校验静态结构与事件契约，不涉及 A 股数据。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

BASE = Path(__file__).resolve().parent.parent
TEMPLATE = BASE / "dashboard" / "templates" / "dashboard.html"
PET_JS = BASE / "dashboard" / "static" / "js" / "pet.js"
PET_CSS = BASE / "dashboard" / "static" / "css" / "pet.css"
AGENT_JS = BASE / "dashboard" / "static" / "js" / "agent.js"
DASH_JS = BASE / "dashboard" / "static" / "js" / "dashboard.js"

PET_IDS = [
    "xm-pet", "xm-pet-canvas", "xm-pet-fallback", "xm-pet-scene",
    "xm-pet-bubble", "xm-pet-zzz", "xm-pet-modes",
    "xm-pet-btn-min", "xm-pet-btn-hide", "xm-pet-mini",
]
STATES = ["offline", "leave", "sleep", "slack", "working", "thinking"]  # unknown=初始默认态，无需专属规则
POSTURES = ["type", "code", "data", "read"]  # read=阅读态：隐藏非 LIVE2D 场景动画


def _text(p):
    return p.read_text(encoding="utf-8")


def test_template_serves_pet_mount():
    """GET / 渲染的 HTML 含桌宠挂载点与资源引用（防模板/静态路径被改坏）。"""
    from dashboard import app as app_mod
    client = TestClient(app_mod.app)   # 不 with：不触发 lifespan
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert 'id="xm-pet"' in html
    assert "/static/css/pet.css" in html
    assert "/static/js/pet.js" in html


def test_pet_ids_in_html():
    html = _text(TEMPLATE)
    for pid in PET_IDS:
        assert f'id="{pid}"' in html, f"dashboard.html 缺挂载点 #{pid}"


def test_pet_js_id_refs_exist_in_html():
    """pet.js 引用的元素 id（$('…') / getElementById('…') 两种写法）必须都在模板中。"""
    html = _text(TEMPLATE)
    js = _text(PET_JS)
    refs = set(re.findall(r"\$\('([^']+)'\)", js))
    refs |= set(re.findall(r"getElementById\('([^']+)'\)", js))
    assert refs, "pet.js 未解析到任何元素引用"
    missing = [r for r in refs if f'id="{r}"' not in html]
    assert not missing, f"pet.js 引用但模板缺失的 id: {missing}"


def test_pet_css_covers_states_and_postures():
    """pet.js 通过 data-state/data-posture 驱动的视觉态，CSS 必须全覆盖。"""
    css = _text(PET_CSS)
    for st in STATES:
        assert f'data-state="{st}"' in css, f"pet.css 缺 data-state={st} 样式"
    for p in POSTURES:
        assert f'data-posture="{p}"' in css, f"pet.css 缺 data-posture={p} 样式"
    # 无障碍/响应式降级
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (max-width: 899px)" in css


def test_event_contract_across_modules():
    """事件契约：
    - pet.js：收 xm:auth + xm:thinking，发 xm:status
    - agent.js：发 xm:thinking，收 xm:status（轮询已收敛，无自轮询）
    - dashboard.js：showApp/showLoginPage 双向发 xm:auth
    """
    pet = _text(PET_JS)
    agent = _text(AGENT_JS)
    dash = _text(DASH_JS)
    assert "xm:auth" in pet and "xm:thinking" in pet and "xm:status" in pet
    assert "xm:status" in agent and "xm:thinking" in agent
    assert dash.count("xm:auth") >= 2
    assert "authed: true" in dash and "authed: false" in dash
    # agent.js 不应再自建状态轮询（单一轮询源=pet.js）
    assert "setInterval(loadStatus" not in agent


def test_vendor_paths_match_layout():
    """pet.js 的 vendor 探测路径须与 fetch 脚本/README 约定布局一致。"""
    js = _text(PET_JS)
    for f in ["vendor/pixi.min.js",
              "vendor/live2dcubismcore.min.js",
              "vendor/pixi-live2d-display.min.js"]:
        assert f in js, f"pet.js 缺少 vendor 路径约定 {f}"
