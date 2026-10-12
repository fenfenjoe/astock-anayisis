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
    "xm-pet", "xm-pet-canvas", "xm-pet-fallback",
    "xm-pet-bubble", "xm-pet-zzz", "xm-pet-modes",
    "xm-pet-btn-min", "xm-pet-mini",
]
STATES = ["offline", "leave", "sleep", "slack", "working", "thinking"]  # unknown=初始默认态，无需专属规则
# 注：data-posture 已随"场景层移除"退出 DOM 契约（posture 是 pet.js 内部状态变量，
# 不再驱动 CSS 动画场景）；此处不再断言 CSS 覆盖 data-posture。


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
    """pet.js 通过 data-state 驱动的视觉态，CSS 必须全覆盖。

    场景层已移除（posture 不再写 DOM），故只校验 data-state 全集。
    """
    css = _text(PET_CSS)
    for st in STATES:
        assert f'data-state="{st}"' in css, f"pet.css 缺 data-state={st} 样式"
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


def test_collapse_is_shrink_not_hide():
    """2026-10-10 改版契约：收起=缩小（仍展示），不再 display:none 隐藏。

    设计变更：原「收起/隐藏」双按钮合并为单个「收起」切换按钮，收起仅将桌宠
    transform 缩小（.is-min → scale），角色仍可见、LIVE2D 渲染循环不中断 →
    从根本上消除"隐藏(display:none)→召唤后头部被裁"的 bug 路径（渲染/布局状态
    不丢失），因此不再需要 retryLayout 这类召唤后补救机制。

    契约：
    1. 模板只有一个收起按钮（#xm-pet-btn-min），且无隐藏按钮（#xm-pet-btn-hide）
    2. pet.css 的 .is-min 用 transform 缩放而非 display:none
    3. pet.js 提供 setCollapsed/toggleCollapse（切换缩小），summon 保留给移动端召回
    4. layoutModel 的收起态守卫 + fitBounds 缓存仍保留（防御性，防止异常 bounds 改坏 transform）
    """
    html = _text(TEMPLATE)
    js = _text(PET_JS)
    css = _text(PET_CSS)
    # 1. 单按钮契约
    assert html.count('id="xm-pet-btn-min"') == 1
    assert 'id="xm-pet-btn-hide"' not in html, "隐藏按钮已删除（与收起重复）"
    # 2. 收起=缩小：.is-min 是 transform scale，不是 display:none
    assert ".xm-pet.is-min" in css
    assert "display: none" not in css.split(".xm-pet.is-min")[1].split("}")[0], \
        "收起态不得 display:none（否则触发隐藏→召唤头部被裁 bug 路径）"
    # 3. JS 切换逻辑
    assert "function setCollapsed" in js or "setCollapsed" in js
    assert "toggleCollapse" in js
    assert "function summon" in js
    assert "sessionHidden" not in js, "sessionHidden 已随隐藏功能移除"
    assert "hidePet" not in js, "hidePet 已随隐藏功能移除"
    # 4. 防御契约保留：layoutModel 收起态守卫 + fitBounds 缓存
    assert "fitBounds" in js
    assert "if (isCollapsed()) return false;" in js


def test_hide_summon_layout_guards():
    """BUG-FIX(2026-09-21) 第 2 轮：真实 GPU 下召唤后头仍被裁。

    防御契约（缺一不可，删掉会回归）：
    1. fitBounds 缓存 —— 首次成功布局后缓存模型视觉包围盒，召唤后布局优先用
       缓存值，免疫 getLocalBounds 返回非 0 但异常的值（真实 GPU 下 display:none
       期间 Cubism 更新暂停可能触发）。
    2. isCollapsed 守卫 —— 收起/隐藏（display:none）期间不重算布局，防止隐藏时
       canvas 尺寸 0 + bounds 异常把 transform 改坏（召唤后第一帧头就被裁）。
    """
    js = _text(PET_JS)
    assert "fitBounds" in js, "pet.js 缺少 fitBounds 缓存（召唤后布局免疫异常 bounds）"
    assert "state.fitBounds = { w: bw, h: bh }" in js, "首次成功布局未写 fitBounds 缓存"
    assert "isCollapsed()" in js, "pet.js 缺少 isCollapsed"
    # layoutModel 开头必须有收起态守卫（隐藏期间不布局）
    assert "if (isCollapsed()) return false;" in js, "layoutModel 缺少收起态守卫（隐藏时会把 transform 改坏）"
