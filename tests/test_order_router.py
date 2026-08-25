from __future__ import annotations

import unittest

from trade_relay.config import Settings
from trade_relay.models import EventType, Side, SignalEvent, SignalSetup
from trade_relay.order_router import maybe_create_order_intent_async
from trade_relay.runtime_state import RuntimeState
from trade_relay.main import select_latest_setup


class _FakeToobit:
    async def account_info_futures(self):
        return {"totalWalletBalance": "100000"}


class _Message:
    def __init__(self, message_id: int, text: str):
        self.id = message_id
        self.raw_text = text


def _settings(mode: str = "paper") -> Settings:
    return Settings(
        telegram_api_id="1",
        telegram_api_hash="h",
        telegram_phone="+100****0000",
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


class TestOrderRouter(unittest.IsolatedAsyncioTestCase):
    def test_select_latest_setup_from_newest_first_messages(self):
        older = _Message(
            5547,
            "LBANK Futures SHORT #ETH/USDT Enter price: 2481.8 - 2496.6 "
            "TP1: 2466.5 TP2: 2451.1 TP3: 2436.1 Normal Stop Loss: 2512.5 #Signal",
        )
        newer = _Message(
            5550,
            "LBANK Futures SHORT #AVAX/USDT Enter price: 7.530 - 7.616 "
            "TP1: 7.441 TP2: 7.352 TP3: 7.263 Normal Stop Loss: 7.708 #Signal",
        )

        selected = select_latest_setup([newer, older])

        self.assertIsNotNone(selected)
        assert selected is not None
        message, event = selected
        self.assertEqual(message.id, 5550)
        self.assertEqual(event.symbol, "AVAX/USDT")

    async def test_paper_intent_created_on_accepted_entry(self):
        settings = _settings("paper")
        state = _state_with_setup()
        event = SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="BTC/USDT", side=Side.SHORT)
        note = await maybe_create_order_intent_async(
            settings,
            state,
            event,
            "ENTRY_ACCEPTED_DRYRUN BTC/USDT SHORT",
            _FakeToobit(),
        )
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("PAPER_ORDER_INTENT", note)
        self.assertEqual(len(state.order_intents), 1)

    async def test_live_mode_is_intent_only_blocked(self):
        settings = _settings("live")
        state = _state_with_setup()
        event = SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="BTC/USDT", side=Side.SHORT)
        note = await maybe_create_order_intent_async(
            settings,
            state,
            event,
            "ENTRY_ACCEPTED_DRYRUN BTC/USDT SHORT",
            _FakeToobit(),
        )
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("LIVE_BLOCKED_INTENT_ONLY", note)

    async def test_non_accepted_entry_does_nothing(self):
        settings = _settings("paper")
        state = _state_with_setup()
        event = SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="BTC/USDT", side=Side.SHORT)
        note = await maybe_create_order_intent_async(
            settings,
            state,
            event,
            "ENTRY_SKIPPED_NO_SETUP",
            _FakeToobit(),
        )
        self.assertIsNone(note)
        self.assertEqual(len(state.order_intents), 0)

    async def test_explicit_test_entry_can_create_intent_for_existing_position(self):
        settings = _settings("paper")
        state = _state_with_setup()
        state.open_symbols.add("BTC/USDT")
        event = SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol="BTC/USDT", side=Side.SHORT)

        note = await maybe_create_order_intent_async(
            settings,
            state,
            event,
            "TEST_ENTRY_ACCEPTED_EXISTING_OPEN BTC/USDT SHORT",
            _FakeToobit(),
        )

        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("PAPER_ORDER_INTENT", note)
        self.assertEqual(len(state.order_intents), 1)


if __name__ == "__main__":
    unittest.main()
