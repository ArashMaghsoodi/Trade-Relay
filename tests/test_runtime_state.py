from __future__ import annotations

import unittest

from trade_relay.models import EventType, Side, SignalEvent, SignalSetup
from trade_relay.runtime_state import RuntimeState, process_signal_event


def _setup(symbol: str = "BTC/USDT", side: Side = Side.SHORT) -> SignalSetup:
    return SignalSetup(
        symbol=symbol,
        side=side,
        entry_low=100.0,
        entry_high=101.0,
        tp1=99.0,
        tp2=98.0,
        tp3=97.0,
        stop_loss=102.0,
    )


class TestRuntimeState(unittest.TestCase):
    def test_entry_skips_without_setup(self):
        state = RuntimeState()
        event = SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="BTC/USDT", side=Side.SHORT)
        decision = process_signal_event(state, event, "k1")
        self.assertIn("ENTRY_SKIPPED_NO_SETUP", decision)

    def test_setup_then_entry_accepts_and_opens_position(self):
        state = RuntimeState()
        setup_event = SignalEvent(
            event_type=EventType.SETUP,
            symbol="BTC/USDT",
            side=Side.SHORT,
            setup=_setup(),
        )
        entry_event = SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="BTC/USDT", side=Side.SHORT)

        d1 = process_signal_event(state, setup_event, "k1")
        d2 = process_signal_event(state, entry_event, "k2")

        self.assertIn("SETUP_CACHED", d1)
        self.assertIn("ENTRY_ACCEPTED_DRYRUN", d2)
        self.assertIn("BTC/USDT", state.open_symbols)
        self.assertIn("BTC/USDT", state.positions_by_symbol)
        pos = state.positions_by_symbol["BTC/USDT"]
        self.assertEqual(pos.entry_status, "OPEN")
        self.assertAlmostEqual(pos.size_percent_open, 100.0)

    def test_tp1_updates_virtual_position(self):
        state = RuntimeState()
        process_signal_event(
            state,
            SignalEvent(event_type=EventType.SETUP, symbol="BTC/USDT", side=Side.SHORT, setup=_setup()),
            "k1",
        )
        process_signal_event(
            state,
            SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="BTC/USDT", side=Side.SHORT),
            "k2",
        )

        d3 = process_signal_event(
            state,
            SignalEvent(event_type=EventType.TARGET_HIT, symbol="BTC/USDT", side=Side.SHORT, target_number=1),
            "k3",
        )

        self.assertIn("TP1_PLAN", d3)
        pos = state.positions_by_symbol["BTC/USDT"]
        self.assertTrue(pos.tp1_hit)
        self.assertTrue(pos.sl_moved_to_breakeven)
        self.assertEqual(pos.entry_status, "OPEN_PARTIAL")
        self.assertAlmostEqual(pos.size_percent_open, 50.0)

    def test_tp2_closes_position_and_records_history(self):
        state = RuntimeState()
        process_signal_event(
            state,
            SignalEvent(event_type=EventType.SETUP, symbol="BTC/USDT", side=Side.SHORT, setup=_setup()),
            "k1",
        )
        process_signal_event(
            state,
            SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="BTC/USDT", side=Side.SHORT),
            "k2",
        )

        d3 = process_signal_event(
            state,
            SignalEvent(event_type=EventType.TARGET_HIT, symbol="BTC/USDT", side=Side.SHORT, target_number=2),
            "k3",
        )

        self.assertIn("TP2_CLOSE_REMAINING", d3)
        self.assertNotIn("BTC/USDT", state.open_symbols)
        pos = state.positions_by_symbol["BTC/USDT"]
        self.assertEqual(pos.entry_status, "CLOSED_TP2")
        self.assertAlmostEqual(pos.size_percent_open, 0.0)
        self.assertGreaterEqual(len(state.closed_positions), 1)
        rec = state.closed_positions[-1]
        self.assertEqual(rec.symbol, "BTC/USDT")
        self.assertEqual(rec.final_status, "CLOSED_TP2")
        self.assertEqual(rec.close_reason, "TARGET_2_PLUS_REACHED")

    def test_stopped_out_records_history(self):
        state = RuntimeState()
        process_signal_event(
            state,
            SignalEvent(event_type=EventType.SETUP, symbol="LDO/USDT", side=Side.SHORT, setup=_setup("LDO/USDT")),
            "k1",
        )
        process_signal_event(
            state,
            SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="LDO/USDT", side=Side.SHORT),
            "k2",
        )

        d3 = process_signal_event(
            state,
            SignalEvent(event_type=EventType.STOPPED_OUT, symbol="LDO/USDT", side=Side.SHORT),
            "k3",
        )

        self.assertIn("STOPPED_OUT_CLOSED", d3)
        self.assertGreaterEqual(len(state.closed_positions), 1)
        rec = state.closed_positions[-1]
        self.assertEqual(rec.symbol, "LDO/USDT")
        self.assertEqual(rec.final_status, "CLOSED_SL")
        self.assertEqual(rec.close_reason, "STOPPED_OUT")

    def test_pause_blocks_entry(self):
        state = RuntimeState()
        state.pause()
        process_signal_event(
            state,
            SignalEvent(event_type=EventType.SETUP, symbol="BTC/USDT", side=Side.SHORT, setup=_setup()),
            "k1",
        )

        decision = process_signal_event(
            state,
            SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="BTC/USDT", side=Side.SHORT),
            "k2",
        )
        self.assertIn("ENTRY_SKIPPED_RELAY_PAUSED", decision)

    def test_dedup_skips_repeated_key(self):
        state = RuntimeState()
        event = SignalEvent(
            event_type=EventType.SETUP,
            symbol="BTC/USDT",
            side=Side.SHORT,
            setup=_setup(),
        )
        first = process_signal_event(state, event, "same")
        second = process_signal_event(state, event, "same")
        self.assertIn("SETUP_CACHED", first)
        self.assertIn("DEDUP_SKIPPED", second)


if __name__ == "__main__":
    unittest.main()
