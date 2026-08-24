from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .models import Side, SignalSetup
from .runtime_state import ClosedPositionRecord, RuntimeState, VirtualPosition


class StateRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with closing(self.connect()) as conn:
            with conn:
                conn.executescript(
                    """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS setups (
                    symbol TEXT PRIMARY KEY,
                    side TEXT NOT NULL,
                    entry_low REAL NOT NULL,
                    entry_high REAL NOT NULL,
                    tp1 REAL NOT NULL,
                    tp2 REAL NOT NULL,
                    tp3 REAL,
                    stop_loss REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS open_positions (
                    symbol TEXT PRIMARY KEY,
                    side TEXT NOT NULL,
                    entry_status TEXT NOT NULL,
                    size_percent_open REAL NOT NULL,
                    tp1_hit INTEGER NOT NULL,
                    sl_moved_to_breakeven INTEGER NOT NULL,
                    opened_at TEXT NOT NULL,
                    last_event_at TEXT NOT NULL,
                    closed_at TEXT,
                    close_reason TEXT
                );

                CREATE TABLE IF NOT EXISTS closed_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    final_status TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT NOT NULL,
                    close_reason TEXT NOT NULL,
                    tp1_hit INTEGER NOT NULL,
                    sl_moved_to_breakeven INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_key TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_key TEXT,
                    event_summary TEXT,
                    decision TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                    """
                )

    def load_state(self, one_position_per_symbol: bool) -> RuntimeState:
        state = RuntimeState(one_position_per_symbol=one_position_per_symbol)

        with closing(self.connect()) as conn:
            paused_row = conn.execute("SELECT value FROM meta WHERE key='paused'").fetchone()
            if paused_row:
                state.paused = paused_row["value"].lower() == "true"

            for row in conn.execute("SELECT * FROM setups"):
                state.setups_by_symbol[row["symbol"]] = SignalSetup(
                    symbol=row["symbol"],
                    side=Side(row["side"]),
                    entry_low=row["entry_low"],
                    entry_high=row["entry_high"],
                    tp1=row["tp1"],
                    tp2=row["tp2"],
                    tp3=row["tp3"],
                    stop_loss=row["stop_loss"],
                )

            for row in conn.execute("SELECT * FROM open_positions"):
                pos = VirtualPosition(
                    symbol=row["symbol"],
                    side=row["side"],
                    entry_status=row["entry_status"],
                    size_percent_open=row["size_percent_open"],
                    tp1_hit=bool(row["tp1_hit"]),
                    sl_moved_to_breakeven=bool(row["sl_moved_to_breakeven"]),
                    opened_at=row["opened_at"],
                    last_event_at=row["last_event_at"],
                    closed_at=row["closed_at"],
                    close_reason=row["close_reason"],
                )
                state.positions_by_symbol[pos.symbol] = pos
                if pos.size_percent_open > 0:
                    state.open_symbols.add(pos.symbol)

            for row in conn.execute(
                "SELECT symbol, side, final_status, opened_at, closed_at, close_reason, tp1_hit, sl_moved_to_breakeven "
                "FROM closed_positions ORDER BY id DESC LIMIT 400"
            ):
                state.closed_positions.appendleft(
                    ClosedPositionRecord(
                        symbol=row["symbol"],
                        side=row["side"],
                        final_status=row["final_status"],
                        opened_at=row["opened_at"],
                        closed_at=row["closed_at"],
                        close_reason=row["close_reason"],
                        tp1_hit=bool(row["tp1_hit"]),
                        sl_moved_to_breakeven=bool(row["sl_moved_to_breakeven"]),
                    )
                )

            for row in conn.execute("SELECT message_key FROM processed_messages ORDER BY rowid DESC LIMIT 2000"):
                state.processed_message_keys.appendleft(row["message_key"])
                state._processed_lookup.add(row["message_key"])

            for row in conn.execute("SELECT decision FROM decisions ORDER BY id DESC LIMIT 300"):
                state.recent_decisions.appendleft(row["decision"])

        return state

    def persist_state_snapshot(self, state: RuntimeState) -> None:
        with closing(self.connect()) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES('paused', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("true" if state.paused else "false",),
                )

                conn.execute("DELETE FROM setups")
                conn.executemany(
                    "INSERT INTO setups(symbol, side, entry_low, entry_high, tp1, tp2, tp3, stop_loss, updated_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    [
                        (
                            s.symbol,
                            s.side.value if hasattr(s.side, "value") else str(s.side),
                            s.entry_low,
                            s.entry_high,
                            s.tp1,
                            s.tp2,
                            s.tp3,
                            s.stop_loss,
                        )
                        for s in state.setups_by_symbol.values()
                    ],
                )

                conn.execute("DELETE FROM open_positions")
                conn.executemany(
                    "INSERT INTO open_positions(symbol, side, entry_status, size_percent_open, tp1_hit, sl_moved_to_breakeven, opened_at, last_event_at, closed_at, close_reason) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            p.symbol,
                            p.side,
                            p.entry_status,
                            p.size_percent_open,
                            int(p.tp1_hit),
                            int(p.sl_moved_to_breakeven),
                            p.opened_at,
                            p.last_event_at,
                            p.closed_at,
                            p.close_reason,
                        )
                        for p in state.positions_by_symbol.values()
                    ],
                )

                conn.execute("DELETE FROM processed_messages")
                conn.executemany(
                    "INSERT INTO processed_messages(message_key) VALUES(?)",
                    [(k,) for k in state.processed_message_keys],
                )

                conn.execute("DELETE FROM decisions")
                conn.executemany(
                    "INSERT INTO decisions(message_key, event_summary, decision) VALUES(NULL, NULL, ?)",
                    [(d,) for d in state.recent_decisions],
                )

                conn.execute("DELETE FROM closed_positions")
                conn.executemany(
                    "INSERT INTO closed_positions(symbol, side, final_status, opened_at, closed_at, close_reason, tp1_hit, sl_moved_to_breakeven) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            c.symbol,
                            c.side,
                            c.final_status,
                            c.opened_at,
                            c.closed_at,
                            c.close_reason,
                            int(c.tp1_hit),
                            int(c.sl_moved_to_breakeven),
                        )
                        for c in state.closed_positions
                    ],
                )

    def table_counts(self) -> dict[str, int]:
        tables = ["setups", "open_positions", "closed_positions", "processed_messages", "decisions"]
        out: dict[str, int] = {}
        with closing(self.connect()) as conn:
            for t in tables:
                row = conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()
                out[t] = int(row["c"]) if row else 0
        return out
