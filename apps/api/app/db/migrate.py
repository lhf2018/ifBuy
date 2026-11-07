"""Lightweight SQLite migrations for multi-currency wallets."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.session import Base
from app import models  # noqa: F401


def _cols(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def run_migrations(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        # cash_flows.currency
        if "cash_flows" in Base.metadata.tables:
            cols = _cols(conn, "cash_flows")
            if "currency" not in cols:
                conn.execute(text("ALTER TABLE cash_flows ADD COLUMN currency VARCHAR(8) DEFAULT 'CNY'"))
        if "cash_ledger" in Base.metadata.tables:
            cols = _cols(conn, "cash_ledger")
            if "currency" not in cols:
                conn.execute(text("ALTER TABLE cash_ledger ADD COLUMN currency VARCHAR(8) DEFAULT 'CNY'"))

        # backfill wallet_balances from legacy single-currency accounts
        accounts = conn.execute(text("SELECT id, currency, cash_balance_cents FROM accounts")).fetchall()
        for acc_id, currency, bal in accounts:
            cur = currency or "CNY"
            exists = conn.execute(
                text("SELECT 1 FROM wallet_balances WHERE account_id=:a AND currency=:c"),
                {"a": acc_id, "c": cur},
            ).fetchone()
            if not exists:
                conn.execute(
                    text(
                        "INSERT INTO wallet_balances (account_id, currency, balance_cents, updated_at) "
                        "VALUES (:a, :c, :b, CURRENT_TIMESTAMP)"
                    ),
                    {"a": acc_id, "c": cur, "b": bal or 0},
                )
            # ensure CNY / USD / HKD rows exist
            for c in ("CNY", "USD", "HKD"):
                exists = conn.execute(
                    text("SELECT 1 FROM wallet_balances WHERE account_id=:a AND currency=:c"),
                    {"a": acc_id, "c": c},
                ).fetchone()
                if not exists:
                    conn.execute(
                        text(
                            "INSERT INTO wallet_balances (account_id, currency, balance_cents, updated_at) "
                            "VALUES (:a, :c, 0, CURRENT_TIMESTAMP)"
                        ),
                        {"a": acc_id, "c": c},
                    )
            # fix null currency on flows/ledger
            conn.execute(text("UPDATE cash_flows SET currency = :c WHERE currency IS NULL OR currency = ''"), {"c": cur})
            conn.execute(text("UPDATE cash_ledger SET currency = :c WHERE currency IS NULL OR currency = ''"), {"c": cur})
