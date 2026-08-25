from __future__ import annotations

from .config import Settings
from .execution import build_entry_order_intent
from .models import EventType, SignalEvent
from .runtime_state import RuntimeState
from .toobit_client import ToobitAPIError, ToobitClient, extract_summary_snapshot


def _demo_balance_from_toobit(settings: Settings, toobit_client: ToobitClient) -> float:
    if not settings.toobit_api_key or not settings.toobit_api_secret:
        raise ToobitAPIError("Toobit API key/secret missing for paper sizing")

    # Runs async call from sync context carefully: caller may already be in event loop.
    # So this function should only be used by async wrapper below.
    raise RuntimeError("Use maybe_create_order_intent_async instead")


async def maybe_create_order_intent_async(
    settings: Settings,
    state: RuntimeState,
    event: SignalEvent,
    decision: str,
    toobit_client: ToobitClient,
) -> str | None:
    if settings.trading_mode not in {"paper", "live"}:
        return None

    if event.event_type != EventType.ENTRY_TRIGGER:
        return None

    if not decision.startswith("ENTRY_ACCEPTED_DRYRUN"):
        return None

    setup = state.setups_by_symbol.get(event.symbol)
    if setup is None:
        return None

    if not settings.toobit_api_key or not settings.toobit_api_secret:
        return "ORDER_INTENT_SKIPPED_NO_TOOBIT_KEYS"

    account = await toobit_client.account_info_futures()
    wallet_balance = float(account.get("totalWalletBalance", 0.0) or 0.0)
    if wallet_balance <= 0:
        return "ORDER_INTENT_SKIPPED_ZERO_BALANCE"

    entry_reference = (setup.entry_low + setup.entry_high) / 2.0
    intent = build_entry_order_intent(
        symbol=event.symbol,
        side=event.side,
        entry_price=entry_reference,
        stop_loss=setup.stop_loss,
        account_balance_usdt=wallet_balance,
        risk_percent=settings.risk_per_trade_percent,
        leverage=settings.default_leverage,
        reason=f"{settings.trading_mode}:entry_trigger",
    )
    state.add_order_intent(intent)

    if settings.trading_mode == "live":
        return f"LIVE_BLOCKED_INTENT_ONLY {intent.symbol} qty={intent.quantity} lev={intent.leverage}"

    return f"PAPER_ORDER_INTENT {intent.symbol} {intent.side} qty={intent.quantity} lev={intent.leverage}"


async def build_summary_text(toobit_client: ToobitClient) -> str:
    account = await toobit_client.account_info_futures()
    positions = await toobit_client.position_risk_futures()
    snap = extract_summary_snapshot(account, positions, today_realized_pnl=0.0)

    lines: list[str] = []
    lines.append("SUMMARY")
    lines.append("")
    lines.append(
        f"Current Balance: {snap['current_balance']:.3f} ({snap['today_realized_pnl']:+.3f})"
    )
    lines.append(f"Unrealized PnL: {snap['unrealized_pnl_total']:+.3f}")
    lines.append("")
    lines.append("Open Positions:")

    open_positions = snap["open_positions"]
    if not open_positions:
        lines.append("(none)")
        return "\n".join(lines)

    for idx, pos in enumerate(open_positions, start=1):
        lines.append(f"{idx}. {pos['symbol']} ({pos['side']} | {pos['leverage']}x):")
        lines.append(f"Average Entry Price: {pos['entry_price']}")
        lines.append(f"Current Price: {pos['mark_price']}")
        lines.append(f"Margin (USDT): {pos['margin_usdt']:.3f}")
        lines.append(
            f"Unrealized PnL: {pos['unrealized_pnl']:+.3f} USDT ({pos['unrealized_pnl_percent']:+.2f}%)"
        )

    return "\n".join(lines)
