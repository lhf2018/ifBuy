from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), default="me")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), default=1)
    name: Mapped[str] = mapped_column(String(128))
    # base_currency：汇总展示与收益率换算基准（账本可同时持有多种现金）
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    initial_cash_cents: Mapped[int] = mapped_column(BigInteger, default=0)  # legacy / 冗余
    cash_balance_cents: Mapped[int] = mapped_column(BigInteger, default=0)  # legacy 同步 base 币种余额
    status: Mapped[str] = mapped_column(String(16), default="active")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WalletBalance(Base):
    """账本多币种现金余额。"""

    __tablename__ = "wallet_balances"
    __table_args__ = (UniqueConstraint("account_id", "currency", name="uk_wallet"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    currency: Mapped[str] = mapped_column(String(8))  # CNY | USD
    balance_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CashFlow(Base):
    __tablename__ = "cash_flows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # initial|deposit|withdraw|fx_out|fx_in
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class CashLedger(Base):
    __tablename__ = "cash_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    type: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    ref_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    balance_after_cents: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class FxTrade(Base):
    """账本内换汇记录。"""

    __tablename__ = "fx_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    from_currency: Mapped[str] = mapped_column(String(8))
    to_currency: Mapped[str] = mapped_column(String(8))
    from_amount_cents: Mapped[int] = mapped_column(BigInteger)
    to_amount_cents: Mapped[int] = mapped_column(BigInteger)
    rate_e6: Mapped[int] = mapped_column(BigInteger)  # to/from * 1e6
    rate_source: Mapped[str] = mapped_column(String(16), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Instrument(Base):
    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    instrument_type: Mapped[str] = mapped_column(String(16))  # equity|etf|spot
    theme: Mapped[str | None] = mapped_column(String(64), nullable=True)
    asset_class: Mapped[str] = mapped_column(String(32))
    market: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(8))
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    tick_size_e4: Mapped[int] = mapped_column(Integer, default=100)  # 0.01
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Bar(Base):
    __tablename__ = "bars"
    __table_args__ = (
        UniqueConstraint("symbol", "interval", "ts", "adjust", name="uk_bars"),
        Index("ix_bars_lookup", "symbol", "interval", "adjust"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    interval: Mapped[str] = mapped_column(String(8))
    ts: Mapped[str] = mapped_column(String(32))
    adjust: Mapped[str] = mapped_column(String(16), default="none")
    open_e4: Mapped[int] = mapped_column(BigInteger)
    high_e4: Mapped[int] = mapped_column(BigInteger)
    low_e4: Mapped[int] = mapped_column(BigInteger)
    close_e4: Mapped[int] = mapped_column(BigInteger)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    finalized: Mapped[bool] = mapped_column(Boolean, default=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uk_watchlist"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, default=1)
    symbol: Mapped[str] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("account_id", "client_order_id", name="uk_client_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    client_order_id: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16), default="market")
    qty_micros: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="filled")
    fee_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    expected_price_e4: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fill_price_e4: Mapped[int] = mapped_column(BigInteger)
    price_source: Mapped[str] = mapped_column(String(16))
    client_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    emotion_tag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    trades: Mapped[list[Trade]] = relationship("Trade", back_populates="order")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    price_e4: Mapped[int] = mapped_column(BigInteger)
    qty_micros: Mapped[int] = mapped_column(BigInteger)
    fee_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    traded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    price_source: Mapped[str] = mapped_column(String(16))

    order: Mapped[Order] = relationship("Order", back_populates="trades")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("account_id", "symbol", name="uk_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    qty_micros: Mapped[int] = mapped_column(BigInteger)
    avg_cost_e4: Mapped[int] = mapped_column(BigInteger)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PositionAdjustment(Base):
    __tablename__ = "position_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reason: Mapped[str] = mapped_column(String(32))
    qty_delta_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_delta_e4: Mapped[int] = mapped_column(BigInteger, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="entry_reason")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FeeRule(Base):
    __tablename__ = "fee_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), default="global")
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    market: Mapped[str | None] = mapped_column(String(8), nullable=True)
    instrument_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # rates in bps * 100 or as string decimals stored as text for clarity
    buy_commission_rate: Mapped[str] = mapped_column(String(32), default="0.00025")
    buy_min_commission_cents: Mapped[int] = mapped_column(Integer, default=500)
    buy_stamp_tax_rate: Mapped[str] = mapped_column(String(32), default="0")
    buy_transfer_fee_rate: Mapped[str] = mapped_column(String(32), default="0.00001")
    sell_commission_rate: Mapped[str] = mapped_column(String(32), default="0.00025")
    sell_min_commission_cents: Mapped[int] = mapped_column(Integer, default=500)
    sell_stamp_tax_rate: Mapped[str] = mapped_column(String(32), default="0.0005")
    sell_transfer_fee_rate: Mapped[str] = mapped_column(String(32), default="0.00001")
    sell_sec_fee_rate: Mapped[str] = mapped_column(String(32), default="0")


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "snapshot_date", name="uk_snapshot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    snapshot_date: Mapped[str] = mapped_column(String(10))
    total_equity_cents: Mapped[int] = mapped_column(BigInteger)
    cash_cents: Mapped[int] = mapped_column(BigInteger)
    market_value_cents: Mapped[int] = mapped_column(BigInteger)
    valuation_basis: Mapped[str] = mapped_column(String(16), default="api")
