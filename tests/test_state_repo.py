from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from trade_relay.models import Side, SignalSetup
from trade_relay.runtime_state import ClosedPositionRecord, RuntimeState, VirtualPosition
from trade_relay.state_repo import StateRepository


class TestStateRepo(unittest.TestCase):
    def test_roundtrip_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "state.db"
            repo = StateRepository(db_path)
            repo.init_db()

            state = RuntimeState(one_position_per_symbol=True)
            state.paused = True
            state.setups_by_symbol["BTC/USDT"] = SignalSetup(
                symbol="BTC/USDT",
                side=Side.SHORT,
                entry_low=100.0,
                entry_high=101.0,
                tp1=99.0,
                tp2=98.0,
                tp3=97.0,
                stop_loss=102.0,
            )
            state.open_symbols.add("BTC/USDT")
            state.positions_by_symbol["BTC/USDT"] = VirtualPosition(symbol="BTC/USDT", side="SHORT")
            state.positions_by_symbol["BTC/USDT"].entry_status = "OPEN"
            state.positions_by_symbol["BTC/USDT"].size_percent_open = 100.0
            state.processed_message_keys.append("live:-100:1")
            state._processed_lookup.add("live:-100:1")
            state.recent_decisions.append("ENTRY_ACCEPTED_DRYRUN BTC/USDT SHORT")
            state.closed_positions.append(
                ClosedPositionRecord(
                    symbol="LDO/USDT",
                    side="SHORT",
                    final_status="CLOSED_SL",
                    opened_at="2026-01-01T00:00:00+00:00",
                    closed_at="2026-01-01T01:00:00+00:00",
                    close_reason="STOPPED_OUT",
                    tp1_hit=False,
                    sl_moved_to_breakeven=False,
                )
            )

            repo.persist_state_snapshot(state)

            loaded = repo.load_state(one_position_per_symbol=True)
            self.assertTrue(loaded.paused)
            self.assertIn("BTC/USDT", loaded.setups_by_symbol)
            self.assertIn("BTC/USDT", loaded.positions_by_symbol)
            self.assertIn("BTC/USDT", loaded.open_symbols)
            self.assertIn("live:-100:1", loaded._processed_lookup)
            self.assertGreaterEqual(len(loaded.recent_decisions), 1)
            self.assertGreaterEqual(len(loaded.closed_positions), 1)
            self.assertEqual(loaded.closed_positions[-1].symbol, "LDO/USDT")

            counts = repo.table_counts()
            self.assertEqual(counts["setups"], 1)
            self.assertEqual(counts["open_positions"], 1)
            self.assertEqual(counts["closed_positions"], 1)
            self.assertEqual(counts["processed_messages"], 1)
            self.assertGreaterEqual(counts["decisions"], 1)


if __name__ == "__main__":
    unittest.main()
