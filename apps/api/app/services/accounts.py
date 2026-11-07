from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.money import cents_to_money, money_to_cents
from app.models import Account, CashFlow, CashLedger, FxTrade, User, WalletBalance
from app.services.fx import convert_cents, get_fx_rate

SUPPORTED = ("CNY", "USD", "HKD")


def ensure_default_user(db: Session) -> User:
    user = db.query(User).first()
    if user:
        return user
    user = User(display_name="me")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_account_or_404(db: Session, account_id: int) -> Account:
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise AppError("ACCOUNT_NOT_FOUND", "账本不存在", status_code=404)
    return account


def get_wallet(db: Session, account_id: int, currency: str, *, create: bool = True) -> WalletBalance:
    currency = currency.upper()
    if currency not in SUPPORTED:
        raise AppError("FX_UNSUPPORTED", f"暂不支持币种 {currency}")
    row = (
        db.query(WalletBalance)
        .filter(WalletBalance.account_id == account_id, WalletBalance.currency == currency)
        .first()
    )
    if row:
        return row
    if not create:
        raise AppError("ACCOUNT_NOT_FOUND", f"账本没有 {currency} 余额行")
    row = WalletBalance(account_id=account_id, currency=currency, balance_cents=0)
    db.add(row)
    db.flush()
    return row


def ensure_wallets(db: Session, account_id: int) -> list[WalletBalance]:
    return [get_wallet(db, account_id, c) for c in SUPPORTED]


def wallet_balance_cents(db: Session, account_id: int, currency: str) -> int:
    return get_wallet(db, account_id, currency).balance_cents


def _sync_legacy_cash(db: Session, account: Account) -> None:
    """Keep accounts.cash_balance_cents = base-currency wallet for old clients."""
    w = get_wallet(db, account.id, account.currency)
    account.cash_balance_cents = w.balance_cents


def _append_ledger(
    db: Session,
    account: Account,
    type_: str,
    amount_cents: int,
    currency: str,
    note: str | None = None,
    ref_order_id: int | None = None,
) -> CashLedger:
    currency = currency.upper()
    wallet = get_wallet(db, account.id, currency)
    if wallet.balance_cents + amount_cents < 0:
        raise AppError("INSUFFICIENT_CASH", f"{currency} 现金不够。")
    wallet.balance_cents += amount_cents
    wallet.updated_at = datetime.now(timezone.utc)
    entry = CashLedger(
        account_id=account.id,
        type=type_,
        currency=currency,
        amount_cents=amount_cents,
        balance_after_cents=wallet.balance_cents,
        note=note,
        ref_order_id=ref_order_id,
    )
    db.add(entry)
    _sync_legacy_cash(db, account)
    return entry


def create_account(
    db: Session,
    name: str,
    base_currency: str = "CNY",
    initial_cash_cny: float = 0,
    initial_cash_usd: float = 0,
    *,
    # legacy single-field create
    currency: str | None = None,
    initial_cash: float | None = None,
) -> Account:
    ensure_default_user(db)
    base = (currency or base_currency or "CNY").upper()
    if base not in ("CNY", "USD"):
        raise AppError("FX_UNSUPPORTED", "基准货币仅支持 CNY / USD")

    cny = money_to_cents(initial_cash_cny)
    usd = money_to_cents(initial_cash_usd)
    if initial_cash is not None:
        cents = money_to_cents(initial_cash)
        if (currency or base) == "USD":
            usd = cents
            cny = 0
        else:
            cny = cents
            usd = 0
    if cny <= 0 and usd <= 0:
        raise AppError("PRICE_INVALID", "至少要有一种货币的开户本金大于 0。")

    base_initial = cny if base == "CNY" else usd
    account = Account(
        name=name,
        currency=base,
        initial_cash_cents=base_initial,
        cash_balance_cents=0,
        status="active",
    )
    db.add(account)
    db.flush()
    ensure_wallets(db, account.id)

    if cny > 0:
        db.add(CashFlow(account_id=account.id, type="initial", currency="CNY", amount_cents=cny, note="开户本金·人民币"))
        _append_ledger(db, account, "initial", cny, "CNY", note="开户本金·人民币")
    if usd > 0:
        db.add(CashFlow(account_id=account.id, type="initial", currency="USD", amount_cents=usd, note="开户本金·美元"))
        _append_ledger(db, account, "initial", usd, "USD", note="开户本金·美元")

    db.commit()
    db.refresh(account)
    return account


