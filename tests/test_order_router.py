from __future__ import annotations

import unittest

from trade_relay.config import Settings
from trade_relay.models import EventType, Side, SignalEvent, SignalSetup
from trade_relay.order_router import maybe_create_order_intent
from trade_relay.runtime_state import RuntimeState


def _settings(mode: str = "paper") -> Settings:
    return Settings(
        telegram_api_id="1",
        telegram_api_hash="h",
        telegram_phone="+10000000000",
        telegram_session_name="s",
        vip_channel_ids=[-1001],
        telegram_bot_token="b",
        telegram_allowed_user_id=1,
        toobit_api_key="k",
        toobit_api_secret="s",
        toobit_base_url="https://api.toobit.com",
        toobit_futures_base_url="https://fapi.toobit.com",
        trading_mode=mode,
        default_leverage=10,
        max_leverage=15,
        risk_per_trade_percent=1.0,
        paper_account_balance_usdt=1000.0,
        margin_mode="cross",
        one_position_per_symbol=True,
        log_level="INFO",
        state_db_path="trade_relay.db",
    )


def _state_with_setup() -> RuntimeState:
    st = RuntimeState()
    st.setups_by_symbol["BTC/USDT"] = SignalSetup(
        symbol="BTC/USDT",
        side=Side.SHORT,
        entry_low=100.0,
        entry_high=101.0,
        tp1=99.0,
        tp2=98.0,
        tp3=97.0,
        stop_loss=102.0,
    )
    return st


class TestOrderRouter(unittest.TestCase):
    def test_paper_intent_created_on_accepted_entry(self):
        settings = _settings("paper")
        state = _state_with_setup()
        event = SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="BTC/USDT", side=Side.SHORT)
        note = maybe_create_order_intent(settings, state, event, "ENTRY_ACCEPTED_DRYRUN BTC/USDT SHORT")
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("PAPER_ORDER_INTENT", note)
        self.assertEqual(len(state.order_intents), 1)

    def test_live_mode_is_intent_only_blocked(self):
        settings = _settings("live")
        state = _state_with_setup()
        event = SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="BTC/USDT", side=Side.SHORT)
        note = maybe_create_order_intent(settings, state, event, "ENTRY_ACCEPTED_DRYRUN BTC/USDT SHORT")
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("LIVE_BLOCKED_INTENT_ONLY", note)

    def test_non_accepted_entry_does_nothing(self):
        settings = _settings("paper")
        state = _state_with_setup()
        event = SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="BTC/USDT", side=Side.SHORT)
        note = maybe_create_order_intent(settings, state, event, "ENTRY_SKIPPED_NO_SETUP")
        self.assertIsNone(note)
        self.assertEqual(len(state.order_intents), 0)


if __name__ == "__main__":
    unittest.main()
