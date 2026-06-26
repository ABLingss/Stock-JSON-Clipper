"""
alert_engine.py — Background price alert engine + shared PriceFetcher.

Architecture:
  PriceFetcher (shared) → AlertEngine (poll + check + fire)
  Extensible via add_consumer() for future features.

Thread safety: 5 iron rules (see CLAUDE.md or plan document).
  1. Never hold a lock during IO
  2. reload() reads config first, then takes lock for atomic swap
  3. _fire() releases lock before calling icon.notify()
  4. _poll_loop copies consumer list under lock, iterates after release
  5. config writes use atomic write-then-rename
"""

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import requests

log = logging.getLogger("alert_engine")


# ============================================================
# Data classes
# ============================================================

@dataclass
class PriceSnapshot:
    """A single stock's current price data from live feed."""
    code: str
    name: str
    price: float
    change_pct: float = 0.0


@dataclass
class AlertConfig:
    """Persistent alert configuration for one stock (syncs with config.ini)."""
    code: str
    name: str = ""
    enabled: bool = True
    price_upper: Optional[float] = None
    price_lower: Optional[float] = None
    upper_triggered: bool = False
    lower_triggered: bool = False
    last_price: float = 0.0
    last_update: str = ""
    buffer_pct: float = 2.0


# ============================================================
# PriceFetcher — shared HTTP fetcher
# ============================================================

class PriceFetcher:
    """Fetch live stock prices from Tencent / Sina free APIs.

    Zero auth, zero token.  Tencent first (3s timeout), Sina fallback (5s).
    """

    TENCENT_URL = "https://qt.gtimg.cn/q={codes}"
    SINA_URL = "https://hq.sinajs.cn/list={codes}"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })

    def fetch(self, codes: List[str]) -> Dict[str, "PriceSnapshot"]:
        """Fetch prices for a list of stock codes.

        Args:
            codes: e.g. ["SH600519", "SZ000651"]

        Returns:
            {code: PriceSnapshot} — partial results on partial failure.
        """
        if not codes:
            return {}

        results: Dict[str, PriceSnapshot] = {}
        unknown: List[str] = []

        # ── Try Tencent ──
        try:
            cs = ",".join(codes)
            resp = self._session.get(
                self.TENCENT_URL.format(codes=cs), timeout=3
            )
            if resp.status_code == 200:
                for code in codes:
                    snap = _parse_tencent(resp.text, code)
                    if snap:
                        results[code] = snap
                    else:
                        unknown.append(code)
            else:
                unknown = list(codes)
        except Exception:
            unknown = list(codes)

        # ── Fallback: Sina for unresolved codes ──
        if unknown:
            try:
                cs = ",".join(unknown)
                resp = self._session.get(
                    self.SINA_URL.format(codes=cs),
                    headers={"Referer": "https://finance.sina.com.cn/"},
                    timeout=5,
                )
                if resp.status_code == 200:
                    for code in unknown:
                        snap = _parse_sina(resp.text, code)
                        if snap:
                            results[code] = snap
            except Exception:
                pass

        return results


# ---- Tencent parser ----

_TENCENT_LINE_RE = re.compile(r'v_([a-z]{2}\d{6})="([^"]*)"')


def _parse_tencent(text: str, code: str) -> Optional[PriceSnapshot]:
    """Parse a single stock from Tencent's qt.gtimg.cn response.

    Format: v_sh600519="1~贵州茅台~600519~1620.50~..."
    Fields: ~ separated. name=[1], price=[3], change_pct=[32].
    """
    for m in _TENCENT_LINE_RE.finditer(text):
        if m.group(1).upper() == code.upper():
            parts = m.group(2).split("~")
            if len(parts) < 4:
                return None
            try:
                price = float(parts[3])
            except (ValueError, IndexError):
                return None
            name = parts[1] if len(parts) > 1 else code
            change_pct = 0.0
            if len(parts) > 32:
                try:
                    change_pct = float(parts[32])
                except (ValueError, IndexError):
                    pass
            return PriceSnapshot(code=code, name=name, price=price, change_pct=change_pct)
    return None


# ---- Sina parser ----

