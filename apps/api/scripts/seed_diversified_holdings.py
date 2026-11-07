"""Add HK / fund / futures / crypto / custom holdings into 我的练习账本 (id=1)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.core.money import money_to_cents, notional_cents, price_to_e4, qty_to_micros
from app.db.session import SessionLocal, init_db
from app.models import (
    Account,
    CashFlow,
    CashLedger,
    Instrument,
    Note,
    Order,
    Position,
    PositionAdjustment,
    Trade,
    WatchlistItem,
)
from app.providers.base import InstrumentDraft
from app.services.accounts import ensure_wallets, get_wallet, _append_ledger, get_account_or_404
from app.services.equity import rebuild_equity_curve
from app.services.market import _upsert_instrument
from app.services.trading import account_summary, list_positions


ACCOUNT_ID = 1

INSTRUMENTS: list[InstrumentDraft] = [
    InstrumentDraft("00700.HK", "00700", "腾讯控股", "equity", "equity_hk", "HK", "HKD", 100, 0.01, provider="akshare_hk"),
    InstrumentDraft("09988.HK", "09988", "阿里巴巴-SW", "equity", "equity_hk", "HK", "HKD", 100, 0.01, provider="akshare_hk"),
    InstrumentDraft("110022.OF", "110022", "易方达消费行业股票", "fund", "fund_cn", "CN", "CNY", 1, 0.0001, provider="akshare_fund"),
    InstrumentDraft("005827.OF", "005827", "易方达蓝筹精选混合", "fund", "fund_cn", "CN", "CNY", 1, 0.0001, provider="akshare_fund"),
    InstrumentDraft("AU0.FUT", "AU0", "沪金主连", "future", "commodity", "CN", "CNY", 1, 0.01, theme="commodity", provider="akshare_fut"),
    InstrumentDraft("SC0.FUT", "SC0", "原油主连", "future", "commodity", "CN", "CNY", 1, 0.01, theme="commodity", provider="akshare_fut"),
    InstrumentDraft("BTC-USD", "BTC", "Bitcoin", "crypto", "crypto", "CRYPTO", "USD", 1, 0.01, provider="binance"),
    InstrumentDraft("ETH-USD", "ETH", "Ethereum", "crypto", "crypto", "CRYPTO", "USD", 1, 0.01, provider="binance"),
    InstrumentDraft("CUST.HOUSE1", "HOUSE1", "自住房", "custom", "custom", "OTC", "CNY", 1, 0.01, provider="manual"),
]

# (symbol, side, qty, price, fee_cents, days_ago, note)
FILLS = [
    ("00700.HK", "buy", 200, 380.0, 500, 22, "港股通·腾讯"),
    ("09988.HK", "buy", 300, 92.0, 500, 18, "港股·阿里"),
    ("110022.OF", "buy", 8000, 2.85, 0, 25, "定投消费基金"),
    ("005827.OF", "buy", 5000, 1.62, 0, 20, "蓝筹精选"),
    ("AU0.FUT", "buy", 2, 820.0, 200, 12, "纸面黄金期货"),
    ("SC0.FUT", "buy", 1, 520.0, 200, 10, "纸面原油"),
    ("BTC-USD", "buy", 0.15, 68000.0, 0, 16, "比特币仓位"),
    ("ETH-USD", "buy", 1.2, 3200.0, 0, 14, "以太坊"),
    ("CUST.HOUSE1", "buy", 1, 3000000.0, 0, 28, "自住房入账"),
]


def ensure_instruments(db) -> None:
    for d in INSTRUMENTS:
        inst = _upsert_instrument(db, d)
        if d.symbol == "CUST.HOUSE1":
            inst.meta_json = json.dumps({"manual_price": 3200000, "note": "模拟估值"}, ensure_ascii=False)
            db.commit()


def deposit(db, account: Account, currency: str, amount: float, days_ago: int, note: str) -> None:
    cents = money_to_cents(amount)
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    ensure_wallets(db, account.id)
    w = get_wallet(db, account.id, currency)
    w.balance_cents += cents
    w.updated_at = when
    db.add(
        CashFlow(
            account_id=account.id,
            type="deposit",
            currency=currency,
            amount_cents=cents,
            note=note,
            occurred_at=when,
        )
    )
    db.add(
        CashLedger(
            account_id=account.id,
            ts=when,
            type="deposit",
            currency=currency,
            amount_cents=cents,
            balance_after_cents=w.balance_cents,
            note=note,
        )
    )
    if currency == account.currency:
        account.cash_balance_cents = w.balance_cents


def append_fill(
    db,
    account: Account,
    *,
    seq: int,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    fee: int,
    days_ago: int,
    note: str,
) -> None:
    inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
    assert inst
    when = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=3)
    ccy = inst.currency.upper()
    qty_m = qty_to_micros(qty)
    px_e4 = price_to_e4(price)
    notional = notional_cents(px_e4, qty_m)
    delta = -(notional + fee) if side == "buy" else (notional - fee)

    order = Order(
        account_id=account.id,
        client_order_id=f"div-{account.id}-{seq:03d}-{symbol.replace('.', '').replace('-', '')}",
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
            account_id=account.id,
            symbol=symbol,
            side=side,
            price_e4=px_e4,
            qty_micros=qty_m,
            fee_cents=fee,
            traded_at=when,
            price_source="manual",
        )
    )
    db.add(
        Note(
            order_id=order.id,
            account_id=account.id,
            symbol=symbol,
            kind="entry_reason",
            body=note,
            created_at=when,
            updated_at=when,
        )
    )
    w = get_wallet(db, account.id, ccy)
    if w.balance_cents + delta < 0:
        # top-up so paper ledger never goes negative mid-seed
        need = -(w.balance_cents + delta)
        w.balance_cents += need
        db.add(
            CashFlow(
                account_id=account.id,
                type="deposit",
                currency=ccy,
                amount_cents=need,
                note=f"种子补仓·{ccy}",
                occurred_at=when - timedelta(hours=1),
            )
        )
    w.balance_cents += delta
    db.add(
        CashLedger(
            account_id=account.id,
            ts=when,
            type=side,
            currency=ccy,
            amount_cents=delta,
            ref_order_id=order.id,
            balance_after_cents=w.balance_cents,
            note=f"{'买入' if side == 'buy' else '卖出'} {symbol}",
        )
    )

    pos = (
        db.query(Position)
        .filter(Position.account_id == account.id, Position.symbol == symbol)
        .first()
    )
    if side == "buy":
        if not pos:
            db.add(
                Position(
                    account_id=account.id,
                    symbol=symbol,
                    qty_micros=qty_m,
                    avg_cost_e4=px_e4,
                    opened_at=when,
                    updated_at=when,
                )
            )
        else:
            total_cost = pos.avg_cost_e4 * pos.qty_micros + px_e4 * qty_m
            new_qty = pos.qty_micros + qty_m
            pos.qty_micros = new_qty
            pos.avg_cost_e4 = int(total_cost / new_qty) if new_qty else 0
            pos.updated_at = when
    else:
        if not pos or pos.qty_micros < qty_m:
            raise RuntimeError(f"cannot sell {symbol}")
        pos.qty_micros -= qty_m
        pos.updated_at = when
        if pos.qty_micros == 0:
            db.delete(pos)


def maybe_dividend(db, account: Account) -> None:
    """Demo cash dividend on 茅台 if held."""
    symbol = "600519.SH"
    pos = db.query(Position).filter(Position.account_id == account.id, Position.symbol == symbol).first()
    if not pos:
        return
    exists = (
        db.query(PositionAdjustment)
        .filter(
            PositionAdjustment.account_id == account.id,
            PositionAdjustment.symbol == symbol,
            PositionAdjustment.reason == "dividend",
        )
        .first()
    )
    if exists:
        return
    from app.core.money import micros_to_qty, cents_to_money
    from decimal import Decimal

    qty = float(micros_to_qty(pos.qty_micros))
    cash_per = 25.0
    cents = money_to_cents(Decimal(str(qty)) * Decimal(str(cash_per)))
    when = datetime.now(timezone.utc) - timedelta(days=5)
    _append_ledger(db, account, "dividend", cents, "CNY", note=f"分红 {symbol} @ {cash_per}")
    db.add(
        PositionAdjustment(
            account_id=account.id,
            symbol=symbol,
            ts=when,
            reason="dividend",
            qty_delta_micros=0,
            cost_delta_e4=0,
            note=f"分红 {symbol} · 共 {float(cents_to_money(cents))} CNY",
        )
    )


def ensure_watch(db, symbols: list[str]) -> None:
    existing = {w.symbol for w in db.query(WatchlistItem).all()}
    for i, sym in enumerate(symbols):
        if sym in existing:
            continue
        db.add(WatchlistItem(symbol=sym, sort_order=100 + i))


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        account = get_account_or_404(db, ACCOUNT_ID)
        ensure_instruments(db)
        ensure_wallets(db, account.id)

        # skip if already diversified
        held = {p.symbol for p in db.query(Position).filter(Position.account_id == account.id)}
        needed = [s for s, *_ in [(f[0],) for f in FILLS] if s not in held]
        # unique symbols from FILLS not yet held
        wanted = []
        for row in FILLS:
            if row[0] not in held and row[0] not in wanted:
                wanted.append(row[0])
        if not wanted:
            print(f"account {ACCOUNT_ID} already has diversified symbols; nothing to add")
            for p in list_positions(db, ACCOUNT_ID):
                print(f"  {p['symbol']:16} {p['name']}")
            return

        # fund wallets for new markets
        if get_wallet(db, account.id, "HKD").balance_cents < money_to_cents(150000):
            deposit(db, account, "HKD", 200000, 30, "港股通备付金")
        if get_wallet(db, account.id, "USD").balance_cents < money_to_cents(20000):
            deposit(db, account, "USD", 25000, 30, "加密/美股补仓")
        if get_wallet(db, account.id, "CNY").balance_cents < money_to_cents(500000):
            deposit(db, account, "CNY", 800000, 30, "基金期货房产补仓")

        seq = 500
        for symbol, side, qty, price, fee, days_ago, note in FILLS:
            if symbol in held:
                continue
            seq += 1
            append_fill(
                db,
                account,
                seq=seq,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                fee=fee,
                days_ago=days_ago,
                note=note,
            )
            held.add(symbol)

        maybe_dividend(db, account)

        cny = get_wallet(db, account.id, "CNY")
        account.cash_balance_cents = cny.balance_cents
        ensure_watch(db, [d.symbol for d in INSTRUMENTS])
        db.commit()

        rebuild_equity_curve(db, account.id)
        summary = account_summary(db, account.id)
        print(f"account_id={account.id} name={account.name}")
        print(f"wallets={summary.get('wallets')}")
        print(f"total_equity={summary['total_equity']} return_pct={summary.get('return_pct')}%")
        print("positions:")
        for p in list_positions(db, account.id):
            print(f"  {p['symbol']:16} qty={p['qty']:<10} cost={p['avg_cost']}  {p['name']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
