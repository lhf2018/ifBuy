from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.money import cents_to_money, e4_to_price, micros_to_qty, money_to_cents
from app.models import CashFlow, EquitySnapshot, Instrument, Order
from app.services.accounts import account_to_dict, convert_to_base_cents, get_account_or_404


def _live_equity_parts(db: Session, account_id: int) -> tuple[int, int, int]:
    from app.services.trading import list_positions

    account = get_account_or_404(db, account_id)
    positions = list_positions(db, account_id)
    mv_by: dict[str, int] = {}
    for p in positions:
        if p["market_value"] is not None and p.get("currency"):
            ccy = str(p["currency"]).upper()
            mv_by[ccy] = mv_by.get(ccy, 0) + money_to_cents(p["market_value"])
    data = account_to_dict(account, db=db, market_value_by_ccy=mv_by)
    return (
        money_to_cents(data["total_equity"]),
        money_to_cents(data["cash_balance"]),
        money_to_cents(data["market_value"] or 0),
    )


def take_snapshot(
    db: Session,
    account_id: int,
    *,
    snapshot_date: str | None = None,
    equity_cents: int | None = None,
    cash_cents: int | None = None,
    mv_cents: int | None = None,
) -> EquitySnapshot:
    get_account_or_404(db, account_id)
    day = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    if equity_cents is None or cash_cents is None or mv_cents is None:
        equity_cents, cash_cents, mv_cents = _live_equity_parts(db, account_id)
    row = (
        db.query(EquitySnapshot)
        .filter(EquitySnapshot.account_id == account_id, EquitySnapshot.snapshot_date == day)
        .first()
    )
    if row:
        row.total_equity_cents = equity_cents
        row.cash_cents = cash_cents
        row.market_value_cents = mv_cents
        row.valuation_basis = "api"
    else:
        row = EquitySnapshot(
            account_id=account_id,
            snapshot_date=day,
            total_equity_cents=equity_cents,
            cash_cents=cash_cents,
            market_value_cents=mv_cents,
            valuation_basis="api",
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def rebuild_equity_curve(db: Session, account_id: int) -> list[dict]:
    """Replay cash flows + fills to build daily equity points; mark today with live quotes."""
    account = get_account_or_404(db, account_id)
    base = account.currency.upper()

    cash: dict[str, int] = {"CNY": 0, "USD": 0}
    holdings: dict[str, dict] = {}
    points: dict[str, tuple[int, int, int]] = {}

    def mark() -> tuple[int, int, int]:
        cash_base = sum(convert_to_base_cents(cents, ccy, base) for ccy, cents in cash.items())
        mv_base = 0
        for h in holdings.values():
            if h["qty_micros"] <= 0:
                continue
            qty = float(micros_to_qty(h["qty_micros"]))
            px = float(e4_to_price(h["last_px_e4"]))
            mv_base += convert_to_base_cents(money_to_cents(px * qty), h["currency"], base)
        return cash_base + mv_base, cash_base, mv_base

    # Apply opening capital first so historical fills never precede 本金
    open_day = None
    for f in db.query(CashFlow).filter(CashFlow.account_id == account_id, CashFlow.type == "initial").all():
        ccy = (f.currency or base).upper()
        cash[ccy] = cash.get(ccy, 0) + int(f.amount_cents)
        ts = f.occurred_at or account.created_at or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        # use account created_at if available so curve starts at open
        if account.created_at:
            ts0 = account.created_at
            if ts0.tzinfo is None:
                ts0 = ts0.replace(tzinfo=timezone.utc)
            open_day = ts0.date().isoformat()
        else:
            open_day = ts.date().isoformat()
    if open_day:
        points[open_day] = mark()

    events: list[tuple[datetime, int, str, object]] = []
    for f in db.query(CashFlow).filter(CashFlow.account_id == account_id).all():
        if f.type in ("buy", "sell", "initial"):
            continue
        ts = f.occurred_at or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        events.append((ts, f.id or 0, "flow", f))
    for o in (
        db.query(Order)
        .filter(Order.account_id == account_id, Order.status == "filled")
        .all()
    ):
        ts = o.filled_at or o.created_at or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        events.append((ts, o.id or 0, "order", o))
    events.sort(key=lambda x: (x[0], 0 if x[2] == "flow" else 1, x[1]))

    for ts, _id, kind, obj in events:
        if kind == "flow":
            f = obj
            ccy = (f.currency or base).upper()
            if f.type in ("deposit", "fx_in"):
                cash[ccy] = cash.get(ccy, 0) + int(f.amount_cents)
            elif f.type in ("withdraw", "fx_out"):
                cash[ccy] = cash.get(ccy, 0) - int(f.amount_cents)
        else:
            o = obj
            inst = db.query(Instrument).filter(Instrument.symbol == o.symbol).first()
            ccy = (inst.currency if inst else base).upper()
            notional = int(
                (Decimal(o.fill_price_e4) * Decimal(o.qty_micros) / Decimal(100_000_000)).to_integral_value()
            )
            fee = int(o.fee_cents or 0)
            if o.side == "buy":
                cash[ccy] = cash.get(ccy, 0) - (notional + fee)
                h = holdings.get(o.symbol) or {
                    "qty_micros": 0,
                    "last_px_e4": o.fill_price_e4,
                    "currency": ccy,
                }
                h["qty_micros"] += o.qty_micros
                h["last_px_e4"] = o.fill_price_e4
                h["currency"] = ccy
                holdings[o.symbol] = h
            else:
                cash[ccy] = cash.get(ccy, 0) + (notional - fee)
                h = holdings.get(o.symbol)
                if h:
                    h["qty_micros"] -= o.qty_micros
                    h["last_px_e4"] = o.fill_price_e4
                    if h["qty_micros"] <= 0:
                        holdings.pop(o.symbol, None)

        points[ts.date().isoformat()] = mark()

    today = datetime.now(timezone.utc).date().isoformat()
    points[today] = _live_equity_parts(db, account_id)

    db.query(EquitySnapshot).filter(EquitySnapshot.account_id == account_id).delete(synchronize_session=False)
    out_rows: list[EquitySnapshot] = []
    for day, (eq, cash_b, mv_b) in sorted(points.items()):
        row = EquitySnapshot(
            account_id=account_id,
            snapshot_date=day,
            total_equity_cents=eq,
            cash_cents=cash_b,
            market_value_cents=mv_b,
            valuation_basis="api" if day == today else "replay",
        )
        db.add(row)
        out_rows.append(row)
    db.commit()
    return [_snap_dict(r, base) for r in out_rows]


def list_equity_curve(db: Session, account_id: int) -> list[dict]:
    account = get_account_or_404(db, account_id)
    rows = (
        db.query(EquitySnapshot)
        .filter(EquitySnapshot.account_id == account_id)
        .order_by(EquitySnapshot.snapshot_date.asc())
        .all()
    )
    if len(rows) < 2:
        return rebuild_equity_curve(db, account_id)
    take_snapshot(db, account_id)
    rows = (
        db.query(EquitySnapshot)
        .filter(EquitySnapshot.account_id == account_id)
        .order_by(EquitySnapshot.snapshot_date.asc())
        .all()
    )
    return [_snap_dict(r, account.currency) for r in rows]


def _snap_dict(row: EquitySnapshot, currency: str) -> dict:
    return {
        "date": row.snapshot_date,
        "total_equity": float(cents_to_money(row.total_equity_cents)),
        "cash": float(cents_to_money(row.cash_cents)),
        "market_value": float(cents_to_money(row.market_value_cents)),
        "currency": currency,
    }