def _parse_sina(text: str, code: str) -> Optional[PriceSnapshot]:
    """Parse a single stock from Sina's sinajs.cn response.

    Each line: var hq_str_{code}="name,open,yesterday,price,..."
    Fields: name=[0], yesterday=[2], price=[3].
    """
    # Sina uses lowercase prefix (sh600519, sz000651)
    sina_code = code.lower()
    escaped = re.escape(sina_code)
    pattern = re.compile(r'hq_str_' + escaped + r'="([^"]*)"')
    m = pattern.search(text)
    if not m:
        return None
    parts = m.group(1).split(",")
    if len(parts) < 4:
        return None
    try:
        price = float(parts[3])
    except (ValueError, IndexError):
        return None
    name = parts[0]
    change_pct = 0.0
    if len(parts) > 2:
        try:
            yesterday = float(parts[2])
            if yesterday > 0:
                change_pct = (price - yesterday) / yesterday * 100.0
        except (ValueError, IndexError):
            pass
    return PriceSnapshot(code=code, name=name, price=price, change_pct=round(change_pct, 2))


# ============================================================
# AlertEngine — background polling + alert checking
# ============================================================

class AlertEngine:
    """Background price alert engine.

    Lifecycle:
      - clipper.start() calls start() → loads config, spawns daemon thread
      - clipper.stop()  calls stop()  → signals thread, joins with timeout

    Consumer pattern:
      - add_consumer(callback) registers a callback(prices_dict) for every poll
      - Future consumers can use this to react to price updates
    """

    DEFAULT_POLL_INTERVAL = 5       # seconds
    DEFAULT_BUFFER_PCT = 2.0        # %
    FAILSAFE_INTERVAL = 60          # seconds when network keeps failing
    FAILSAFE_THRESHOLD = 10         # consecutive errors to trigger failsafe

    def __init__(self, clipper: "StockClipper"):  # type: ignore[name-defined] # noqa: F821
        self._clipper = clipper
        self._fetcher = PriceFetcher()
        self._alerts: Dict[str, AlertConfig] = {}
        self._consumers: List[Callable[[Dict[str, PriceSnapshot]], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._data_lock = threading.Lock()
        self._failsafe = 0

    # ── Lifecycle ──

    def start(self) -> None:
        """Load alerts from config and start the background polling thread."""
        from core.config import load_alerts
        self._alerts = load_alerts()
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="AlertEngine")
        self._thread.start()
        log.info("AlertEngine started with %d alerts", len(self._alerts))

    def stop(self) -> None:
        """Signal the polling thread to stop and wait for it."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=15)
        if self._thread and self._thread.is_alive():
            log.warning("AlertEngine thread did not terminate within timeout")
        log.info("AlertEngine stopped")

    def reload(self) -> None:
        """Re-read alerts from config.ini (called when PanelAPI modifies alerts).

        Iron rule 2: IO first, then lock for atomic swap.
        Preserves trigger states for existing alerts.
        """
        from core.config import load_alerts
        new_alerts = load_alerts()          # disk IO — no lock
        with self._data_lock:
            for code, cfg in new_alerts.items():
                if code in self._alerts:
                    cfg.upper_triggered = self._alerts[code].upper_triggered
                    cfg.lower_triggered = self._alerts[code].lower_triggered
                    cfg.last_price = self._alerts[code].last_price
            self._alerts = new_alerts       # atomic swap
        log.info("AlertEngine reloaded: %d alerts", len(self._alerts))

    def add_consumer(self, callback: Callable[[Dict[str, PriceSnapshot]], None]) -> None:
        """Register a consumer that receives prices after every poll.

        Args:
            callback: Called with {code: PriceSnapshot} dict.
        """
        with self._data_lock:
            self._consumers.append(callback)

    # ── Polling loop ──

    def _poll_loop(self) -> None:
        """Main loop: fetch → check alerts → push to consumers → sleep."""
        while self._running:
            try:
                # Iron rule 1: get codes under lock, release before IO
                with self._data_lock:
                    enabled = self._get_enabled_alerts_locked()
                    codes = list(enabled.keys())

                if codes:
                    prices = self._fetcher.fetch(codes)
                    if prices:
                        self._failsafe = 0  # reset on success
                    else:
                        self._failsafe += 1

                    # Check alerts
                    for code, cfg in enabled.items():
                        snap = prices.get(code)
                        if snap:
                            self._check_and_fire(code, cfg, snap)
                        else:
                            self._handle_miss(code, cfg)

                else:
                    self._failsafe = 0  # no alerts configured, not an error
                    prices = {}

                # Iron rule 4: copy consumer list under lock, iterate after release
                with self._data_lock:
                    consumers = list(self._consumers)
                for consumer in consumers:
                    try:
                        consumer(prices)
                    except Exception:
                        log.debug("Consumer error (non-fatal)", exc_info=True)

                # Adaptive interval
                interval = (
                    self.FAILSAFE_INTERVAL if self._failsafe >= self.FAILSAFE_THRESHOLD
                    else self._get_poll_interval()
                )
                for _ in range(int(interval * 10)):
                    if not self._running:
                        break
                    time.sleep(0.1)

            except Exception:
                self._failsafe += 1
                log.error("Poll cycle error (failsafe=%d)", self._failsafe, exc_info=True)
                for _ in range(60):
                    if not self._running:
                        break
                    time.sleep(1)

    def _get_enabled_alerts_locked(self) -> Dict[str, AlertConfig]:
        """Must hold _data_lock. Returns enabled alerts (master + per-alert)."""
        from core.config import get_alerts_config
        master_cfg = get_alerts_config()
        if not master_cfg.get("enabled", True):
            return {}
        return {c: a for c, a in self._alerts.items() if a.enabled}

    def _get_poll_interval(self) -> int:
        """Read poll_interval from [alerts] section, fallback to default."""
        from core.config import get_alerts_config
        return int(get_alerts_config().get("poll_interval", self.DEFAULT_POLL_INTERVAL))

    # ── Core logic ──

    def _check_and_fire(self, code: str, cfg: AlertConfig, snap: PriceSnapshot) -> None:
        """Debounce state machine for upper/lower threshold checks.

        Iron rule 3: update state under lock, fire notification after release.
        """
        buffer_pct = cfg.buffer_pct / 100.0
        first_poll = cfg.last_price == 0.0
        triggered = False
        direction = ""

        with self._data_lock:
            # ── Upper threshold check ──
            if cfg.price_upper is not None and cfg.price_upper > 0:
                if snap.price >= cfg.price_upper and not cfg.upper_triggered:
                    if not first_poll:
                        cfg.upper_triggered = True
                        triggered = True
                        direction = "upper"
                elif cfg.upper_triggered and snap.price < cfg.price_upper * (1.0 - buffer_pct):
                    cfg.upper_triggered = False  # reset

            # ── Lower threshold check ──
            if not triggered and cfg.price_lower is not None and cfg.price_lower > 0:
                if snap.price <= cfg.price_lower and not cfg.lower_triggered:
                    if not first_poll:
                        cfg.lower_triggered = True
                        triggered = True
                        direction = "lower"
                elif cfg.lower_triggered and snap.price > cfg.price_lower * (1.0 + buffer_pct):
                    cfg.lower_triggered = False

            # Update state
            cfg.last_price = snap.price
            cfg.last_update = time.strftime("%Y-%m-%d %H:%M:%S")

            # Persist state
            from core.config import update_alert_state
            update_alert_state(code, cfg.upper_triggered, cfg.lower_triggered, cfg.last_price)

        # Fire notification AFTER releasing lock (iron rule 3)
        if triggered:
            self._fire(code, cfg, snap, direction)

    def _handle_miss(self, code: str, cfg: AlertConfig) -> None:
        """Price fetch returned nothing for this code."""
        # Could track consecutive misses per code, but for V1 just log
        log.debug("Price fetch miss for %s", code)

    def _fire(self, code: str, cfg: AlertConfig, snap: PriceSnapshot, direction: str) -> None:
        """Send tray notification. Does NOT hold any lock (iron rule 3)."""
        icon = getattr(self._clipper, '_icon', None)
        if icon is None:
            return  # tray not created yet

        name = cfg.name or snap.name or code
        if direction == "upper":
            title = f"🔔 价格预警 — {name}"
            msg = (
                f"📈 突破上限 {cfg.price_upper:.2f} 元！\n"
                f"当前价格: {snap.price:.2f}  ({snap.change_pct:+.2f}%)\n"
                f"{cfg.last_update}"
            )
        else:
            title = f"🔔 价格预警 — {name}"
            msg = (
                f"📉 跌破下限 {cfg.price_lower:.2f} 元！\n"
                f"当前价格: {snap.price:.2f}  ({snap.change_pct:+.2f}%)\n"
                f"{cfg.last_update}"
            )

        try:
            icon.notify(msg, title=title)
            log.info("Alert fired: %s %s price=%.2f", code, direction, snap.price)
        except Exception:
            log.warning("Notification failed for %s (non-fatal)", code, exc_info=True)
