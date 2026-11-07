"""Dividend / split (manual corporate actions for paper trading)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.money import cents_to_money, e4_to_price, micros_to_qty, money_to_cents
from app.models import Instrument, Position, PositionAdjustment
from app.services.accounts import _append_ledger, get_account_or_404
from app.services.market import get_instrument, validate_symbol


def apply_dividend(
    db: Session,
    account_id: int,
    symbol: str,
    *,
    cash_per_share: float,
    note: str | None = None,
) -> dict:
    """Cash dividend: credit wallet by qty * cash_per_share in instrument currency."""
    account = get_account_or_404(db, account_id)
    symbol = validate_symbol(symbol)
    get_instrument(db, symbol)
    inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
    if not inst:
        raise AppError("INSTRUMENT_NOT_FOUND", f"找不到标的 {symbol}")
    if cash_per_share <= 0:
        raise AppError("PRICE_INVALID", "每股分红金额须大于 0")

    pos = db.query(Position).filter(Position.account_id == account_id, Position.symbol == symbol).first()
    if not pos or pos.qty_micros <= 0:
        raise AppError("INSUFFICIENT_POSITION", "没有该标的持仓，无法分红入账")

    qty = float(micros_to_qty(pos.qty_micros))
    total = Decimal(str(qty)) * Decimal(str(cash_per_share))
    cents = money_to_cents(total)
    ccy = (inst.currency or "CNY").upper()
    now = datetime.now(timezone.utc)
    note_text = note or f"分红 {symbol} @ {cash_per_share}/{ccy}"

    _append_ledger(db, account, "dividend", cents, ccy, note=note_text)
    adj = PositionAdjustment(
        account_id=account_id,
        symbol=symbol,
        ts=now,
        reason="dividend",
        qty_delta_micros=0,
        cost_delta_e4=0,
        note=f"{note_text} · 共 {float(cents_to_money(cents))} {ccy}",
    )
    db.add(adj)
    db.commit()
    db.refresh(adj)
    try:
        from app.services.trading import invalidate_positions_cache

        invalidate_positions_cache(account_id)
    except Exception:
        pass
    try:
        from app.services.equity import take_snapshot

        take_snapshot(db, account_id)
    except Exception:
        pass
    return _adj_dict(adj, cash_cents=cents, currency=ccy)


def apply_split(
    db: Session,
    account_id: int,
    symbol: str,
    *,
    ratio_num: float,
    ratio_den: float = 1.0,
    note: str | None = None,
) -> dict:
    """
    Stock split / reverse split.
    ratio_num:ratio_den — e.g. 2:1 split → qty *= 2, avg_cost /= 2.
    """
    get_account_or_404(db, account_id)
    symbol = validate_symbol(symbol)
    get_instrument(db, symbol)
    if ratio_num <= 0 or ratio_den <= 0:
        raise AppError("PRICE_INVALID", "拆股比例须大于 0")

    pos = db.query(Position).filter(Position.account_id == account_id, Position.symbol == symbol).first()
    if not pos or pos.qty_micros <= 0:
        raise AppError("INSUFFICIENT_POSITION", "没有该标的持仓，无法拆股")

    factor = Decimal(str(ratio_num)) / Decimal(str(ratio_den))
    old_qty = pos.qty_micros
    old_cost = pos.avg_cost_e4
    new_qty = int((Decimal(old_qty) * factor).to_integral_value())
    if new_qty <= 0:
        raise AppError("PRICE_INVALID", "拆股后数量无效")
    # keep cost basis: avg_cost / factor
    new_cost = int((Decimal(old_cost) / factor).to_integral_value())
    if new_cost <= 0:
        new_cost = 1

    now = datetime.now(timezone.utc)
    note_text = note or f"拆股 {symbol} {ratio_num}:{ratio_den}"
    pos.qty_micros = new_qty
    pos.avg_cost_e4 = new_cost
    pos.updated_at = now
    adj = PositionAdjustment(
        account_id=account_id,
        symbol=symbol,
        ts=now,
        reason="split",
        qty_delta_micros=new_qty - old_qty,
        cost_delta_e4=new_cost - old_cost,
        note=f"{note_text} · 数量 {float(micros_to_qty(old_qty))}→{float(micros_to_qty(new_qty))} · "
        f"成本 {float(e4_to_price(old_cost))}→{float(e4_to_price(new_cost))}",
    )
    db.add(adj)
    db.commit()
    db.refresh(adj)
    try:
        from app.services.trading import invalidate_positions_cache

        invalidate_positions_cache(account_id)
    except Exception:
        pass
    try:
        from app.services.equity import take_snapshot

        take_snapshot(db, account_id)
    except Exception:
        pass
    return _adj_dict(adj)


def list_adjustments(db: Session, account_id: int, symbol: str | None = None) -> list[dict]:
    get_account_or_404(db, account_id)
    q = db.query(PositionAdjustment).filter(PositionAdjustment.account_id == account_id)
    if symbol:
        q = q.filter(PositionAdjustment.symbol == validate_symbol(symbol))
    rows = q.order_by(PositionAdjustment.ts.desc()).limit(200).all()
    return [_adj_dict(r) for r in rows]


def _adj_dict(adj: PositionAdjustment, cash_cents: int | None = None, currency: str | None = None) -> dict:
    d = {
        "id": adj.id,
        "account_id": adj.account_id,
        "symbol": adj.symbol,
        "reason": adj.reason,
        "qty_delta": float(micros_to_qty(adj.qty_delta_micros)),
        "note": adj.note,
        "ts": adj.ts.isoformat() if adj.ts else None,
    }
    if cash_cents is not None:
        d["cash"] = float(cents_to_money(cash_cents))
        d["currency"] = currency
    return d


def upsert_custom_asset(
    db: Session,
    *,
    code: str,
    name: str,
    currency: str = "CNY",
    price: float,
    note: str | None = None,
) -> dict:
    """Create/update a custom (e.g. realty) instrument with manual mark price."""
    from app.services.market import _upsert_instrument
    from app.providers.base import InstrumentDraft
    import json
    import re

    code = code.strip().upper().replace(" ", "_")
    if not re.fullmatch(r"[A-Z0-9_-]{1,24}", code):
        raise AppError("INSTRUMENT_NOT_FOUND", "自定义代码仅限字母数字下划线，最长 24")
    if price <= 0:
        raise AppError("PRICE_INVALID", "估值须大于 0")
    currency = currency.upper()
    if currency not in ("CNY", "USD", "HKD"):
        raise AppError("FX_UNSUPPORTED", "自定义资产币种仅 CNY/USD/HKD")
    symbol = f"CUST.{code}"
    meta = json.dumps({"manual_price": price, "note": note or ""}, ensure_ascii=False)
    draft = InstrumentDraft(
        symbol=symbol,
        ticker=code,
        name=name.strip() or code,
        instrument_type="custom",
        asset_class="custom",
        market="OTC",
        currency=currency,
        lot_size=1,
        tick_size=0.01,
        provider="manual",
    )
    inst = _upsert_instrument(db, draft)
    inst.meta_json = meta
    db.commit()
    db.refresh(inst)
    return {
        "symbol": inst.symbol,
        "name": inst.name,
        "currency": inst.currency,
        "price": price,
        "instrument_type": "custom",
        "asset_class": "custom",
        "market": "OTC",
        "lot_size": 1,
        "tick_size": 0.01,
        "note": note,
    }


def set_custom_price(db: Session, symbol: str, price: float, note: str | None = None) -> dict:
    import json

    symbol = validate_symbol(symbol)
    if not symbol.startswith("CUST."):
        raise AppError("INSTRUMENT_NOT_FOUND", "仅自定义资产可手填估值")
    if price <= 0:
        raise AppError("PRICE_INVALID", "估值须大于 0")
    inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
    if not inst:
        raise AppError("INSTRUMENT_NOT_FOUND", f"找不到 {symbol}", status_code=404)
    meta = {}
    if inst.meta_json:
        try:
            meta = json.loads(inst.meta_json)
        except Exception:
            meta = {}
    meta["manual_price"] = price
    if note is not None:
        meta["note"] = note
    inst.meta_json = json.dumps(meta, ensure_ascii=False)
    db.commit()
    return {"symbol": symbol, "price": price, "name": inst.name, "currency": inst.currency}
