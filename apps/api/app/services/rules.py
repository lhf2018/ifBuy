"""Trading rules closer to reality: T+1, 港股通 daily quota, calendars."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.money import cents_to_money, money_to_cents
from app.models import Account, HkConnectDaily, Instrument, Order
from app.services.fx import get_fx_rate

SH_TZ = ZoneInfo("Asia/Shanghai")

DEFAULT_SETTINGS = {
    "alert_max_weight_pct": 40.0,
    "alert_loss_pct": 15.0,
    "alert_low_cash_pct": 5.0,
    "hk_connect_daily_quota_cny": 1_000_000.0,  # paper default 100万
}


def trade_date_shanghai(when: datetime | None = None) -> date:
    if when is None:
        when = datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(SH_TZ).date()


def is_weekday(d: date) -> bool:
    return d.weekday() < 5


def next_trading_day(d: date) -> date:
    n = d + timedelta(days=1)
    while not is_weekday(n):
        n += timedelta(days=1)
    return n


def get_account_settings(account: Account) -> dict:
    raw = {}
    if account.settings_json:
        try:
            raw = json.loads(account.settings_json) or {}
        except Exception:
            raw = {}
    out = dict(DEFAULT_SETTINGS)
    out.update({k: v for k, v in raw.items() if v is not None})
    return out


def save_account_settings(db: Session, account: Account, patch: dict) -> dict:
    cur = get_account_settings(account)
    for k, v in patch.items():
        if k not in DEFAULT_SETTINGS:
            continue
        if v is None:
            continue
        cur[k] = float(v)
    # clamps
    cur["alert_max_weight_pct"] = max(5.0, min(100.0, float(cur["alert_max_weight_pct"])))
    cur["alert_loss_pct"] = max(1.0, min(90.0, float(cur["alert_loss_pct"])))
    cur["alert_low_cash_pct"] = max(0.0, min(50.0, float(cur["alert_low_cash_pct"])))
    cur["hk_connect_daily_quota_cny"] = max(0.0, float(cur["hk_connect_daily_quota_cny"]))
    account.settings_json = json.dumps(cur, ensure_ascii=False)
    db.commit()
    db.refresh(account)
    try:
        from app.services.trading import invalidate_positions_cache

        invalidate_positions_cache(account.id)
    except Exception:
        pass
    return cur


def applies_t1(instrument: Instrument) -> bool:
    """A-share equities/ETFs and HK equities: T+1. Funds/crypto/US/custom/futures: T+0 paper."""
    if instrument.instrument_type in ("fund", "crypto", "future", "custom"):
        return False
    m = (instrument.market or "").upper()
    if m in ("CN", "HK"):
        return True
    if instrument.asset_class in ("equity_cn", "equity_hk", "gold") and m != "US":
        return True
    return False


def bought_on_trade_date_micros(db: Session, account_id: int, symbol: str, day: date) -> int:
    """Sum buy qty filled on Shanghai trade date `day`."""
    day_s = day.isoformat()
    rows = (
        db.query(Order)
        .filter(Order.account_id == account_id, Order.symbol == symbol, Order.side == "buy", Order.status == "filled")
        .all()
    )
    total = 0
    for o in rows:
        ts = o.filled_at or o.created_at
        if not ts:
            continue
        if trade_date_shanghai(ts).isoformat() == day_s:
            total += int(o.qty_micros)
    return total


def sellable_qty_micros(db: Session, account_id: int, instrument: Instrument, position_qty_micros: int) -> int:
    if position_qty_micros <= 0:
        return 0
    if not applies_t1(instrument):
        return position_qty_micros
    today = trade_date_shanghai()
    locked = bought_on_trade_date_micros(db, account_id, instrument.symbol, today)
    return max(0, position_qty_micros - locked)


def is_hk_connect(instrument: Instrument) -> bool:
    return (instrument.market or "").upper() == "HK" or instrument.asset_class == "equity_hk"


def hk_connect_status(db: Session, account: Account) -> dict:
    settings = get_account_settings(account)
    quota = float(settings["hk_connect_daily_quota_cny"])
    day = trade_date_shanghai().isoformat()
    row = (
        db.query(HkConnectDaily)
        .filter(HkConnectDaily.account_id == account.id, HkConnectDaily.trade_date == day)
        .first()
    )
    used = (row.used_cny_cents / 100) if row else 0.0
    remaining = max(0.0, quota - used)
    return {
        "trade_date": day,
        "quota_cny": quota,
        "used_cny": used,
        "remaining_cny": remaining,
        "exhausted": remaining <= 0 and quota > 0,
    }


def consume_hk_connect_quota(db: Session, account: Account, notional_hkd_cents: int) -> dict:
    """Convert HKD buy notional to CNY and consume daily paper quota."""
    status = hk_connect_status(db, account)
    rate, _ = get_fx_rate("HKD", "CNY")
    cny_cents = money_to_cents((notional_hkd_cents / 100) * rate)
    need = cny_cents / 100
    if need > status["remaining_cny"] + 1e-6:
        raise AppError(
            "HK_CONNECT_QUOTA",
            f"港股通今日额度不足：还需约 ¥{need:.0f}，剩余 ¥{status['remaining_cny']:.0f}"
            f"（额度 ¥{status['quota_cny']:.0f}）。",
            extra=status,
        )
    day = status["trade_date"]
    row = (
        db.query(HkConnectDaily)
        .filter(HkConnectDaily.account_id == account.id, HkConnectDaily.trade_date == day)
        .first()
    )
    now = datetime.now(timezone.utc)
    if not row:
        row = HkConnectDaily(account_id=account.id, trade_date=day, used_cny_cents=0, updated_at=now)
        db.add(row)
        db.flush()
    row.used_cny_cents += cny_cents
    row.updated_at = now
    return hk_connect_status(db, account)


def period_equity_change(
    db: Session,
    account_id: int,
    *,
    days: int,
    equity_now_cents: int | None = None,
) -> dict:
    """Compare live equity to snapshot ~`days` ago, adjusting for net deposits since then."""
    from app.models import CashFlow, EquitySnapshot
    from app.services.accounts import convert_to_base_cents, get_account_or_404
    from app.services.equity import take_snapshot, _live_equity_parts

    account = get_account_or_404(db, account_id)
    base = account.currency.upper()
    if equity_now_cents is None:
        take_snapshot(db, account_id)
        equity_now, _, _ = _live_equity_parts(db, account_id)
    else:
        equity_now = equity_now_cents

    today = trade_date_shanghai()
    target = today - timedelta(days=days)
    # walk back to find a snapshot
    snaps = (
        db.query(EquitySnapshot)
        .filter(EquitySnapshot.account_id == account_id, EquitySnapshot.snapshot_date <= target.isoformat())
        .order_by(EquitySnapshot.snapshot_date.desc())
        .limit(1)
        .all()
    )
    if not snaps:
        # fallback: earliest snapshot
        snaps = (
            db.query(EquitySnapshot)
            .filter(EquitySnapshot.account_id == account_id)
            .order_by(EquitySnapshot.snapshot_date.asc())
            .limit(1)
            .all()
        )
    if not snaps:
        return {
            "pnl": 0.0,
            "pnl_pct": None,
            "from_date": None,
            "to_date": today.isoformat(),
            "baseline_equity": float(cents_to_money(equity_now)),
            "current_equity": float(cents_to_money(equity_now)),
        }

    snap = snaps[0]
    # net deposits after snap date (exclude initial already in snap)
    flows = (
        db.query(CashFlow)
        .filter(CashFlow.account_id == account_id, CashFlow.type.in_(("deposit", "withdraw")))
        .all()
    )
    net_dep = 0
    for f in flows:
        ts = f.occurred_at
        if not ts:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if trade_date_shanghai(ts).isoformat() <= snap.snapshot_date:
            continue
        ccy = (f.currency or base).upper()
        cents = convert_to_base_cents(int(f.amount_cents), ccy, base)
        if f.type == "deposit":
            net_dep += cents
        else:
            net_dep -= cents

    baseline = snap.total_equity_cents + net_dep
    pnl_cents = equity_now - baseline
    pct = None
    if baseline > 0:
        pct = round(pnl_cents / baseline * 100, 2)
    return {
        "pnl": float(cents_to_money(pnl_cents)),
        "pnl_pct": pct,
        "from_date": snap.snapshot_date,
        "to_date": today.isoformat(),
        "baseline_equity": float(cents_to_money(baseline)),
        "current_equity": float(cents_to_money(equity_now)),
    }
