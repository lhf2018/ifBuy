"""Force-seed demo buys + history for A-share / US / gold."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.core.money import cents_to_money, money_to_cents, notional_cents, price_to_e4, qty_to_micros
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
from app.services.accounts import ensure_wallets, get_wallet


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        acc = db.query(Account).order_by(Account.id.asc()).first()
        if not acc:
            raise SystemExit("no account")

        db.query(Trade).filter(Trade.account_id == acc.id).delete(synchronize_session=False)
        db.query(Note).filter(Note.account_id == acc.id).delete(synchronize_session=False)
        db.query(CashLedger).filter(
            CashLedger.account_id == acc.id,
            CashLedger.type.in_(["buy", "sell", "fee"]),
        ).delete(synchronize_session=False)
        db.query(Order).filter(Order.account_id == acc.id).delete(synchronize_session=False)
        db.query(Position).filter(Position.account_id == acc.id).delete(synchronize_session=False)

        ensure_wallets(db, acc.id)
        open_cny = money_to_cents(800000)
        open_usd = money_to_cents(50000)
        for w in db.query(WalletBalance).filter(WalletBalance.account_id == acc.id):
            if w.currency == "CNY":
                w.balance_cents = open_cny
            elif w.currency == "USD":
                w.balance_cents = open_usd
        # cash_flows must match opening cash or total_pnl will be fake
        db.query(CashFlow).filter(
            CashFlow.account_id == acc.id,
            CashFlow.type.in_(["initial", "deposit", "withdraw"]),
        ).delete(synchronize_session=False)
        db.add(
            CashFlow(
                account_id=acc.id,
                type="initial",
                currency="CNY",
                amount_cents=open_cny,
                note="开户本金·人民币",
            )
        )
        db.add(
            CashFlow(
                account_id=acc.id,
                type="initial",
                currency="USD",
                amount_cents=open_usd,
                note="开户本金·美元",
            )
        )
        acc.initial_cash_cents = open_cny
        db.flush()

        instruments = [
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
                symbol="300750.SZ",
                ticker="300750",
                name="宁德时代",
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
                symbol="TSLA",
                ticker="TSLA",
                name="Tesla",
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
                symbol="NVDA",
                ticker="NVDA",
                name="NVIDIA",
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

        for d in instruments:
            inst = db.query(Instrument).filter(Instrument.symbol == d["symbol"]).first()
            if inst:
                for k, v in d.items():
                    setattr(inst, k, v)
            else:
                db.add(Instrument(**d))
        db.flush()

        fills = [
            ("600519.SH", "buy", 100, 1680.00, 500, 45, "建仓茅台"),
            ("600519.SH", "buy", 100, 1725.50, 500, 30, "加仓"),
            ("000001.SZ", "buy", 1000, 11.28, 500, 40, ""),
            ("300750.SZ", "buy", 200, 198.60, 500, 25, ""),
            ("300750.SZ", "sell", 100, 215.40, 500, 10, "减半"),
            ("518880.SH", "buy", 2000, 5.42, 500, 35, "国内黄金"),
            ("AAPL", "buy", 20, 178.25, 0, 50, "美股建仓"),
            ("AAPL", "buy", 10, 185.10, 0, 20, ""),
            ("TSLA", "buy", 15, 242.80, 0, 28, ""),
            ("NVDA", "buy", 8, 118.50, 0, 18, ""),
            ("GLD", "buy", 25, 215.60, 0, 33, "美黄金ETF"),
        ]

        pos: dict[str, dict[str, Decimal]] = {}
        now = datetime.now(timezone.utc)
        last_px: dict[str, float] = {}

        for i, (symbol, side, qty, price, fee, days_ago, note) in enumerate(fills, start=1):
            last_px[symbol] = price
            inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
            assert inst is not None
            ccy = inst.currency
            qty_m = qty_to_micros(qty)
            px_e4 = price_to_e4(price)
            notional = notional_cents(px_e4, qty_m)
            ts = now - timedelta(days=days_ago, hours=(i % 5))

            if symbol not in pos:
                pos[symbol] = {"qty": Decimal("0"), "cost": Decimal("0")}
            p = pos[symbol]

            if side == "buy":
                cash_delta = -(notional + fee)
                p["cost"] += cents_to_money(notional + fee)
                p["qty"] += Decimal(str(qty))
            else:
                cash_delta = notional - fee
                old_qty = p["qty"]
                if old_qty <= 0:
                    raise RuntimeError(f"sell without pos: {symbol}")
                unit = p["cost"] / old_qty
                p["qty"] -= Decimal(str(qty))
                p["cost"] -= unit * Decimal(str(qty))

            order = Order(
                account_id=acc.id,
                client_order_id=f"seed-{i:03d}-{symbol.replace('.', '')}",
                symbol=symbol,
                side=side,
                qty_micros=qty_m,
                status="filled",
                fee_cents=fee,
                fill_price_e4=px_e4,
                price_source="manual",
                client_note=note or None,
                created_at=ts,
                filled_at=ts,
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
                    traded_at=ts,
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
                        created_at=ts,
                        updated_at=ts,
                    )
                )

            w = get_wallet(db, acc.id, ccy)
            w.balance_cents += cash_delta
            db.add(
                CashLedger(
                    account_id=acc.id,
                    ts=ts,
                    type=side,
                    currency=ccy,
                    amount_cents=cash_delta,
                    ref_order_id=order.id,
                    balance_after_cents=w.balance_cents,
                    note=f"{'买入' if side == 'buy' else '卖出'} {symbol}",
                )
            )

        for symbol, p in pos.items():
            if p["qty"] <= 0:
                continue
            avg = p["cost"] / p["qty"]
            db.add(
                Position(
                    account_id=acc.id,
                    symbol=symbol,
                    qty_micros=qty_to_micros(float(p["qty"])),
                    avg_cost_e4=price_to_e4(avg),
                    opened_at=now - timedelta(days=50),
                    updated_at=now,
                )
            )

        symbols = [d["symbol"] for d in instruments]
        db.query(Bar).filter(Bar.symbol.in_(symbols)).delete(synchronize_session=False)
        random.seed(42)
        for d in instruments:
            sym = d["symbol"]
            base = float(last_px.get(sym, 100))
            px = base
            closes: list[float] = []
            for _ in range(120):
                drift = random.uniform(-0.018, 0.02)
                px = max(px * (1 + drift), 0.5)
                closes.append(px)
            closes.reverse()
            closes[-1] = base
            for i, close in enumerate(closes):
                day = (now - timedelta(days=120 - i)).date().isoformat()
                o = close * random.uniform(0.992, 1.008)
                h = max(o, close) * random.uniform(1.0, 1.015)
                l = min(o, close) * random.uniform(0.985, 1.0)
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
                        volume=int(random.uniform(1e6, 8e6)),
                        finalized=True,
                    )
                )

        db.query(WatchlistItem).delete(synchronize_session=False)
        for i, d in enumerate(instruments):
            db.add(WatchlistItem(symbol=d["symbol"], sort_order=i))

        cny = get_wallet(db, acc.id, "CNY")
        usd = get_wallet(db, acc.id, "USD")
        acc.cash_balance_cents = cny.balance_cents
        db.commit()

        print(f"account={acc.id} {acc.name}")
        print(f"CNY={float(cents_to_money(cny.balance_cents))} USD={float(cents_to_money(usd.balance_cents))}")
        print("positions:")
        for p in db.query(Position).filter_by(account_id=acc.id):
            print(f"  {p.symbol} qty={p.qty_micros/1e6:.4g} avg={p.avg_cost_e4/1e4:.4f}")
        print(f"orders={db.query(Order).filter_by(account_id=acc.id).count()}")
        print(f"bars={db.query(Bar).filter(Bar.symbol.in_(symbols)).count()}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
