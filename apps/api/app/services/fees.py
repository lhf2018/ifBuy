from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.core.money import d, money_to_cents
from app.models import FeeRule, Instrument


def _rate(s: str) -> Decimal:
    return d(s)


def fee_market_key(instrument: Instrument) -> str:
    """Map instrument to fee bucket."""
    if instrument.asset_class == "fund_cn" or instrument.instrument_type == "fund":
        return "FUND_CN"
    if instrument.asset_class == "crypto" or instrument.instrument_type == "crypto":
        return "CRYPTO"
    if instrument.asset_class == "commodity" or instrument.instrument_type == "future":
        return "FUT_CN"
    if instrument.asset_class == "custom" or instrument.instrument_type == "custom":
        return "CUSTOM"
    if instrument.asset_class == "equity_hk" or (instrument.market or "").upper() == "HK":
        return "HK"
    if instrument.asset_class == "gold" or instrument.theme == "gold":
        m = (instrument.market or "CN").upper()
        return "GOLD_US" if m == "US" else "GOLD_CN"
    return (instrument.market or "CN").upper()


def get_fee_rule(db: Session, market: str, instrument_type: str | None) -> FeeRule:
    q = db.query(FeeRule).filter(FeeRule.scope == "global", FeeRule.market == market)
    if instrument_type:
        rule = q.filter(FeeRule.instrument_type == instrument_type).first()
        if rule:
            return rule
    rule = q.filter(FeeRule.instrument_type.is_(None)).first()
    if rule:
        return rule
    # legacy: GOLD_* missing → fall back to CN/US etf defaults
    if market.startswith("GOLD_"):
        base = "US" if market.endswith("US") else "CN"
        return get_fee_rule(db, base, instrument_type or "etf")
    return _default_rule(market, instrument_type or "equity")


def _default_rule(market: str, instrument_type: str) -> FeeRule:
    if market == "FUND_CN":
        return FeeRule(
            market=market,
            instrument_type=instrument_type or "fund",
            buy_commission_rate="0.0015",
            buy_min_commission_cents=0,
            buy_stamp_tax_rate="0",
            buy_transfer_fee_rate="0",
            sell_commission_rate="0.005",
            sell_min_commission_cents=0,
            sell_stamp_tax_rate="0",
            sell_transfer_fee_rate="0",
            sell_sec_fee_rate="0",
        )
    if market in ("HK", "FUT_CN", "CRYPTO", "CUSTOM"):
        return FeeRule(
            market=market,
            instrument_type=instrument_type,
            buy_commission_rate="0.00025" if market == "HK" else ("0.0002" if market == "FUT_CN" else "0.001"),
            buy_min_commission_cents=0,
            buy_stamp_tax_rate="0.001" if market == "HK" else "0",
            buy_transfer_fee_rate="0",
            sell_commission_rate="0.00025" if market == "HK" else ("0.0002" if market == "FUT_CN" else "0.001"),
            sell_min_commission_cents=0,
            sell_stamp_tax_rate="0.001" if market == "HK" else "0",
            sell_transfer_fee_rate="0",
            sell_sec_fee_rate="0",
        )
    if market in ("CN", "GOLD_CN") and instrument_type == "etf":
        return FeeRule(
            market=market,
            instrument_type=instrument_type,
            buy_commission_rate="0.00025",
            buy_min_commission_cents=500,
            buy_stamp_tax_rate="0",
            buy_transfer_fee_rate="0",
            sell_commission_rate="0.00025",
            sell_min_commission_cents=500,
            sell_stamp_tax_rate="0",
            sell_transfer_fee_rate="0",
            sell_sec_fee_rate="0",
        )
    if market == "CN":
        return FeeRule(
            market=market,
            instrument_type=instrument_type,
            buy_commission_rate="0.00025",
            buy_min_commission_cents=500,
            buy_stamp_tax_rate="0",
            buy_transfer_fee_rate="0.00001",
            sell_commission_rate="0.00025",
            sell_min_commission_cents=500,
            sell_stamp_tax_rate="0.0005",
            sell_transfer_fee_rate="0.00001",
            sell_sec_fee_rate="0",
        )
    # US / GOLD_US — commission-free paper default
    return FeeRule(
        market=market,
        instrument_type=instrument_type,
        buy_commission_rate="0",
        buy_min_commission_cents=0,
        buy_stamp_tax_rate="0",
        buy_transfer_fee_rate="0",
        sell_commission_rate="0",
        sell_min_commission_cents=0,
        sell_stamp_tax_rate="0",
        sell_transfer_fee_rate="0",
        sell_sec_fee_rate="0",
    )


