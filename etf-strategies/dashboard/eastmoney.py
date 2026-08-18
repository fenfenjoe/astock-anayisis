"""东方财富账号自动获取 — 实验功能（可选，非主路径）。

⚠️ 调研结论：东财无官方个人账户 API，唯一路径是社区逆向交易库
（jadepeng/pytrader，基于 easytrader + easyquotation，驱动东财 PC 客户端），
脆弱、条款灰色、随客户端版本漂移。本模块只做**薄封装**，不提交任何逆向实现。

集成前提（未满足则优雅降级到手动配置）：
- 安装社区库（未上 PyPI，需从 GitHub 装）:
    pip install git+https://github.com/jadepeng/pytrader.git
- 本机已安装并登录 东方财富 PC 客户端（pytrader 经 pywinauto 驱动客户端取持仓）
- 类名/接口随版本变化，本模块用「适配器探测」尽量兼容，失败给可操作提示

安全设计：
- 凭据用 Fernet（密钥派生自 dashboard auth 的持久化 secret key）加密后存 DB
- 任何失败都优雅降级：调用方保留手动持仓数据，绝不覆盖

依赖：cryptography>=41（缺包时拒绝保存凭据，而非存明文）
"""
import base64
import hashlib
import json

from dashboard.auth import _SECRET_KEY


class EastmoneyUnavailable(Exception):
    """东财自动获取不可用（未安装 trader 库 / 网络 / 凭据问题）。"""


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise EastmoneyUnavailable(
            "缺少 cryptography 依赖，无法加密存储东财凭据。"
            "请安装: pip install cryptography"
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(_SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_creds(account: str, password: str, note: str = "") -> str:
    """加密账户凭据 → Fernet token（存 portfolio_meta['eastmoney_config']）。"""
    payload = json.dumps({"account": account, "password": password, "note": note},
                         ensure_ascii=False)
    return _fernet().encrypt(payload.encode("utf-8")).decode("utf-8")


def decrypt_creds(token: str) -> dict:
    """解密凭据 token → {account, password, note}。"""
    try:
        raw = _fernet().decrypt(token.encode("utf-8"))
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise EastmoneyUnavailable(f"凭据解密失败: {e}")


def account_suffix(creds: dict) -> str:
    """返回账号后 4 位（用于 UI 展示，不泄露完整账号）。"""
    acct = str(creds.get("account", ""))
    return acct[-4:] if len(acct) >= 4 else "****"


def _discover_trader_cls():
    """探测已安装的社区东财交易库，返回 trader 工厂类（或 None）。

    类名随 pytrader 版本变化，用 getattr 探测多个候选名，避免硬编码导入失败。
    """
    # 1) pytrader（jadepeng 分支，支持东财；未上 PyPI，需 git 安装）
    try:
        import pytrader  # type: ignore
    except ImportError:
        pytrader = None
    if pytrader is not None:
        for name in ("EastMoneyTrader", "EastmoneyTrader", "EMTrader"):
            cls = getattr(pytrader, name, None)
            if cls is not None:
                return cls
    # 2) easytrader 风格（部分 fork 加了东财支持）
    try:
        import easytrader  # type: ignore
    except ImportError:
        easytrader = None
    if easytrader is not None:
        for name in ("EastMoney", "Eastmoney", "EM"):
            cls = getattr(easytrader, name, None)
            if cls is not None:
                return cls
    return None


def fetch_positions(creds: dict) -> dict:
    """从东财拉取持仓/资产。返回 {holdings:[{code,name,shares,cost_price}], total_assets, available_cash}。

    尝试社区 trader 库（pytrader 驱动东财 PC 客户端取 get_position()/balance）；
    库未装 / 类名对不上 → 抛 EastmoneyUnavailable（调用方优雅降级到手动配置）。
    """
    if not creds.get("account") or not creds.get("password"):
        raise EastmoneyUnavailable("未配置东财账号或密码")

    trader_cls = _discover_trader_cls()
    if trader_cls is None:
        raise EastmoneyUnavailable(
            "未检测到支持东财的 trader 库。安装方式（未上 PyPI，需从 GitHub 装）：\n"
            "  pip install git+https://github.com/jadepeng/pytrader.git\n"
            "并确认：① 本机已安装并登录 东方财富 PC 客户端；② pytrader 内能找到东财适配类。"
            "此为实验功能，失败不会改动手动持仓。"
        )

    try:
        trader = trader_cls(user=creds["account"], password=creds["password"])
        positions = trader.get_position()
        balance = trader.balance
    except Exception as e:
        raise EastmoneyUnavailable(f"东财登录/拉取失败（可能需人工过验证码）: {e}")

    holdings = []
    for p in positions or []:
        code = str(p.get("stock_code") or p.get("代码") or "").zfill(6)
        if not code:
            continue
        holdings.append({
            "code": code,
            "name": p.get("stock_name") or p.get("名称") or code,
            "shares": float(p.get("current_amount") or p.get("持仓数量") or 0),
            "cost_price": float(p.get("cost_price") or p.get("成本价") or 0),
        })
    return {
        "holdings": [h for h in holdings if h["shares"] > 0],
        "total_assets": float(balance.get("总资产") or balance.get("total_assets") or 0),
        "available_cash": float(balance.get("可用金额") or balance.get("available_cash") or 0),
    }
