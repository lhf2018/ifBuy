"""Portfolio risk hints for paper ledgers."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.money import cents_to_money, money_to_cents
from app.models import EquitySnapshot
from app.services.accounts import account_to_dict, convert_to_base_cents, get_account_or_404, net_deposit_base_cents
from app.services.rules import get_account_settings, hk_connect_status
from app.services.trading import list_positions


def risk_report(db: Session, account_id: int) -> dict:
    from app.core.cache import cache_get, cache_set

    cache_key = f"risk:{account_id}"
    hit = cache_get(cache_key)
    if hit is not None:
        return hit

    account = get_account_or_404(db, account_id)
    settings = get_account_settings(account)
    max_w = float(settings["alert_max_weight_pct"])
    loss_th = float(settings["alert_loss_pct"])
    low_cash = float(settings["alert_low_cash_pct"])
    positions = list_positions(db, account_id)
    base = account.currency.upper()

    mv_by_symbol: list[dict] = []
    total_mv_base = 0
    for p in positions:
        if p.get("market_value") is None or not p.get("currency"):
            continue
        cents = money_to_cents(p["market_value"])
        base_cents = convert_to_base_cents(cents, p["currency"].upper(), base)
        total_mv_base += base_cents
        mv_by_symbol.append(
            {
                "symbol": p["symbol"],
                "name": p["name"],
                "market_value_base": float(cents_to_money(base_cents)),
                "weight_pct": None,
                "unrealized_pct": p.get("unrealized_pct"),
            }
        )

    summary = account_to_dict(
        account,
        db=db,
        market_value_by_ccy={
            (p["currency"] or base).upper(): money_to_cents(p["market_value"] or 0)
            for p in positions
            if p.get("market_value") is not None
        },
    )
    # rebuild market_value_by properly
    mv_map: dict[str, int] = {}
    for p in positions:
        if p.get("market_value") is None or not p.get("currency"):
            continue
        ccy = p["currency"].upper()
        mv_map[ccy] = mv_map.get(ccy, 0) + money_to_cents(p["market_value"])
    summary = account_to_dict(account, db=db, market_value_by_ccy=mv_map)

    equity = float(summary["total_equity"])
    cash = float(summary.get("cash_total") or summary.get("cash_balance") or 0)
    # cash_total may not exist — compute from wallets
    wallets = summary.get("wallets") or summary.get("cash_by_currency") or {}
    cash_base = 0
    for ccy, amt in wallets.items():
        if amt is None:
            continue
        cash_base += convert_to_base_cents(money_to_cents(amt), str(ccy).upper(), base)
    cash = float(cents_to_money(cash_base))

    for row in mv_by_symbol:
        if equity > 0:
            row["weight_pct"] = round(row["market_value_base"] / equity * 100, 2)

    mv_by_symbol.sort(key=lambda x: x["market_value_base"], reverse=True)
    top = mv_by_symbol[0] if mv_by_symbol else None
    top_weight = top["weight_pct"] if top and top["weight_pct"] is not None else 0.0
    cash_ratio = round(cash / equity * 100, 2) if equity > 0 else 100.0
    invested_ratio = round(100 - cash_ratio, 2) if equity > 0 else 0.0

    # max drawdown from equity snapshots
    snaps = (
        db.query(EquitySnapshot)
        .filter(EquitySnapshot.account_id == account_id)
        .order_by(EquitySnapshot.snapshot_date.asc())
        .all()
    )
    peak = 0
    max_dd = 0.0
    max_dd_date = None
    for s in snaps:
        eq = s.total_equity_cents
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd
                max_dd_date = s.snapshot_date

    net = net_deposit_base_cents(db, account)
    pnl = money_to_cents(equity) - net
    return_pct = float((Decimal(pnl) / Decimal(net) * 100).quantize(Decimal("0.01"))) if net > 0 else None

    alerts: list[dict] = []
    warn_w = max_w
    info_w = max(10.0, max_w * 0.6)
    if top_weight >= warn_w:
        alerts.append(
            {
                "level": "warn",
                "code": "CONCENTRATION",
                "message": f"单票集中度偏高：{top['name']} 约占权益 {top_weight}%（阈值 {warn_w:g}%）",
            }
        )
    elif top_weight >= info_w:
        alerts.append(
            {
                "level": "info",
                "code": "CONCENTRATION",
                "message": f"最大持仓 {top['name']} 约占 {top_weight}%",
            }
        )
    if cash_ratio < low_cash and equity > 0:
        alerts.append(
            {
                "level": "warn",
                "code": "LOW_CASH",
                "message": f"现金比例偏低（{cash_ratio}%，阈值 {low_cash:g}%），缓冲不足",
            }
        )
    if cash_ratio > 80 and total_mv_base > 0:
        alerts.append({"level": "info", "code": "HIGH_CASH", "message": f"现金比例较高（{cash_ratio}%），仓位偏轻"})
    if max_dd >= 20:
        alerts.append(
            {
                "level": "warn",
                "code": "DRAWDOWN",
                "message": f"历史最大回撤约 {max_dd:.1f}%（{max_dd_date or '—'}）",
            }
        )
    elif max_dd >= 10:
        alerts.append(
            {
                "level": "info",
                "code": "DRAWDOWN",
                "message": f"历史最大回撤约 {max_dd:.1f}%",
            }
        )
    losers = [p for p in positions if (p.get("unrealized_pct") or 0) <= -loss_th]
    if losers:
        names = "、".join(p["name"] for p in losers[:3])
        alerts.append(
            {
                "level": "warn",
                "code": "UNDERWATER",
                "message": f"浮亏超过 {loss_th:g}%：{names}" + ("…" if len(losers) > 3 else ""),
            }
        )
    t1_locked = [p for p in positions if (p.get("locked_qty") or 0) > 0]
    if t1_locked:
        alerts.append(
            {
                "level": "info",
                "code": "T1_LOCKED",
                "message": f"T+1 锁定中：{len(t1_locked)} 只标的有今日买入不可卖份额",
            }
        )
    hk = hk_connect_status(db, account)
    if hk["quota_cny"] > 0 and hk["remaining_cny"] / hk["quota_cny"] < 0.1:
        alerts.append(
            {
                "level": "warn" if hk["exhausted"] else "info",
                "code": "HK_CONNECT",
                "message": f"港股通今日额度剩余 ¥{hk['remaining_cny']:.0f} / ¥{hk['quota_cny']:.0f}",
            }
        )
    if not alerts:
        alerts.append({"level": "ok", "code": "OK", "message": "暂无特别风险提示"})

    flagged = []
    for p in positions:
        flags = []
        if equity > 0 and p.get("market_value") is not None and p.get("currency"):
            # weight approx in instrument ccy skipped — use holdings list
            pass
        if (p.get("unrealized_pct") or 0) <= -loss_th:
            flags.append("loss")
        if (p.get("locked_qty") or 0) > 0:
            flags.append("t1")
        for h in mv_by_symbol:
            if h["symbol"] == p["symbol"] and (h.get("weight_pct") or 0) >= warn_w:
                flags.append("concentration")
        if flags:
            flagged.append({"symbol": p["symbol"], "name": p["name"], "flags": flags})

    result = {
        "account_id": account_id,
        "base_currency": base,
        "total_equity": equity,
        "cash": cash,
        "cash_ratio_pct": cash_ratio,
        "invested_ratio_pct": invested_ratio,
        "return_pct": return_pct,
        "max_drawdown_pct": round(max_dd, 2),
        "max_drawdown_date": max_dd_date,
        "top_holding": top,
        "holdings": mv_by_symbol,
        "alerts": alerts,
        "settings": settings,
        "hk_connect": hk,
        "flagged_positions": flagged,
    }
    cache_set(cache_key, result, 45.0)
    return result
