"""行情多源容错 — 健康探测 + 自动切换编排（REQ-004）。

设计：
- SourceHealth：跟踪单源连续失败/成功，down 后需连续 recovery_probes 次成功才回 up
- MultiSourceQuote：按 [主源, 备源, ...] 顺序编排 fetch；down 的源照常尝试探测
  （成功进入恢复探测，失败继续累计），首个成功即返回；全部失败抛 RuntimeError

为未来插 miniQMT 推送行情源预留：实现 fetch() 接口即可接入 MultiSourceQuote。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import logging

logger = logging.getLogger(__name__)


class SourceHealth:
    """单源健康状态机。

    up → (连续 max_fail 次失败) → down → (连续 recovery_probes 次成功) → up
    """

    def __init__(self, name: str, max_fail: int = 3, recovery_probes: int = 2):
        self.name = name
        self.max_fail = max_fail
        self.recovery_probes = recovery_probes
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.down = False

    def record_failure(self):
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        if self.consecutive_failures >= self.max_fail:
            if not self.down:
                logger.warning("[quote] 行情源 %s 连续失败 %d 次 → DOWN", self.name, self.consecutive_failures)
            self.down = True

    def record_success(self):
        self.consecutive_successes += 1
        if self.down:
            # 恢复探测期：需要连续 recovery_probes 次成功才回 up
            if self.consecutive_successes >= self.recovery_probes:
                logger.info("[quote] 行情源 %s 恢复探测通过 → UP", self.name)
                self.down = False
                self.consecutive_successes = 0
                self.consecutive_failures = 0
        else:
            self.consecutive_failures = 0
            self.consecutive_successes = 0

    def is_up(self) -> bool:
        return not self.down

    def is_down(self) -> bool:
        return self.down


class MultiSourceQuote:
    """多源切换编排：按序尝试 sources，首个成功的返回；全部失败抛 RuntimeError。

    sources: list[Source]，每个源需实现 fetch()（成功返回值，失败抛异常）。
    """

    def __init__(self, sources, max_fail: int = 3, recovery_probes: int = 2):
        self.sources = [
            (src, SourceHealth(name=repr(src),
                               max_fail=max_fail, recovery_probes=recovery_probes))
            for src in sources
        ]
        self.max_fail = max_fail
        self.recovery_probes = recovery_probes

    def fetch(self):
        last_err = None
        for src, health in self.sources:
            # down 源照常尝试（成功进入恢复探测，失败继续累计）——
            # 保证主源恢复后能自动回切，而不是被永久跳过
            try:
                value = src.fetch()
                health.record_success()
                return value
            except Exception as e:  # noqa: BLE001 — 源异常统一视为该源失败
                health.record_failure()
                last_err = e
                logger.warning("[quote] 行情源 %s fetch 失败: %s", health.name, e)
        raise RuntimeError(f"所有行情源均不可用: {last_err}")

    def health_report(self) -> list[dict]:
        return [
            {"name": h.name, "up": h.is_up(), "failures": h.consecutive_failures}
            for _, h in self.sources
        ]


class CachedSource:
    """兜底源：读本地缓存。fetch() 实现接入 MultiSourceQuote 尾部。"""

    def __init__(self, loader, name: str = "cache"):
        self._loader = loader
        self._name = name

    def fetch(self):
        value = self._loader()
        if value is None:
            raise RuntimeError("cache empty")
        return value

    def __repr__(self):
        return self._name


# ═══════════════════════════════════════════════════════════════
# 交叉校验：双源价差一致性（REQ-004 期望4）
# ═══════════════════════════════════════════════════════════════

def cross_validate_series(primary: dict, backup: dict, code: str,
                          threshold: float = 0.005) -> dict:
    """双源收盘价交叉校验。

    primary/backup: {date: close} 映射（或 DataFrame 转 dict）。
    threshold: 相对价差阈值（ETF 默认 0.5%）。
    返回: {"code", "match": bool, "max_diff_pct": float, "dates": n}
    超阈值打 WARN（不静默），但不抛异常（数据可用性优先）。
    """
    if not primary or not backup:
        return {"code": code, "match": True, "max_diff_pct": 0.0,
                "dates": 0, "reason": "单源无数据，跳过校验"}
    common = set(primary) & set(backup)
    if not common:
        return {"code": code, "match": True, "max_diff_pct": 0.0,
                "dates": 0, "reason": "无公共日期，跳过校验"}
    max_diff = 0.0
    for d in common:
        p, b = primary[d], backup[d]
        if p and b and b != 0:
            diff = abs(p - b) / abs(b)
            if diff > max_diff:
                max_diff = diff
    match = max_diff <= threshold
    if not match:
        logger.warning(
            "[quote] 交叉校验 %s 价差 %.4f%% 超阈值 %.2f%%（双源不一致，"
            "以主源为准，请核查数据源）", code, max_diff * 100, threshold * 100)
    return {"code": code, "match": match,
            "max_diff_pct": round(max_diff * 100, 4), "dates": len(common)}


def cross_validate_df(primary_df, backup_df, code: str,
                      threshold: float = 0.005) -> dict:
    """DataFrame 版交叉校验：取 close 列按 index 对齐比较。"""
    if primary_df is None or backup_df is None or len(primary_df) == 0 or len(backup_df) == 0:
        return {"code": code, "match": True, "max_diff_pct": 0.0,
                "dates": 0, "reason": "单源无数据，跳过校验"}
    p = primary_df["close"].to_dict()
    b = backup_df["close"].to_dict()
    return cross_validate_series(p, b, code, threshold)


if __name__ == "__main__":
    # 自检：单源 down → 自动降级
    logging.basicConfig(level=logging.INFO)

    class Flaky:
        def __init__(self):
            self.n = 0
        def fetch(self):
            self.n += 1
            if self.n <= 2:
                raise ConnectionError("flaky")
            return {"ok": True}
        def __repr__(self):
            return "flaky"

    ms = MultiSourceQuote(sources=[Flaky(), CachedSource(lambda: {"ok": "cache"})], max_fail=2)
    for _ in range(4):
        print("fetch:", ms.fetch())
    print("health:", ms.health_report())
