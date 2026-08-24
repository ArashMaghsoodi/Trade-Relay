from __future__ import annotations

import unittest

from trade_relay.models import EventType, Side
from trade_relay.parser import parse_signal_message

SETUP_TEXT = """LBANK Futures 🔥SHORT
🎯 #ENA/USDT
🟢Enter price: 0.17660 – 0.17960
✅ TP1: 0.17364
🎯TP2 : 0.17050
🎯TP3: 0.16760
❌Normal Stop Loss: 0.18254
⚠️1% Risk (Isolated 4X)
#Signal"""

ENTRY_TRIGGER_TEXT = "#ENA/USDT (SHORT)\nEntry 1 Achieved ✅"

TARGET_HIT_TEXT = """#ENA/USDT (SHORT)
Target ( 1 ) Reached ✅
📅 8-23 13:27 UTC
+6.70% Profit 🚀
Period: 11M ⏰"""

STOPPED_OUT_TEXT = """#LDO/USDT (SHORT)
Stopped out ⛔️
📅 8-23 11:16 UTC
-11.65% Loss
Period: 21M ⏰"""


class TestParser(unittest.TestCase):
    def test_parses_setup(self):
        event = parse_signal_message(SETUP_TEXT)
        self.assertIsNotNone(event)
        assert event is not None and event.event_type == EventType.SETUP and event.setup is not None

        setup = event.setup
        self.assertEqual(setup.symbol, "ENA/USDT")
        self.assertEqual(setup.side, Side.SHORT)
        self.assertAlmostEqual(setup.entry_low, 0.17660)
        self.assertAlmostEqual(setup.entry_high, 0.17960)
        self.assertAlmostEqual(setup.tp1, 0.17364)
        self.assertAlmostEqual(setup.tp2, 0.17050)
        # self.assertAlmostEqual(setup.tp3, 0.16760)
        self.assertAlmostEqual(setup.stop_loss, 0.18254)

    def test_parses_entry_trigger(self):
        event = parse_signal_message(ENTRY_TRIGGER_TEXT)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.event_type, EventType.ENTRY_TRIGGER)
        self.assertEqual(event.symbol, "ENA/USDT")
        self.assertEqual(event.side, Side.SHORT)
        self.assertIsNone(event.setup)

    def test_parses_target_hit(self):
        event = parse_signal_message(TARGET_HIT_TEXT)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.event_type, EventType.TARGET_HIT)
        self.assertEqual(event.symbol, "ENA/USDT")
        self.assertEqual(event.side, Side.SHORT)
        self.assertEqual(event.target_number, 1)

    def test_parses_stopped_out(self):
        event = parse_signal_message(STOPPED_OUT_TEXT)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.event_type, EventType.STOPPED_OUT)
        self.assertEqual(event.symbol, "LDO/USDT")
        self.assertEqual(event.side, Side.SHORT)

    def test_ignores_non_signal_text(self):
        self.assertIsNone(parse_signal_message("Hello everyone 👋 welcome to the channel"))
        self.assertIsNone(parse_signal_message(""))


if __name__ == "__main__":
    unittest.main()
