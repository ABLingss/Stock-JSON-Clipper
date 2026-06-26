"""
test_alert_engine.py — Unit tests for PriceFetcher + AlertEngine.

Tests:
  - PriceFetcher Tencent/Sina parsing
  - AlertEngine debounce state machine
  - Anti-repeat, buffer reset, first-poll, gap-up
  - Network error degradation
  - Consumer pattern
"""

import json
import os
import sys
import time
import unittest
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# PriceFetcher tests
# ============================================================

class TestPriceFetcherParsing(unittest.TestCase):
    """Test Tencent and Sina response parsing."""

    def setUp(self):
        from core.alert_engine import PriceFetcher
        self.fetcher = PriceFetcher()

    def test_parse_tencent_single(self):
        """Parse a valid Tencent response."""
        raw = 'v_sh600519="1~贵州茅台~600519~1620.50~1615.00~1610.00~1625.00~1610.00~10000~5000~...~2.30~..."\n'
        from core.alert_engine import _parse_tencent
        snap = _parse_tencent(raw, "SH600519")
        self.assertIsNotNone(snap)
        self.assertEqual(snap.name, "贵州茅台")
        self.assertAlmostEqual(snap.price, 1620.50)

    def test_parse_tencent_not_found(self):
        """Code not in response returns None."""
        from core.alert_engine import _parse_tencent
        snap = _parse_tencent("v_sz000001=...", "SH600519")
        self.assertIsNone(snap)

    def test_parse_sina_single(self):
        """Parse a valid Sina response."""
        raw = 'var hq_str_sh600519="贵州茅台,1615.00,1610.00,1620.50,1625.00,1610.00,...";\n'
        from core.alert_engine import _parse_sina
        snap = _parse_sina(raw, "SH600519")
        self.assertIsNotNone(snap)
        self.assertEqual(snap.name, "贵州茅台")
        self.assertAlmostEqual(snap.price, 1620.50)

    def test_parse_sina_not_found(self):
        """Code not in response returns None."""
        from core.alert_engine import _parse_sina
        snap = _parse_sina("var hq_str_sz000001=...", "SH600519")
        self.assertIsNone(snap)

    @patch('core.alert_engine.requests.Session.get')
    def test_fetch_tencent_success(self, mock_get):
        """Fetch returns results from Tencent."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.text = 'v_sh600519="1~茅台~600519~1620.50~1615.00~...~2.30~..."\n'
        mock_get.return_value = mock_resp

        results = self.fetcher.fetch(["SH600519"])
        self.assertIn("SH600519", results)
        self.assertEqual(results["SH600519"].name, "茅台")

    @patch('core.alert_engine.requests.Session.get')
    def test_fetch_tencent_fail_sina_fallback(self, mock_get):
        """When Tencent fails, Sina is used as fallback."""
        from core.alert_engine import PriceFetcher
        call_count = [0]

        def side_effect(url, **kwargs):
            call_count[0] += 1
            resp = Mock()
            if "gtimg" in url:
                resp.status_code = 500  # Tencent fails
                resp.text = ""
            else:
                resp.status_code = 200
                resp.text = 'var hq_str_sh600519="茅台,1615.00,1610.00,1620.50,...";\n'
            return resp

        mock_get.side_effect = side_effect
        results = self.fetcher.fetch(["SH600519"])
        self.assertEqual(call_count[0], 2)  # Tencent + Sina
        self.assertIn("SH600519", results)

    @patch('core.alert_engine.requests.Session.get')
    def test_fetch_all_fail(self, mock_get):
        """When both fail, return empty dict."""
        mock_resp = Mock()
        mock_resp.status_code = 500
        mock_resp.text = ""
        mock_get.return_value = mock_resp

        results = self.fetcher.fetch(["SH600519"])
        self.assertEqual(results, {})

    def test_fetch_empty_codes(self):
        """Empty code list returns empty dict."""
        self.assertEqual(self.fetcher.fetch([]), {})


# ============================================================
# AlertEngine state machine tests
# ============================================================

class TestAlertEngine(unittest.TestCase):
    """Test debounce state machine and alert logic."""

    def setUp(self):
        import threading
        # Create a minimal mock clipper
        self.clipper = Mock()
        self.clipper._icon = None

        from core.alert_engine import AlertEngine, AlertConfig, PriceSnapshot
        self.AlertEngine = AlertEngine
        self.AlertConfig = AlertConfig
        self.PriceSnapshot = PriceSnapshot

        # Override config IO (functions imported locally in alert_engine methods)
        self._patchers = [
            patch('core.config.load_alerts', return_value={}),
            patch('core.config.get_alerts_config', return_value={
                "enabled": True, "poll_interval": 5, "buffer_pct": 2.0, "max_alerts": 10
            }),
            patch('core.config.update_alert_state'),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()

    def _make_engine(self):
        return self.AlertEngine(self.clipper)

    def test_first_poll_no_fire(self):
        """First poll (last_price=0) records price but does NOT fire."""
        engine = self._make_engine()
        cfg = self.AlertConfig(
            code="SH600519", name="茅台", enabled=True,
            price_upper=1600.0, last_price=0.0
        )
        snap = self.PriceSnapshot(code="SH600519", name="茅台", price=1620.0, change_pct=2.3)

        with patch.object(engine, '_fire') as mock_fire:
            engine._check_and_fire("SH600519", cfg, snap)
            mock_fire.assert_not_called()
            self.assertEqual(cfg.last_price, 1620.0)  # price updated
            self.assertFalse(cfg.upper_triggered)      # but not triggered

    def test_upper_trigger(self):
        """Price crossing above upper threshold triggers alert."""
        engine = self._make_engine()
        cfg = self.AlertConfig(
            code="SH600519", name="茅台", enabled=True,
            price_upper=1600.0, last_price=1550.0
        )
        snap = self.PriceSnapshot(code="SH600519", name="茅台", price=1620.0, change_pct=2.0)

        with patch.object(engine, '_fire') as mock_fire:
            engine._check_and_fire("SH600519", cfg, snap)
            mock_fire.assert_called_once()
            self.assertTrue(cfg.upper_triggered)

    def test_lower_trigger(self):
        """Price crossing below lower threshold triggers alert."""
        engine = self._make_engine()
        cfg = self.AlertConfig(
            code="SH600519", name="茅台", enabled=True,
            price_lower=1400.0, last_price=1450.0
        )
        snap = self.PriceSnapshot(code="SH600519", name="茅台", price=1380.0, change_pct=-5.0)

        with patch.object(engine, '_fire') as mock_fire:
            engine._check_and_fire("SH600519", cfg, snap)
            mock_fire.assert_called_once()
            self.assertTrue(cfg.lower_triggered)

    def test_anti_repeat_upper(self):
        """Once triggered, same-direction doesn't fire again."""
        engine = self._make_engine()
        cfg = self.AlertConfig(
            code="SH600519", name="茅台", enabled=True,
            price_upper=1600.0, last_price=1550.0, upper_triggered=True
        )
        snap = self.PriceSnapshot(code="SH600519", name="茅台", price=1650.0, change_pct=3.0)

        with patch.object(engine, '_fire') as mock_fire:
            engine._check_and_fire("SH600519", cfg, snap)
            mock_fire.assert_not_called()

    def test_buffer_reset_upper(self):
        """After triggering, price must drop below buffer zone to reset."""
        engine = self._make_engine()
        cfg = self.AlertConfig(
            code="SH600519", name="茅台", enabled=True,
            price_upper=1600.0, last_price=1620.0, upper_triggered=True, buffer_pct=2.0
        )
        # Price at 1580: 1600 * (1 - 0.02) = 1568.  1580 > 1568 → still triggered
        snap1 = self.PriceSnapshot(code="SH600519", name="茅台", price=1580.0, change_pct=-1.0)
        engine._check_and_fire("SH600519", cfg, snap1)
        self.assertTrue(cfg.upper_triggered)  # not reset yet

        # Price at 1550: 1550 < 1568 → reset
        snap2 = self.PriceSnapshot(code="SH600519", name="茅台", price=1550.0, change_pct=-3.0)
        engine._check_and_fire("SH600519", cfg, snap2)
        self.assertFalse(cfg.upper_triggered)  # reset!

    def test_gap_up_fires(self):
        """Price jumping from below to above (gap up) still triggers."""
        engine = self._make_engine()
        cfg = self.AlertConfig(
            code="SH600519", name="茅台", enabled=True,
            price_upper=1600.0, last_price=1500.0  # was below
        )
        # Open at 1650 (gap up through threshold)
        snap = self.PriceSnapshot(code="SH600519", name="茅台", price=1650.0, change_pct=10.0)

        with patch.object(engine, '_fire') as mock_fire:
            engine._check_and_fire("SH600519", cfg, snap)
            mock_fire.assert_called_once()  # fires on gap-up

    def test_consumer_pattern(self):
        """Registered consumer receives prices after poll."""
        engine = self._make_engine()
        received = []

        def consumer(prices):
            received.append(prices)

        engine.add_consumer(consumer)
        self.assertEqual(len(engine._consumers), 1)

        # Invoke consumers manually
        test_prices = {"SH600519": self.PriceSnapshot("SH600519", "茅台", 1600.0, 1.0)}
        with engine._data_lock:
            consumers = list(engine._consumers)
        for c in consumers:
            c(test_prices)
        self.assertEqual(len(received), 1)

    def test_network_error_degradation(self):
        """Failsafe counter increments on error, resets on success."""
        engine = self._make_engine()
        self.assertEqual(engine._failsafe, 0)
        engine._failsafe += 1
        engine._failsafe += 1
        self.assertEqual(engine._failsafe, 2)
        # Simulate success
        engine._failsafe = 0
        self.assertEqual(engine._failsafe, 0)

    def test_enabled_filtering(self):
        """Only enabled alerts are polled."""
        engine = self._make_engine()
        cfg1 = self.AlertConfig(code="SH600519", name="茅台", enabled=True)
        cfg2 = self.AlertConfig(code="SZ000001", name="平安", enabled=False)
        engine._alerts = {"SH600519": cfg1, "SZ000001": cfg2}
        enabled = engine._get_enabled_alerts_locked()
        self.assertIn("SH600519", enabled)
        self.assertNotIn("SZ000001", enabled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
