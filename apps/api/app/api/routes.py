from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.common import (
    AccountCreate,
    AccountUpdate,
    CashFlowCreate,
    CustomAssetCreate,
    CustomPriceUpdate,
    DividendCreate,
    FxExchangeCreate,
    OrderCreate,
    SplitCreate,
    WatchlistCreate,
)
from app.services import accounts as account_svc
from app.services import corporate_actions as corp_svc
from app.services import market as market_svc
from app.services import risk as risk_svc
from app.services import trading as trading_svc
from app.services.fx import get_fx_rate
from app.services import fees as fee_svc
from app.services.equity import list_equity_curve, rebuild_equity_curve
from app.services.export_import import export_all, import_payload
from app.models import WatchlistItem
from app.core.errors import AppError

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health():
    return {"ok": True, "service": "ifbuy-api"}


@router.get("/fee-rules")
def api_fee_rules(db: Session = Depends(get_db)):
    return fee_svc.list_fee_rules(db)


# ---- accounts ----
@router.get("/accounts")
def api_list_accounts(db: Session = Depends(get_db)):
    return [account_svc.account_to_dict(a, db=db) for a in account_svc.list_accounts(db)]


@router.post("/accounts")
def api_create_account(body: AccountCreate, db: Session = Depends(get_db)):
    a = account_svc.create_account(
        db,
        body.name,
        base_currency=body.base_currency or body.currency,
        initial_cash_cny=body.initial_cash_cny,
        initial_cash_usd=body.initial_cash_usd,
        currency=body.currency if body.initial_cash is not None else None,
        initial_cash=body.initial_cash,
    )
    return account_svc.account_to_dict(a, db=db)


@router.get("/accounts/{account_id}")
def api_get_account(account_id: int, db: Session = Depends(get_db)):
    return trading_svc.account_summary(db, account_id)


@router.get("/accounts/{account_id}/summary")
def api_summary(account_id: int, db: Session = Depends(get_db)):
    return trading_svc.account_summary(db, account_id)


@router.patch("/accounts/{account_id}")
def api_patch_account(account_id: int, body: AccountUpdate, db: Session = Depends(get_db)):
    a = account_svc.update_account(db, account_id, body.name, body.status, body.note)
    return account_svc.account_to_dict(a, db=db)


@router.get("/accounts/{account_id}/cash-flows")
def api_list_cash_flows(account_id: int, db: Session = Depends(get_db)):
    return account_svc.list_cash_flows(db, account_id)


@router.post("/accounts/{account_id}/cash-flows")
def api_cash_flow(account_id: int, body: CashFlowCreate, db: Session = Depends(get_db)):
    a = account_svc.add_cash_flow(db, account_id, body.type, body.amount, body.note, currency=body.currency)
    return account_svc.account_to_dict(a, db=db)


@router.get("/accounts/{account_id}/equity-curve")
def api_equity_curve(account_id: int, rebuild: bool = False, db: Session = Depends(get_db)):
    if rebuild:
        return rebuild_equity_curve(db, account_id)
    return list_equity_curve(db, account_id)


@router.post("/accounts/{account_id}/fx")
def api_fx_exchange(account_id: int, body: FxExchangeCreate, db: Session = Depends(get_db)):
    return account_svc.exchange(
        db,
        account_id,
        from_currency=body.from_currency,
        to_currency=body.to_currency,
        from_amount=body.from_amount,
        rate=body.rate,
        note=body.note,
    )


@router.get("/fx/rate")
def api_fx_rate(from_currency: str = "USD", to_currency: str = "CNY"):
    rate, source = get_fx_rate(from_currency, to_currency)
    return {"from_currency": from_currency.upper(), "to_currency": to_currency.upper(), "rate": rate, "source": source}


@router.post("/accounts/{account_id}/orders")
def api_place_order(account_id: int, body: OrderCreate, db: Session = Depends(get_db)):
    return trading_svc.place_order(
        db,
        account_id,
        client_order_id=body.client_order_id,
        symbol=body.symbol,
        side=body.side,
        qty=body.qty,
        manual_price=body.manual_price,
        expected_price=body.expected_price,
        confirm_price_moved=body.confirm_price_moved,
        note=body.note,
        emotion_tag=body.emotion_tag,
    )


