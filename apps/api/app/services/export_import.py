from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.money import cents_to_money, e4_to_price, micros_to_qty
from app.models import Account, CashFlow, Note, Order, Position, Trade, WatchlistItem
from app.services.accounts import create_account

SCHEMA_VERSION = 1


def export_all(db: Session) -> dict:
    accounts = db.query(Account).all()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "accounts": [],
        "watchlist": [{"symbol": w.symbol} for w in db.query(WatchlistItem).all()],
    }
    for a in accounts:
        orders = db.query(Order).filter(Order.account_id == a.id).all()
        trades = db.query(Trade).filter(Trade.account_id == a.id).all()
        positions = db.query(Position).filter(Position.account_id == a.id).all()
        flows = db.query(CashFlow).filter(CashFlow.account_id == a.id).all()
        notes = db.query(Note).filter(Note.account_id == a.id).all()
        payload["accounts"].append(
            {
                "name": a.name,
                "currency": a.currency,
                "initial_cash": float(cents_to_money(a.initial_cash_cents)),
                "cash_balance": float(cents_to_money(a.cash_balance_cents)),
                "status": a.status,
                "cash_flows": [
                    {"type": f.type, "amount": float(cents_to_money(f.amount_cents)), "note": f.note} for f in flows
                ],
                "orders": [
                    {
                        "client_order_id": o.client_order_id,
                        "symbol": o.symbol,
                        "side": o.side,
                        "qty": float(micros_to_qty(o.qty_micros)),
                        "fill_price": float(e4_to_price(o.fill_price_e4)),
                        "fee": float(cents_to_money(o.fee_cents)),
                        "price_source": o.price_source,
                        "note": o.client_note,
                        "emotion_tag": o.emotion_tag,
                        "filled_at": o.filled_at.isoformat() if o.filled_at else None,
                    }
                    for o in orders
                ],
                "trades": [
                    {
                        "symbol": t.symbol,
                        "side": t.side,
                        "qty": float(micros_to_qty(t.qty_micros)),
                        "price": float(e4_to_price(t.price_e4)),
                        "fee": float(cents_to_money(t.fee_cents)),
                    }
                    for t in trades
                ],
                "positions": [
                    {
                        "symbol": p.symbol,
                        "qty": float(micros_to_qty(p.qty_micros)),
                        "avg_cost": float(e4_to_price(p.avg_cost_e4)),
                    }
                    for p in positions
                ],
                "notes": [{"kind": n.kind, "body": n.body, "symbol": n.symbol} for n in notes],
            }
        )
    return payload


def import_payload(db: Session, payload: dict) -> dict:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise AppError("IMPORT_INVALID", "导入文件格式或版本不对。")
    created = []
    for acc in payload.get("accounts", []):
        # MVP: create as new account with initial cash only; full history restore later
        name = f"{acc.get('name', '导入账本')} (导入)"
        currency = acc.get("currency", "CNY")
        initial = float(acc.get("initial_cash") or acc.get("cash_balance") or 100000)
        a = create_account(db, name, currency, initial)
        created.append(a.id)
    for w in payload.get("watchlist", []):
        sym = w.get("symbol")
        if not sym:
            continue
        if not db.query(WatchlistItem).filter(WatchlistItem.symbol == sym).first():
            db.add(WatchlistItem(symbol=sym))
    db.commit()
    return {"ok": True, "created_account_ids": created}
