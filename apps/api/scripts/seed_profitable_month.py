"""Create a demo ledger: last ~30 days buy-low / sell-high, then print return."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.core.money import (
    cents_to_money,
    money_to_cents,
    notional_cents,
    price_to_e4,
    qty_to_micros,
)
from app.db.session import SessionLocal, init_db
from app.models import (
    Account,
    Bar,
    CashFlow,
    CashLedger,
    Instrument,
    Note,
    Order,
    Position,
    Trade,
    WalletBalance,
    WatchlistItem,
)
from app.services.accounts import ensure_wallets, get_wallet, account_to_dict
from app.services.equity import rebuild_equity_curve
from app.services.trading import account_summary


INSTRUMENTS = [
    dict(
        symbol="600519.SH",
        ticker="600519",
        name="贵州茅台",
        instrument_type="equity",
        theme=None,
        asset_class="equity_cn",
        market="CN",
        currency="CNY",
        lot_size=100,
        tick_size_e4=100,
        provider="akshare",
    ),
    dict(
        symbol="000001.SZ",
        ticker="000001",
        name="平安银行",
        instrument_type="equity",
        theme=None,
        asset_class="equity_cn",
        market="CN",
        currency="CNY",
        lot_size=100,
        tick_size_e4=100,
        provider="akshare",
    ),
    dict(
        symbol="518880.SH",
        ticker="518880",
        name="华安黄金易ETF",
        instrument_type="etf",
        theme="gold",
        asset_class="gold",
        market="CN",
        currency="CNY",
        lot_size=100,
        tick_size_e4=100,
        provider="akshare",
    ),
    dict(
        symbol="AAPL",
        ticker="AAPL",
        name="Apple",
        instrument_type="equity",
        theme=None,
        asset_class="equity_us",
        market="US",
        currency="USD",
        lot_size=1,
        tick_size_e4=100,
        provider="yahoo",
    ),
    dict(
        symbol="GLD",
        ticker="GLD",
        name="SPDR Gold Shares",
        instrument_type="etf",
        theme="gold",
        asset_class="gold",
        market="US",
        currency="USD",
        lot_size=1,
        tick_size_e4=100,
        provider="yahoo",
    ),
]

# round-trip plans: buy low then sell high within the month
# (symbol, buy_day_ago, sell_day_ago, qty, buy_px, sell_px, buy_fee, sell_fee)
ROUNDS = [
    ("600519.SH", 28, 21, 100, 1520.0, 1680.0, 500, 500),
    ("600519.SH", 18, 10, 100, 1580.0, 1720.0, 500, 500),
    ("000001.SZ", 26, 19, 2000, 10.80, 11.65, 500, 500),
    ("000001.SZ", 14, 5, 1500, 11.20, 12.05, 500, 500),
    ("518880.SH", 25, 16, 3000, 7.20, 8.05, 500, 500),
    ("518880.SH", 12, 4, 2000, 7.55, 8.35, 500, 500),
    ("AAPL", 27, 20, 40, 168.0, 186.5, 0, 0),
    ("AAPL", 15, 7, 30, 175.0, 192.0, 0, 0),
    ("GLD", 24, 17, 40, 198.0, 218.0, 0, 0),
    ("GLD", 11, 3, 25, 205.0, 222.5, 0, 0),
]


def upsert_instruments(db) -> None:
    for d in INSTRUMENTS:
        inst = db.query(Instrument).filter(Instrument.symbol == d["symbol"]).first()
        if inst:
            for k, v in d.items():
                setattr(inst, k, v)
        else:
            db.add(Instrument(**d))
    db.flush()


def append_fill(
    db,
    acc: Account,
    *,
    seq: int,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    fee: int,
    when: datetime,
    note: str | None,
) -> None:
    inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
    assert inst
    ccy = inst.currency
    qty_m = qty_to_micros(qty)
    px_e4 = price_to_e4(price)
    notional = notional_cents(px_e4, qty_m)
    delta = -(notional + fee) if side == "buy" else (notional - fee)

    order = Order(
        account_id=acc.id,
        client_order_id=f"win-{acc.id}-{seq:03d}-{symbol.replace('.', '')}-{side}",
        symbol=symbol,
        side=side,
        qty_micros=qty_m,
        status="filled",
        fee_cents=fee,
        fill_price_e4=px_e4,
        price_source="manual",
        client_note=note,
        created_at=when,
        filled_at=when,
    )
    db.add(order)
    db.flush()
    db.add(
        Trade(
            order_id=order.id,
            account_id=acc.id,
            symbol=symbol,
            side=side,
            price_e4=px_e4,
            qty_micros=qty_m,
            fee_cents=fee,
            traded_at=when,
            price_source="manual",
        )
    )
    if note:
        db.add(
            Note(
                order_id=order.id,
                account_id=acc.id,
                symbol=symbol,
                kind="entry_reason",
                body=note,
                created_at=when,
                updated_at=when,
            )
        )
    w = get_wallet(db, acc.id, ccy)
    w.balance_cents += delta
    db.add(
        CashLedger(
            account_id=acc.id,
            ts=when,
            type=side,
            currency=ccy,
            amount_cents=delta,
            ref_order_id=order.id,
            balance_after_cents=w.balance_cents,
            note=f"{'买入' if side == 'buy' else '卖出'} {symbol}",
        )
    )


def seed_bars(db, last_px: dict[str, float], now: datetime) -> None:
    random.seed(7)
    symbols = [d["symbol"] for d in INSTRUMENTS]
    db.query(Bar).filter(Bar.symbol.in_(symbols)).delete(synchronize_session=False)
    for d in INSTRUMENTS:
        sym = d["symbol"]
        base = float(last_px.get(sym, 100))
        px = base * 0.92
        closes: list[float] = []
        for _ in range(40):
            px = max(px * (1 + random.uniform(-0.012, 0.018)), 0.5)
            closes.append(px)
        closes[-1] = base
        for i, close in enumerate(closes):
            day = (now - timedelta(days=40 - i)).date().isoformat()
            o = close * random.uniform(0.995, 1.005)
            h = max(o, close) * random.uniform(1.0, 1.01)
            l = min(o, close) * random.uniform(0.99, 1.0)
            db.add(
                Bar(
                    symbol=sym,
                    interval="1d",
                    ts=f"{day}T00:00:00+00:00",
                    adjust="none",
                    open_e4=price_to_e4(o),
                    high_e4=price_to_e4(h),
                    low_e4=price_to_e4(l),
                    close_e4=price_to_e4(close),
                    volume=int(random.uniform(1e6, 5e6)),
                    finalized=True,
                )
            )


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        from app.services.accounts import ensure_default_user

        ensure_default_user(db)
        upsert_instruments(db)

        name = "一个月低买高卖"
        # drop prior same-name demo if re-run
        old = db.query(Account).filter(Account.name == name).all()
        for acc in old:
            aid = acc.id
            for model in (Trade, Note, CashLedger, Order, Position, CashFlow, WalletBalance):
                db.query(model).filter(model.account_id == aid).delete(synchronize_session=False)
            from app.models import EquitySnapshot, FxTrade

            db.query(EquitySnapshot).filter(EquitySnapshot.account_id == aid).delete(synchronize_session=False)
            db.query(FxTrade).filter(FxTrade.account_id == aid).delete(synchronize_session=False)
            db.delete(acc)
        db.flush()

        open_cny = money_to_cents(500000)
        open_usd = money_to_cents(30000)
        now = datetime.now(timezone.utc)
        opened = now - timedelta(days=30)

        acc = Account(
            name=name,
            currency="CNY",
            initial_cash_cents=open_cny,
            cash_balance_cents=0,
            status="active",
            created_at=opened,
        )
        db.add(acc)
        db.flush()
        ensure_wallets(db, acc.id)
        for w in db.query(WalletBalance).filter(WalletBalance.account_id == acc.id):
            if w.currency == "CNY":
                w.balance_cents = open_cny
            elif w.currency == "USD":
                w.balance_cents = open_usd

        db.add(
            CashFlow(
                account_id=acc.id,
                type="initial",
                currency="CNY",
                amount_cents=open_cny,
                note="开户本金·人民币",
                occurred_at=opened,
            )
        )
        db.add(
            CashFlow(
                account_id=acc.id,
                type="initial",
                currency="USD",
                amount_cents=open_usd,
                note="开户本金·美元",
                occurred_at=opened,
            )
        )
        db.add(
            CashLedger(
                account_id=acc.id,
                ts=opened,
                type="initial",
                currency="CNY",
                amount_cents=open_cny,
                balance_after_cents=open_cny,
                note="开户本金·人民币",
            )
        )
        db.add(
            CashLedger(
                account_id=acc.id,
                ts=opened,
                type="initial",
                currency="USD",
                amount_cents=open_usd,
                balance_after_cents=open_usd,
                note="开户本金·美元",
            )
        )

        seq = 0
        last_px: dict[str, float] = {}
        for symbol, buy_ago, sell_ago, qty, buy_px, sell_px, buy_fee, sell_fee in ROUNDS:
            seq += 1
            buy_at = now - timedelta(days=buy_ago, hours=2)
            append_fill(
                db,
                acc,
                seq=seq,
                symbol=symbol,
                side="buy",
                qty=qty,
                price=buy_px,
                fee=buy_fee,
                when=buy_at,
                note="低吸",
            )
            seq += 1
            sell_at = now - timedelta(days=sell_ago, hours=4)
            append_fill(
                db,
                acc,
                seq=seq,
                symbol=symbol,
                side="sell",
                qty=qty,
                price=sell_px,
                fee=sell_fee,
                when=sell_at,
                note="高抛",
            )
            last_px[symbol] = sell_px

        # flat residual cash positions none — all round-trips closed
        db.query(Position).filter(Position.account_id == acc.id).delete(synchronize_session=False)

        seed_bars(db, last_px, now)
        db.query(WatchlistItem).delete(synchronize_session=False)
        for i, d in enumerate(INSTRUMENTS):
            db.add(WatchlistItem(symbol=d["symbol"], sort_order=i))

        cny = get_wallet(db, acc.id, "CNY")
        usd = get_wallet(db, acc.id, "USD")
        acc.cash_balance_cents = cny.balance_cents
        db.commit()

        rebuild_equity_curve(db, acc.id)
        summary = account_summary(db, acc.id)

        print(f"account_id={acc.id} name={acc.name}")
        print(f"wallets CNY={float(cents_to_money(cny.balance_cents))} USD={float(cents_to_money(usd.balance_cents))}")
        print(f"total_equity={summary['total_equity']}")
        print(f"net_deposit={summary['net_deposit']}")
        print(f"total_pnl={summary['total_pnl']}")
        print(f"return_pct={summary['return_pct']}%")
        print(f"orders={seq} (all closed round-trips)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
