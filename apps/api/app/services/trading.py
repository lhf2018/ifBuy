from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.money import (
    cents_to_money,
    e4_to_price,
    micros_to_qty,
    money_to_cents,
    notional_cents,
    price_to_e4,
    qty_to_micros,
)
from app.models import Instrument, Note, Order, Position, Trade
from app.services.accounts import (
    _append_ledger,
    account_to_dict,
    get_account_or_404,
    net_deposit_base_cents,
    wallet_balance_cents,
)
from app.services.fees import calc_fee_cents
from app.services.market import get_instrument, get_quote, validate_symbol


def place_order(
    db: Session,
    account_id: int,
    *,
    client_order_id: str,
    symbol: str,
    side: str,
    qty: float,
    manual_price: float | None = None,
    expected_price: float | None = None,
    confirm_price_moved: bool = False,
    note: str | None = None,
    emotion_tag: str | None = None,
) -> dict:
    symbol = validate_symbol(symbol)
    try:
        existing = (
            db.query(Order)
            .filter(Order.account_id == account_id, Order.client_order_id == client_order_id)
            .first()
        )
        if existing:
            return _order_receipt(existing)

        account = get_account_or_404(db, account_id)
        if account.status != "active":
            raise AppError("ACCOUNT_NOT_FOUND", "该账本已归档，不能再交易。")

        inst_dict = get_instrument(db, symbol)
        instrument = db.query(Instrument).filter(Instrument.symbol == symbol).first()
        if not instrument:
            raise AppError("INSTRUMENT_NOT_FOUND", f"找不到标的 {symbol}")

        trade_ccy = instrument.currency.upper()

        qty_micros = qty_to_micros(qty)
        lot = instrument.lot_size or 1
        pos = (
            db.query(Position)
            .filter(Position.account_id == account_id, Position.symbol == symbol)
            .first()
        )
        selling_all = False
        if side == "sell" and pos and pos.qty_micros == qty_micros:
            selling_all = True
        if side == "buy" or not selling_all:
            if instrument.market == "CN":
                if qty_micros % qty_to_micros(lot) != 0:
                    raise AppError("LOT_SIZE_VIOLATION", f"A 股买入数量需为 {lot} 股的整数倍。")

        price_source = "api"
        if manual_price is not None:
            price_e4 = price_to_e4(manual_price)
            if price_e4 <= 0:
                raise AppError("PRICE_INVALID", "手填价格必须大于 0。")
            tick = instrument.tick_size_e4 or 100
            if price_e4 % tick != 0:
                raise AppError("PRICE_INVALID", f"价格需符合最小变动单位 {tick/10000}。")
            try:
                api_q = get_quote(symbol, allow_stale=True)
                if api_q.price and manual_price > api_q.price * 10:
                    raise AppError("PRICE_INVALID", "手填价格偏离市价过大，请检查。")
            except AppError:
                pass
            price_source = "manual"
        else:
            q = get_quote(symbol, allow_stale=True)
            price_e4 = price_to_e4(q.price)
            price_source = "api"

        fill_price = float(e4_to_price(price_e4))
        if expected_price and not confirm_price_moved and not manual_price:
            drift = abs(fill_price - expected_price) / expected_price
            limit = get_settings().price_drift_bps / 10000
            if drift > limit:
                raise AppError(
                    "PRICE_MOVED",
                    f"价格已变动，当前 {fill_price}，与预期偏差 {drift*100:.2f}%，是否继续？",
                    extra={"current_price": fill_price, "expected_price": expected_price, "drift": drift},
                )

        notional = notional_cents(price_e4, qty_micros)
        fee = calc_fee_cents(db, instrument, side, notional)

        now = datetime.now(timezone.utc)
        if side == "buy":
            need = notional + fee
            avail = wallet_balance_cents(db, account_id, trade_ccy)
            if avail < need:
                raise AppError(
                    "INSUFFICIENT_CASH",
                    f"{trade_ccy} 现金不够。大约需要 {float(cents_to_money(need))}，还剩 {float(cents_to_money(avail))}。"
                    f"{' 可先在首页换汇。' if trade_ccy != account.currency else ''}",
                )
            if pos:
                old_qty = micros_to_qty(pos.qty_micros)
                new_qty = old_qty + Decimal(str(qty))
                old_basis = e4_to_price(pos.avg_cost_e4) * old_qty
                new_basis = old_basis + cents_to_money(notional + fee)
                new_avg = new_basis / new_qty
                pos.qty_micros += qty_micros
                pos.avg_cost_e4 = price_to_e4(new_avg)
                pos.updated_at = now
            else:
                unit = cents_to_money(notional + fee) / Decimal(str(qty))
                pos = Position(
                    account_id=account_id,
                    symbol=symbol,
                    qty_micros=qty_micros,
                    avg_cost_e4=price_to_e4(unit),
                    opened_at=now,
                    updated_at=now,
                )
                db.add(pos)

            order = Order(
                account_id=account_id,
                client_order_id=client_order_id,
                symbol=symbol,
                side="buy",
                qty_micros=qty_micros,
                status="filled",
                fee_cents=fee,
                expected_price_e4=price_to_e4(expected_price) if expected_price else None,
                fill_price_e4=price_e4,
                price_source=price_source,
                client_note=note,
                emotion_tag=emotion_tag,
                created_at=now,
                filled_at=now,
            )
            db.add(order)
            db.flush()
            db.add(
                Trade(
                    order_id=order.id,
                    account_id=account_id,
                    symbol=symbol,
                    side="buy",
                    price_e4=price_e4,
                    qty_micros=qty_micros,
                    fee_cents=fee,
                    traded_at=now,
                    price_source=price_source,
                )
            )
            _append_ledger(
                db, account, "buy", -(notional + fee), trade_ccy, note=f"买入 {symbol}", ref_order_id=order.id
            )
        else:
            if not pos or pos.qty_micros < qty_micros:
                raise AppError("INSUFFICIENT_POSITION", "可卖数量不够。")
            proceeds = notional - fee
            if proceeds < 0:
                raise AppError("PRICE_INVALID", "费用超过成交额，请检查数量。")
            pos.qty_micros -= qty_micros
            pos.updated_at = now
            if pos.qty_micros == 0:
                db.delete(pos)

            order = Order(
                account_id=account_id,
                client_order_id=client_order_id,
                symbol=symbol,
                side="sell",
                qty_micros=qty_micros,
                status="filled",
                fee_cents=fee,
                expected_price_e4=price_to_e4(expected_price) if expected_price else None,
                fill_price_e4=price_e4,
                price_source=price_source,
                client_note=note,
                emotion_tag=emotion_tag,
                created_at=now,
                filled_at=now,
            )
            db.add(order)
            db.flush()
            db.add(
                Trade(
                    order_id=order.id,
                    account_id=account_id,
                    symbol=symbol,
                    side="sell",
                    price_e4=price_e4,
                    qty_micros=qty_micros,
                    fee_cents=fee,
                    traded_at=now,
                    price_source=price_source,
                )
            )
            _append_ledger(
                db, account, "sell", proceeds, trade_ccy, note=f"卖出 {symbol}", ref_order_id=order.id
            )

        if note:
            db.add(
                Note(
                    order_id=order.id,
                    account_id=account_id,
                    symbol=symbol,
                    kind="entry_reason",
                    body=note,
                )
            )

        db.commit()
        db.refresh(order)
        try:
            from app.services.equity import take_snapshot

            take_snapshot(db, account_id)
        except Exception:
            pass
        return _order_receipt(order, instrument_name=inst_dict.get("name"))
    except AppError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def _order_receipt(order: Order, instrument_name: str | None = None) -> dict:
    return {
        "id": order.id,
        "client_order_id": order.client_order_id,
        "account_id": order.account_id,
        "symbol": order.symbol,
        "name": instrument_name,
        "side": order.side,
        "qty": float(micros_to_qty(order.qty_micros)),
        "fill_price": float(e4_to_price(order.fill_price_e4)),
        "fee": float(cents_to_money(order.fee_cents)),
        "price_source": order.price_source,
        "status": order.status,
        "note": order.client_note,
        "emotion_tag": order.emotion_tag,
        "filled_at": order.filled_at.isoformat() if order.filled_at else None,
    }


