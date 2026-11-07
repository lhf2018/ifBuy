"""Boost fund + gold holdings on practice ledger so they are visible vs house."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.money import money_to_cents, notional_cents, price_to_e4, qty_to_micros
from app.db.session import SessionLocal, init_db
from app.models import CashFlow, CashLedger, Instrument, Note, Order, Position, Trade, WatchlistItem
from app.providers.base import InstrumentDraft
from app.services.accounts import ensure_wallets, get_account_or_404, get_wallet
from app.services.equity import rebuild_equity_curve
from app.services.market import _upsert_instrument
from app.services.trading import account_summary, list_positions

ACCOUNT_ID = 1

EXTRA = [
    InstrumentDraft("159934.SZ", "159934", "易方达黄金ETF", "etf", "gold", "CN", "CNY", 100, 0.01, theme="gold", provider="akshare"),
    InstrumentDraft("518800.SH", "518800", "国泰黄金ETF", "etf", "gold", "CN", "CNY", 100, 0.01, theme="gold", provider="akshare"),
    InstrumentDraft("IAU", "IAU", "iShares Gold Trust", "etf", "gold", "US", "USD", 1, 0.01, theme="gold", provider="yfinance"),
    InstrumentDraft("000001.OF", "000001", "华夏成长混合", "fund", "fund_cn", "CN", "CNY", 1, 0.0001, provider="akshare_fund"),
    InstrumentDraft("110011.OF", "110011", "易方达优质精选混合", "fund", "fund_cn", "CN", "CNY", 1, 0.0001, provider="akshare_fund"),
    InstrumentDraft("161725.OF", "161725", "招商中证白酒指数(LOF)", "fund", "fund_cn", "CN", "CNY", 1, 0.0001, provider="akshare_fund"),
    InstrumentDraft("519736.OF", "519736", "交银优势行业混合", "fund", "fund_cn", "CN", "CNY", 1, 0.0001, provider="akshare_fund"),
]

# Add / top-up fills: (symbol, add_qty, price, fee, days_ago, note)
# Larger notionals so fund+gold show up vs 3M house
FILLS = [
    # gold CN
    ("518880.SH", 30000, 7.80, 500, 8, "加仓黄金ETF"),
    ("159934.SZ", 25000, 5.65, 500, 9, "黄金ETF·易方达"),
    ("518800.SH", 20000, 5.40, 500, 7, "黄金ETF·国泰"),
    ("GLD", 80, 220.0, 0, 6, "加仓 GLD"),
    ("IAU", 200, 42.5, 0, 5, "加仓 IAU"),
    # funds
    ("110022.OF", 40000, 2.95, 0, 11, "加仓消费基金"),
    ("005827.OF", 35000, 1.68, 0, 10, "加仓蓝筹精选"),
    ("000001.OF", 50000, 1.15, 0, 15, "华夏成长"),
    ("110011.OF", 30000, 4.20, 0, 13, "优质精选"),
    ("161725.OF", 20000, 0.85, 0, 12, "白酒指数基金"),
    ("519736.OF", 25000, 3.55, 0, 9, "交银优势行业"),
]


def deposit(db, account, currency: str, amount: float, note: str) -> None:
    cents = money_to_cents(amount)
    when = datetime.now(timezone.utc) - timedelta(days=20)
    w = get_wallet(db, account.id, currency)
    w.balance_cents += cents
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


def buy(db, account, symbol: str, qty: float, price: float, fee: int, days_ago: int, note: str, seq: int) -> None:
    inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
    assert inst, symbol
    when = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=2)
    ccy = inst.currency.upper()
    qty_m = qty_to_micros(qty)
    px_e4 = price_to_e4(price)
    notional = notional_cents(px_e4, qty_m)
    delta = -(notional + fee)

    order = Order(
        account_id=account.id,
        client_order_id=f"fg-{account.id}-{seq:03d}-{symbol.replace('.', '').replace('-', '')}",
        symbol=symbol,
        side="buy",
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
            side="buy",
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
        need = -(w.balance_cents + delta)
        w.balance_cents += need
        db.add(
            CashFlow(
                account_id=account.id,
                type="deposit",
                currency=ccy,
                amount_cents=need,
                note=f"基金黄金补仓·{ccy}",
                occurred_at=when - timedelta(hours=2),
            )
        )
    w.balance_cents += delta
    db.add(
        CashLedger(
            account_id=account.id,
            ts=when,
            type="buy",
            currency=ccy,
            amount_cents=delta,
            ref_order_id=order.id,
            balance_after_cents=w.balance_cents,
            note=f"买入 {symbol}",
        )
    )

    pos = db.query(Position).filter(Position.account_id == account.id, Position.symbol == symbol).first()
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
        total = pos.avg_cost_e4 * pos.qty_micros + px_e4 * qty_m
        new_qty = pos.qty_micros + qty_m
        pos.qty_micros = new_qty
        pos.avg_cost_e4 = int(total / new_qty)
        pos.updated_at = when


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        account = get_account_or_404(db, ACCOUNT_ID)
        ensure_wallets(db, account.id)
        for d in EXTRA:
            _upsert_instrument(db, d)

        # marker: if 159934 already held with large qty, skip re-run
        pos = db.query(Position).filter(Position.account_id == ACCOUNT_ID, Position.symbol == "159934.SZ").first()
        if pos and pos.qty_micros >= qty_to_micros(20000):
            print("already boosted fund/gold; skip")
            for p in list_positions(db, ACCOUNT_ID):
                if p["symbol"].endswith(".OF") or "黄金" in p["name"] or p["symbol"] in ("GLD", "IAU", "518880.SH", "159934.SZ", "518800.SH"):
                    print(f"  {p['symbol']:14} qty={p['qty']}  {p['name']}")
            return

        deposit(db, account, "CNY", 1200000, "基金黄金专项入金")
        deposit(db, account, "USD", 40000, "海外黄金专项入金")

        for i, (symbol, qty, price, fee, days, note) in enumerate(FILLS, start=1):
            buy(db, account, symbol, qty, price, fee, days, note, seq=700 + i)

        for sym in [d.symbol for d in EXTRA] + ["518880.SH", "GLD", "110022.OF", "005827.OF"]:
            if not db.query(WatchlistItem).filter(WatchlistItem.symbol == sym).first():
                db.add(WatchlistItem(symbol=sym, sort_order=50))

        cny = get_wallet(db, account.id, "CNY")
        account.cash_balance_cents = cny.balance_cents
        db.commit()
        rebuild_equity_curve(db, account.id)
        s = account_summary(db, account.id)
        print(f"equity={s['total_equity']} wallets={s.get('wallets')}")
        print("fund + gold:")
        for p in list_positions(db, ACCOUNT_ID):
            sym = p["symbol"]
            if (
                sym.endswith(".OF")
                or p.get("name", "").find("黄金") >= 0
                or sym in ("GLD", "IAU", "518880.SH", "159934.SZ", "518800.SH")
            ):
                mv = p.get("market_value")
                print(f"  {sym:14} qty={p['qty']:<10} mv≈{mv}  {p['name']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