@router.get("/accounts/{account_id}/orders")
def api_list_orders(account_id: int, db: Session = Depends(get_db)):
    return trading_svc.list_orders(db, account_id)


@router.get("/accounts/{account_id}/positions")
def api_list_positions(account_id: int, db: Session = Depends(get_db)):
    return trading_svc.list_positions(db, account_id)


@router.get("/accounts/{account_id}/risk")
def api_risk(account_id: int, db: Session = Depends(get_db)):
    return risk_svc.risk_report(db, account_id)


@router.get("/accounts/{account_id}/corporate-actions")
def api_list_corp(account_id: int, symbol: str | None = None, db: Session = Depends(get_db)):
    return corp_svc.list_adjustments(db, account_id, symbol)


@router.post("/accounts/{account_id}/dividends")
def api_dividend(account_id: int, body: DividendCreate, db: Session = Depends(get_db)):
    return corp_svc.apply_dividend(
        db, account_id, body.symbol, cash_per_share=body.cash_per_share, note=body.note
    )


@router.post("/accounts/{account_id}/splits")
def api_split(account_id: int, body: SplitCreate, db: Session = Depends(get_db)):
    return corp_svc.apply_split(
        db,
        account_id,
        body.symbol,
        ratio_num=body.ratio_num,
        ratio_den=body.ratio_den,
        note=body.note,
    )


@router.post("/instruments/custom")
def api_create_custom(body: CustomAssetCreate, db: Session = Depends(get_db)):
    return corp_svc.upsert_custom_asset(
        db,
        code=body.code,
        name=body.name,
        currency=body.currency,
        price=body.price,
        note=body.note,
    )


@router.post("/instruments/{symbol}/valuation")
def api_custom_valuation(symbol: str, body: CustomPriceUpdate, db: Session = Depends(get_db)):
    return corp_svc.set_custom_price(db, symbol, body.price, note=body.note)


# ---- market ----
@router.get("/instruments/search")
def api_search(
    q: str = "",
    asset_class: str | None = None,
    theme: str | None = None,
    db: Session = Depends(get_db),
):
    return market_svc.search_instruments(db, q, asset_class=asset_class, theme=theme)


@router.get("/instruments/{symbol}")
def api_instrument(symbol: str, db: Session = Depends(get_db)):
    return market_svc.get_instrument(db, symbol)


@router.get("/quotes")
def api_quotes(symbols: str = Query(..., description="comma-separated")):
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    return market_svc.get_quotes(syms)


@router.get("/bars/{symbol}")
def api_bars(
    symbol: str,
    interval: str = "1d",
    adjust: str = "none",
    limit: int = 250,
    db: Session = Depends(get_db),
):
    return market_svc.get_bars(db, symbol, interval, adjust, min(limit, 1000))


# ---- watchlist ----
@router.get("/watchlist")
def api_watchlist(db: Session = Depends(get_db)):
    rows = db.query(WatchlistItem).order_by(WatchlistItem.sort_order, WatchlistItem.id).all()
    out = []
    for r in rows:
        try:
            inst = market_svc.get_instrument(db, r.symbol)
        except AppError:
            inst = {"symbol": r.symbol, "name": r.symbol}
        out.append(
            {
                "id": r.id,
                "symbol": r.symbol,
                **{k: inst.get(k) for k in ("name", "currency", "asset_class", "market", "theme")},
            }
        )
    return out


@router.post("/watchlist")
def api_add_watch(body: WatchlistCreate, db: Session = Depends(get_db)):
    symbol = market_svc.validate_symbol(body.symbol)
    market_svc.get_instrument(db, symbol)
    exists = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
    if exists:
        return {"id": exists.id, "symbol": symbol}
    item = WatchlistItem(symbol=symbol)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "symbol": symbol}


@router.delete("/watchlist/{item_id}")
def api_del_watch(item_id: int, db: Session = Depends(get_db)):
    item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if not item:
        raise AppError("INSTRUMENT_NOT_FOUND", "关注项不存在", status_code=404)
    db.delete(item)
    db.commit()
    return {"ok": True}


# ---- export / import ----
@router.get("/export")
def api_export(db: Session = Depends(get_db)):
    return export_all(db)


@router.post("/import")
def api_import(payload: dict, db: Session = Depends(get_db)):
    return import_payload(db, payload)