def list_accounts(db: Session) -> list[Account]:
    ensure_default_user(db)
    return db.query(Account).order_by(Account.id.asc()).all()


def update_account(db: Session, account_id: int, name: str | None, status: str | None, note: str | None) -> Account:
    account = get_account_or_404(db, account_id)
    if name is not None:
        account.name = name
    if status is not None:
        account.status = status
    if note is not None:
        account.note = note
    db.commit()
    db.refresh(account)
    return account


def add_cash_flow(
    db: Session,
    account_id: int,
    type_: str,
    amount: float,
    note: str | None,
    currency: str | None = None,
) -> Account:
    account = get_account_or_404(db, account_id)
    ccy = (currency or account.currency).upper()
    if ccy not in SUPPORTED:
        raise AppError("FX_UNSUPPORTED", f"暂不支持币种 {ccy}")
    cents = money_to_cents(amount)
    if type_ == "withdraw":
        if wallet_balance_cents(db, account.id, ccy) < cents:
            raise AppError("INSUFFICIENT_CASH", f"{ccy} 现金不够，拿不走这么多。")
        signed = -cents
    else:
        signed = cents
    db.add(CashFlow(account_id=account.id, type=type_, currency=ccy, amount_cents=cents, note=note))
    _append_ledger(db, account, type_, signed, ccy, note=note)
    db.commit()
    db.refresh(account)
    try:
        from app.services.equity import take_snapshot

        take_snapshot(db, account.id)
    except Exception:
        pass
    return account


def exchange(
    db: Session,
    account_id: int,
    *,
    from_currency: str,
    to_currency: str,
    from_amount: float,
    rate: float | None = None,
    note: str | None = None,
) -> dict:
    account = get_account_or_404(db, account_id)
    frm = from_currency.upper()
    to = to_currency.upper()
    if frm == to:
        raise AppError("FX_UNSUPPORTED", "换汇币种不能相同")
    if frm not in SUPPORTED or to not in SUPPORTED:
        raise AppError("FX_UNSUPPORTED", "目前支持 CNY / USD / HKD 之间换汇")

    from_cents = money_to_cents(from_amount)
    if from_cents <= 0:
        raise AppError("PRICE_INVALID", "换汇金额须大于 0")
    if wallet_balance_cents(db, account.id, frm) < from_cents:
        raise AppError("INSUFFICIENT_CASH", f"{frm} 现金不够换汇。")

    source = "manual"
    if rate is None:
        rate, source = get_fx_rate(frm, to)
    if rate <= 0:
        raise AppError("PRICE_INVALID", "汇率必须大于 0")

    to_cents = convert_cents(from_cents, rate)
    if to_cents <= 0:
        raise AppError("PRICE_INVALID", "换汇后金额过小")

    rate_e6 = int(round(rate * 1_000_000))
    note_text = note or f"换汇 {frm}→{to} @ {rate:.6g}"

    _append_ledger(db, account, "fx_out", -from_cents, frm, note=note_text)
    _append_ledger(db, account, "fx_in", to_cents, to, note=note_text)
    db.add(
        CashFlow(account_id=account.id, type="fx_out", currency=frm, amount_cents=from_cents, note=note_text)
    )
    db.add(
        CashFlow(account_id=account.id, type="fx_in", currency=to, amount_cents=to_cents, note=note_text)
    )
    fx = FxTrade(
        account_id=account.id,
        from_currency=frm,
        to_currency=to,
        from_amount_cents=from_cents,
        to_amount_cents=to_cents,
        rate_e6=rate_e6,
        rate_source=source,
        note=note,
    )
    db.add(fx)
    db.commit()
    db.refresh(fx)
    db.refresh(account)
    try:
        from app.services.equity import take_snapshot

        take_snapshot(db, account.id)
    except Exception:
        pass
    return {
        "id": fx.id,
        "from_currency": frm,
        "to_currency": to,
        "from_amount": float(cents_to_money(from_cents)),
        "to_amount": float(cents_to_money(to_cents)),
        "rate": rate,
        "rate_source": source,
        "account": account_to_dict(account, db=db),
    }