def calc_fee_cents(db: Session, instrument: Instrument, side: str, notional_cents: int) -> int:
    market = fee_market_key(instrument)
    rule = get_fee_rule(db, market, instrument.instrument_type)
    notional = Decimal(notional_cents) / Decimal(100)
    if side == "buy":
        commission = max(notional * _rate(rule.buy_commission_rate), Decimal(rule.buy_min_commission_cents) / 100)
        stamp = notional * _rate(rule.buy_stamp_tax_rate)
        transfer = notional * _rate(rule.buy_transfer_fee_rate)
        total = commission + stamp + transfer
    else:
        commission = max(notional * _rate(rule.sell_commission_rate), Decimal(rule.sell_min_commission_cents) / 100)
        stamp = notional * _rate(rule.sell_stamp_tax_rate)
        transfer = notional * _rate(rule.sell_transfer_fee_rate)
        sec = notional * _rate(rule.sell_sec_fee_rate)
        total = commission + stamp + transfer + sec
    return money_to_cents(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def list_fee_rules(db: Session) -> list[dict]:
    ensure_fee_rules(db)
    rows = db.query(FeeRule).filter(FeeRule.scope == "global").order_by(FeeRule.market, FeeRule.instrument_type).all()
    return [_rule_dict(r) for r in rows]


def _rule_dict(r: FeeRule) -> dict:
    label = {
        "CN": "A股",
        "US": "美股",
        "GOLD_CN": "黄金·国内",
        "GOLD_US": "黄金·美股",
        "FUND_CN": "基金",
        "HK": "港股",
        "FUT_CN": "期货商品",
        "CRYPTO": "加密货币",
        "CUSTOM": "自定义",
    }.get(r.market or "", r.market or "")
    return {
        "id": r.id,
        "market": r.market,
        "market_label": label,
        "instrument_type": r.instrument_type,
        "buy_commission_rate": float(r.buy_commission_rate),
        "buy_min_commission": r.buy_min_commission_cents / 100,
        "buy_stamp_tax_rate": float(r.buy_stamp_tax_rate),
        "buy_transfer_fee_rate": float(r.buy_transfer_fee_rate),
        "sell_commission_rate": float(r.sell_commission_rate),
        "sell_min_commission": r.sell_min_commission_cents / 100,
        "sell_stamp_tax_rate": float(r.sell_stamp_tax_rate),
        "sell_transfer_fee_rate": float(r.sell_transfer_fee_rate),
        "sell_sec_fee_rate": float(r.sell_sec_fee_rate),
    }


def ensure_fee_rules(db: Session) -> None:
    """Insert any missing default market fee rows (idempotent)."""
    specs = [
        ("CN", "equity", "0.00025", 500, "0", "0.00001", "0.00025", 500, "0.0005", "0.00001", "0"),
        ("CN", "etf", "0.00025", 500, "0", "0", "0.00025", 500, "0", "0", "0"),
        ("US", "equity", "0", 0, "0", "0", "0", 0, "0", "0", "0"),
        ("US", "etf", "0", 0, "0", "0", "0", 0, "0", "0", "0"),
        ("GOLD_CN", "etf", "0.00025", 500, "0", "0", "0.00025", 500, "0", "0", "0"),
        ("GOLD_US", "etf", "0", 0, "0", "0", "0", 0, "0", "0", "0"),
        ("FUND_CN", "fund", "0.0015", 0, "0", "0", "0.005", 0, "0", "0", "0"),
        ("HK", "equity", "0.00025", 0, "0.001", "0", "0.00025", 0, "0.001", "0", "0"),
        ("FUT_CN", "future", "0.0002", 0, "0", "0", "0.0002", 0, "0", "0", "0"),
        ("CRYPTO", "crypto", "0.001", 0, "0", "0", "0.001", 0, "0", "0", "0"),
        ("CUSTOM", "custom", "0", 0, "0", "0", "0", 0, "0", "0", "0"),
    ]
    for m, it, bc, bmin, bst, btf, sc, smin, sst, stf, ssec in specs:
        exists = (
            db.query(FeeRule)
            .filter(FeeRule.scope == "global", FeeRule.market == m, FeeRule.instrument_type == it)
            .first()
        )
        if exists:
            continue
        db.add(
            FeeRule(
                scope="global",
                market=m,
                instrument_type=it,
                buy_commission_rate=bc,
                buy_min_commission_cents=bmin,
                buy_stamp_tax_rate=bst,
                buy_transfer_fee_rate=btf,
                sell_commission_rate=sc,
                sell_min_commission_cents=smin,
                sell_stamp_tax_rate=sst,
                sell_transfer_fee_rate=stf,
                sell_sec_fee_rate=ssec,
            )
        )
    db.commit()


def seed_default_fee_rules(db: Session) -> None:
    ensure_fee_rules(db)
