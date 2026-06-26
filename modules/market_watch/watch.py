"""
modules.market_watch.watch — Real-time market watching module.

Integrated from RollerCoaster (YQBaobao, GPL-3.0).
API methods only — HTML/CSS/JS are baked into ui/panel.py PANEL_HTML.
"""

from typing import Any, Callable, Dict, List

from api.realtime import fetch_realtime_quotes
from core.registry import BaseModule


class MarketWatchModule(BaseModule):
    """Real-time market watching module — API layer only."""

    name = "盯盘"
    description = "实时行情盯盘"
    version = "2.1"

    DEFAULT_CODES = ["000001"]

    def __init__(self):
        super().__init__()
        self._codes: List[str] = list(self.DEFAULT_CODES)

    # ---- Lifecycle ----

    def on_register(self, clipper) -> None:
        super().on_register(clipper)

    def on_start(self) -> None:
        pass

    def on_stop(self) -> None:
        pass

    # ---- API methods (exposed to JS via PanelAPI setattr) ----

    def get_api_methods(self) -> Dict[str, Callable]:
        return {
            "mw_get_quotes": self._api_get_quotes,
            "mw_add_code": self._api_add_code,
            "mw_remove_code": self._api_remove_code,
            "mw_get_codes": self._api_get_codes,
        }

    # ---- Internal handlers ----

    def _api_get_quotes(self) -> Dict[str, Any]:
        """Fetch real-time quotes on-demand."""
        if not self._codes:
            return {}
        try:
            quotes = fetch_realtime_quotes(self._codes, timeout=3)
            return {code: {"name": q.get("name", ""),
                           "current": q.get("current", 0),
                           "percent": q.get("percent", 0)}
                    for code, q in quotes.items()}
        except Exception:
            return {}

    def _api_add_code(self, code: str) -> Dict[str, Any]:
        code = code.strip()
        if not code.isdigit() or len(code) != 6:
            return {"success": False, "error": "无效代码"}
        if code in self._codes:
            return {"success": False, "error": "已在列表中"}
        if len(self._codes) >= 6:
            return {"success": False, "error": "最多添加6只"}
        self._codes.append(code)
        return {"success": True}

    def _api_remove_code(self, code: str) -> Dict[str, Any]:
        if code in self._codes:
            self._codes.remove(code)
        return {"success": True}

    def _api_get_codes(self) -> List[str]:
        return list(self._codes)