def wallets_dict(db: Session, account_id: int) -> dict[str, float]:
    ensure_wallets(db, account_id)
    rows = db.query(WalletBalance).filter(WalletBalance.account_id == account_id).all()
    return {r.currency: float(cents_to_money(r.balance_cents)) for r in rows}


def convert_to_base_cents(amount_cents: int, from_ccy: str, base: str) -> int:
    from_ccy = from_ccy.upper()
    base = base.upper()
    if from_ccy == base:
        return amount_cents
    rate, _ = get_fx_rate(from_ccy, base)
    return convert_cents(amount_cents, rate)


def account_to_dict(account: Account, db: Session | None = None, market_value_by_ccy: dict[str, int] | None = None) -> dict:
    wallets: dict[str, float] = {}
    if db is not None:
        wallets = wallets_dict(db, account.id)
        _sync_legacy_cash(db, account)
    else:
        wallets = {account.currency: float(cents_to_money(account.cash_balance_cents))}

    base = account.currency
    cash_base_cents = 0
    if db is not None:
        for ccy, amt in wallets.items():
            cash_base_cents += convert_to_base_cents(money_to_cents(amt), ccy, base)
    else:
        cash_base_cents = account.cash_balance_cents

    mv_by = {k: float(cents_to_money(v)) for k, v in (market_value_by_ccy or {}).items()}
    mv_base_cents = 0
    for ccy, cents in (market_value_by_ccy or {}).items():
        mv_base_cents += convert_to_base_cents(cents, ccy, base)

    equity_cents = cash_base_cents + mv_base_cents
    return {
        "id": account.id,
        "name": account.name,
        "currency": base,  # base / display currency
        "base_currency": base,
        "wallets": wallets,
        "initial_cash": float(cents_to_money(account.initial_cash_cents)),
        "cash_balance": float(cents_to_money(cash_base_cents)),  # base 折合现金
        "cash_by_currency": wallets,
        "market_value": float(cents_to_money(mv_base_cents)) if market_value_by_ccy is not None else None,
        "market_value_by_currency": mv_by if market_value_by_ccy is not None else None,
        "total_equity": float(cents_to_money(equity_cents)) if market_value_by_ccy is not None else float(cents_to_money(cash_base_cents)),
        "status": account.status,
        "note": account.note,
        "created_at": account.created_at.isoformat() if account.created_at else None,
    }


def list_cash_flows(db: Session, account_id: int) -> list[dict]:
    get_account_or_404(db, account_id)
    rows = (
        db.query(CashFlow)
        .filter(CashFlow.account_id == account_id)
        .order_by(CashFlow.occurred_at.desc(), CashFlow.id.desc())
        .all()
    )
    return [
        {
            "id": f.id,
            "type": f.type,
            "currency": f.currency,
            "amount": float(cents_to_money(f.amount_cents)),
            "note": f.note,
            "occurred_at": f.occurred_at.isoformat() if f.occurred_at else None,
        }
        for f in rows
    ]


def net_deposit_base_cents(db: Session, account: Account) -> int:
    """Net deposits converted to base currency (FX flows cancel in spirit; only real money-in/out)."""
    flows = db.query(CashFlow).filter(CashFlow.account_id == account.id).all()
    total = 0
    for f in flows:
        ccy = (f.currency or account.currency).upper()
        if f.type in ("initial", "deposit"):
            total += convert_to_base_cents(f.amount_cents, ccy, account.currency)
        elif f.type == "withdraw":
            total -= convert_to_base_cents(f.amount_cents, ccy, account.currency)
        # fx_in / fx_out ignored for net deposit
    return total