def list_orders(db: Session, account_id: int) -> list[dict]:
    get_account_or_404(db, account_id)
    rows = db.query(Order).filter(Order.account_id == account_id).order_by(Order.filled_at.desc()).all()
    return [_order_receipt(o) for o in rows]


def list_positions(db: Session, account_id: int) -> list[dict]:
    get_account_or_404(db, account_id)
    rows = db.query(Position).filter(Position.account_id == account_id).all()
    out = []
    for p in rows:
        inst = db.query(Instrument).filter(Instrument.symbol == p.symbol).first()
        qty = float(micros_to_qty(p.qty_micros))
        avg = float(e4_to_price(p.avg_cost_e4))
        price = None
        stale = True
        try:
            q = get_quote(p.symbol, allow_stale=True)
            price = q.price
            stale = q.stale
        except AppError:
            price = None
        market_value = None
        unrealized = None
        unrealized_pct = None
        if price is not None:
            market_value = price * qty
            unrealized = (price - avg) * qty
            unrealized_pct = ((price - avg) / avg * 100) if avg else None
        out.append(
            {
                "symbol": p.symbol,
                "name": inst.name if inst else p.symbol,
                "qty": qty,
                "avg_cost": avg,
                "price": price,
                "stale": stale if price is not None else True,
                "market_value": market_value,
                "unrealized_pnl": unrealized,
                "unrealized_pct": unrealized_pct,
                "currency": inst.currency if inst else None,
            }
        )
    return out


def account_summary(db: Session, account_id: int) -> dict:
    account = get_account_or_404(db, account_id)
    positions = list_positions(db, account_id)
    mv_by: dict[str, int] = {}
    for p in positions:
        if p["market_value"] is not None and p.get("currency"):
            ccy = p["currency"].upper()
            mv_by[ccy] = mv_by.get(ccy, 0) + money_to_cents(p["market_value"])
    data = account_to_dict(account, db=db, market_value_by_ccy=mv_by)
    net = net_deposit_base_cents(db, account)
    equity_cents = money_to_cents(data["total_equity"])
    pnl_cents = equity_cents - net
    data["net_deposit"] = float(cents_to_money(net))
    data["total_pnl"] = float(cents_to_money(pnl_cents))
    if net > 0:
        data["return_pct"] = float(
            (Decimal(pnl_cents) / Decimal(net) * 100).quantize(Decimal("0.01"))
        )
    else:
        data["return_pct"] = None
    data["positions_count"] = len(positions)
    return data
