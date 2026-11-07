from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.money import price_to_e4
from app.models import Bar, Instrument
from app.providers.akshare_cn import AkshareCNProvider, get_cached_name
from app.providers.akshare_fund import AkshareFundProvider, FUND_PRESETS, fund_presets
from app.providers.akshare_hk import AkshareHKProvider, hk_presets
from app.providers.akshare_fut import AkshareFutProvider, fut_presets
from app.providers.crypto import CryptoProvider, crypto_presets
from app.providers.base import BarDTO, InstrumentDraft, QuoteDTO
from app.providers.yahoo_us import YahooUSProvider, GOLD_PRESETS

_CN_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$", re.I)
_FUND_RE = re.compile(r"^\d{6}\.OF$", re.I)
_HK_RE = re.compile(r"^\d{1,5}\.HK$", re.I)
_FUT_RE = re.compile(r"^[A-Z]{1,3}0\.FUT$", re.I)
_CRYPTO_RE = re.compile(r"^[A-Z0-9]{2,10}-USD$", re.I)
_CUST_RE = re.compile(r"^CUST\.[A-Z0-9_-]{1,24}$", re.I)
_US_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,10}$")

_quote_cache: dict[str, tuple[float, QuoteDTO]] = {}
_QUOTE_TTL = 10.0
_executor = ThreadPoolExecutor(max_workers=4)

cn_provider = AkshareCNProvider()
us_provider = YahooUSProvider()
fund_provider = AkshareFundProvider()
hk_provider = AkshareHKProvider()
fut_provider = AkshareFutProvider()
crypto_provider = CryptoProvider()


def validate_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if (
        _CN_RE.match(s)
        or _FUND_RE.match(s)
        or _HK_RE.match(s)
        or _FUT_RE.match(s)
        or _CRYPTO_RE.match(s)
        or _CUST_RE.match(s)
        or _US_RE.match(s)
    ):
        return s
    raise AppError("INSTRUMENT_NOT_FOUND", f"不支持的代码格式：{symbol}")


def _provider_for(symbol: str):
    if _CUST_RE.match(symbol):
        return None  # manual
    if _FUND_RE.match(symbol):
        return fund_provider
    if _HK_RE.match(symbol):
        return hk_provider
    if _FUT_RE.match(symbol):
        return fut_provider
    if _CRYPTO_RE.match(symbol):
        return crypto_provider
    if _CN_RE.match(symbol):
        return cn_provider
    return us_provider


def _upsert_instrument(db: Session, draft: InstrumentDraft) -> Instrument:
    inst = db.query(Instrument).filter(Instrument.symbol == draft.symbol).first()
    tick_e4 = price_to_e4(draft.tick_size)
    if inst:
        inst.name = draft.name or inst.name
        inst.instrument_type = draft.instrument_type
        inst.asset_class = draft.asset_class
        inst.theme = draft.theme
        inst.updated_at = datetime.now(timezone.utc)
    else:
        inst = Instrument(
            symbol=draft.symbol,
            ticker=draft.ticker,
            name=draft.name,
            instrument_type=draft.instrument_type,
            theme=draft.theme,
            asset_class=draft.asset_class,
            market=draft.market,
            currency=draft.currency,
            lot_size=draft.lot_size,
            tick_size_e4=tick_e4,
            provider=draft.provider,
        )
        db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def search_instruments(db: Session, q: str, asset_class: str | None = None, theme: str | None = None) -> list[dict]:
    q = q.strip()
    drafts: list[InstrumentDraft] = []
    want_fund = asset_class == "fund_cn"
    want_hk = asset_class == "equity_hk"
    want_fut = asset_class == "commodity"
    want_crypto = asset_class == "crypto"
    want_custom = asset_class == "custom"

    if not q:
        if theme == "gold" or asset_class == "gold":
            drafts.extend(
                [
                    InstrumentDraft(
                        symbol="518880.SH",
                        ticker="518880",
                        name="华安黄金易ETF",
                        instrument_type="etf",
                        asset_class="gold",
                        market="CN",
                        currency="CNY",
                        lot_size=100,
                        theme="gold",
                        provider="preset",
                    ),
                    InstrumentDraft(
                        symbol="GLD",
                        ticker="GLD",
                        name=GOLD_PRESETS["GLD"],
                        instrument_type="etf",
                        asset_class="gold",
                        market="US",
                        currency="USD",
                        lot_size=1,
                        theme="gold",
                        provider="preset",
                    ),
                ]
            )
        elif want_fund:
            drafts.extend(fund_presets())
        elif want_hk:
            drafts.extend(hk_presets())
        elif want_fut:
            drafts.extend(fut_presets())
        elif want_crypto:
            drafts.extend(crypto_presets())
        elif want_custom:
            rows = db.query(Instrument).filter(Instrument.asset_class == "custom").limit(50).all()
            return [_instrument_dict(r) for r in rows]
        else:
            return []
    elif want_custom:
        rows = (
            db.query(Instrument)
            .filter(Instrument.asset_class == "custom", Instrument.name.contains(q) | Instrument.symbol.contains(q.upper()))
            .limit(50)
            .all()
        )
        return [_instrument_dict(r) for r in rows]
    elif want_fund or q.upper().endswith(".OF") or (re.fullmatch(r"\d{6}", q) and q in FUND_PRESETS):
        code = q.upper().removesuffix(".OF")
        drafts.extend(_run(fund_provider.search, code if re.fullmatch(r"\d{6}", code) else q))
    elif want_hk or q.upper().endswith(".HK"):
        drafts.extend(_run(hk_provider.search, q))
    elif want_fut or q.upper().endswith(".FUT"):
        drafts.extend(_run(fut_provider.search, q))
    elif want_crypto or _CRYPTO_RE.match(q.upper()) or q.upper().endswith("-USD"):
        drafts.extend(_run(crypto_provider.search, q))
    else:
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in q)
        if re.fullmatch(r"\d{6}", q) or re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", q, re.I) or has_cjk:
            drafts.extend(_run(cn_provider.search, q))
            if has_cjk:
                drafts.extend(_run(fund_provider.search, q))
                drafts.extend(_run(hk_provider.search, q))
        if re.fullmatch(r"\d{1,5}", q) or q.upper().endswith(".HK"):
            drafts.extend(_run(hk_provider.search, q))
        if _US_RE.match(q.upper()) or q.upper() in GOLD_PRESETS or "gold" in q.lower():
            drafts.extend(_run(us_provider.search, q))
        if not drafts:
            drafts.extend(_run(cn_provider.search, q))
            drafts.extend(_run(us_provider.search, q))
            drafts.extend(_run(fund_provider.search, q))
            drafts.extend(_run(hk_provider.search, q))

    results = []
    for d in drafts:
        if asset_class and d.asset_class != asset_class and not (asset_class == "gold" and d.theme == "gold"):
            continue
        if theme and d.theme != theme:
            continue
        inst = _upsert_instrument(db, d)
        results.append(_instrument_dict(inst))
    return results


def _run(fn, *args, timeout: float = 20):
    try:
        fut = _executor.submit(fn, *args)
        return fut.result(timeout=timeout)
    except Exception:
        return []


def get_instrument(db: Session, symbol: str) -> dict:
    symbol = validate_symbol(symbol)
    inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
    if not inst:
        # try resolve via search
        found = search_instruments(db, symbol.split(".")[0] if "." in symbol else symbol)
        inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
        if not inst and found:
            # pick exact
            for f in found:
                if f["symbol"] == symbol:
                    inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
                    break
    if not inst:
        # synthesize from symbol rules
        if _FUND_RE.match(symbol):
            code = symbol.split(".")[0]
            found = _run(fund_provider.search, code)
            draft = found[0] if found else InstrumentDraft(
                symbol=symbol,
                ticker=code,
                name=FUND_PRESETS.get(code, code),
                instrument_type="fund",
                asset_class="fund_cn",
                market="CN",
                currency="CNY",
                lot_size=1,
                tick_size=0.0001,
                provider="akshare_fund",
            )
            inst = _upsert_instrument(db, draft)
        elif _HK_RE.match(symbol):
            found = _run(hk_provider.search, symbol)
            if not found:
                raise AppError("INSTRUMENT_NOT_FOUND", f"找不到港股 {symbol}", status_code=404)
            inst = _upsert_instrument(db, found[0])
        elif _FUT_RE.match(symbol):
            found = _run(fut_provider.search, symbol)
            if not found:
                raise AppError("INSTRUMENT_NOT_FOUND", f"找不到期货 {symbol}", status_code=404)
            inst = _upsert_instrument(db, found[0])
        elif _CRYPTO_RE.match(symbol):
            found = _run(crypto_provider.search, symbol)
            if not found:
                raise AppError("INSTRUMENT_NOT_FOUND", f"找不到加密货币 {symbol}", status_code=404)
            inst = _upsert_instrument(db, found[0])
        elif _CUST_RE.match(symbol):
            raise AppError("INSTRUMENT_NOT_FOUND", "请先在行情「自定义」里创建该资产", status_code=404)
        elif _CN_RE.match(symbol):
            code = symbol.split(".")[0]
            name = get_cached_name(symbol) or code
            itype = "etf" if code.startswith(("15", "16", "51", "56", "58")) else "equity"
            draft = InstrumentDraft(
                symbol=symbol,
                ticker=code,
                name=name,
                instrument_type=itype,
                asset_class="gold" if "黄金" in name else "equity_cn",
                market="CN",
                currency="CNY",
                lot_size=100,
                theme="gold" if "黄金" in name else None,
                provider="akshare",
            )
            inst = _upsert_instrument(db, draft)
        elif _US_RE.match(symbol):
            gold = symbol in GOLD_PRESETS
            draft = InstrumentDraft(
                symbol=symbol,
                ticker=symbol,
                name=GOLD_PRESETS.get(symbol, symbol),
                instrument_type="etf" if gold else "equity",
                asset_class="gold" if gold else "equity_us",
                market="US",
                currency="USD",
                lot_size=1,
                theme="gold" if gold else None,
                provider="yfinance",
            )
            inst = _upsert_instrument(db, draft)
        else:
            raise AppError("INSTRUMENT_NOT_FOUND", f"找不到标的 {symbol}", status_code=404)
    return _instrument_dict(inst)


def _instrument_dict(inst: Instrument) -> dict:
    return {
        "symbol": inst.symbol,
        "ticker": inst.ticker,
        "name": inst.name,
        "instrument_type": inst.instrument_type,
        "theme": inst.theme,
        "asset_class": inst.asset_class,
        "market": inst.market,
        "currency": inst.currency,
        "lot_size": inst.lot_size,
        "tick_size": inst.tick_size_e4 / 10000,
        "provider": inst.provider,
    }


def _quote_from_last_bar(symbol: str) -> QuoteDTO | None:
    """Fallback price from local bars cache when live providers fail."""
    from app.core.money import e4_to_price
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        rows = (
            db.query(Bar)
            .filter(Bar.symbol == symbol, Bar.interval == "1d")
            .order_by(Bar.ts.desc())
            .limit(2)
            .all()
        )
        if not rows:
            return None
        latest = rows[0]
        prev = rows[1] if len(rows) > 1 else None
        price = float(e4_to_price(latest.close_e4))
        prev_close = float(e4_to_price(prev.close_e4)) if prev else None
        chg = (price - prev_close) if prev_close else None
        pct = ((price - prev_close) / prev_close * 100) if prev_close else None
        return QuoteDTO(
            symbol=symbol,
            price=price,
            change=chg,
            change_pct=pct,
            prev_close=prev_close,
            as_of=datetime.now(timezone.utc),
            session="closed",
            stale=True,
            provider="bar_cache",
        )
    finally:
        db.close()


def _quote_from_custom(symbol: str) -> QuoteDTO | None:
    import json

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        inst = db.query(Instrument).filter(Instrument.symbol == symbol).first()
        if not inst or not inst.meta_json:
            return None
        meta = json.loads(inst.meta_json)
        price = float(meta.get("manual_price") or 0)
        if price <= 0:
            return None
        return QuoteDTO(
            symbol=symbol,
            price=price,
            change=None,
            change_pct=None,
            prev_close=None,
            as_of=datetime.now(timezone.utc),
            session="closed",
            stale=True,
            provider="manual",
        )
    except Exception:
        return None
    finally:
        db.close()


def get_quote(symbol: str, allow_stale: bool = True) -> QuoteDTO:
    symbol = validate_symbol(symbol)
    now = time.time()
    cached = _quote_cache.get(symbol)
    if cached and now - cached[0] < _QUOTE_TTL:
        q = cached[1]
        q.stale = False
        return q
    if _CUST_RE.match(symbol):
        q = _quote_from_custom(symbol)
        if q:
            _quote_cache[symbol] = (now, q)
            return q
        raise AppError("QUOTE_UNAVAILABLE", "自定义资产暂无估值，请先更新估值")
    provider = _provider_for(symbol)
    try:
        fut = _executor.submit(provider.get_quote, symbol)
        q = fut.result(timeout=12)
        _quote_cache[symbol] = (now, q)
        return q
    except Exception:
        if allow_stale and cached:
            q = cached[1]
            q.stale = True
            return q
        if allow_stale:
            bar_q = _quote_from_last_bar(symbol)
            if bar_q:
                _quote_cache[symbol] = (now, bar_q)
                return bar_q
        raise AppError("QUOTE_UNAVAILABLE", "暂无行情，请手填价格")


def get_quotes(symbols: list[str]) -> list[dict]:
    syms = [validate_symbol(s) for s in symbols[:50] if s.strip()]
    futs = {s: _executor.submit(get_quote, s) for s in syms}
    out = []
    for s in syms:
        try:
            q = futs[s].result(timeout=15)
            out.append(_quote_dict(q))
        except Exception:
            out.append({"symbol": s, "price": None, "stale": True, "session": "unknown", "as_of": None})
    return out


def _quote_dict(q: QuoteDTO) -> dict:
    return {
        "symbol": q.symbol,
        "price": q.price,
        "change": q.change,
        "change_pct": q.change_pct,
        "prev_close": q.prev_close,
        "as_of": q.as_of.isoformat() if q.as_of else None,
        "session": q.session,
        "stale": q.stale,
        "provider": q.provider,
    }


def get_bars(db: Session, symbol: str, interval: str, adjust: str, limit: int) -> list[dict]:
    symbol = validate_symbol(symbol)
    if interval not in ("1d", "1w"):
        raise AppError("IMPORT_INVALID", f"不支持的周期 {interval}")
    if adjust not in ("none", "forward", "backward"):
        adjust = "none"

    # serve from cache if enough finalized bars
    cached = (
        db.query(Bar)
        .filter(Bar.symbol == symbol, Bar.interval == interval, Bar.adjust == adjust)
        .order_by(Bar.ts.asc())
        .all()
    )
    need_fetch = True
    if len(cached) >= min(limit, 30):
        last = cached[-1]
        age = (datetime.now(timezone.utc) - last.fetched_at.replace(tzinfo=timezone.utc)).total_seconds() if last.fetched_at.tzinfo is None else (datetime.now(timezone.utc) - last.fetched_at).total_seconds()
        if last.finalized and age < 3600:
            need_fetch = False
        elif not last.finalized and age < 30:
            need_fetch = False

    if need_fetch:
        if _CUST_RE.match(symbol):
            # flat synthetic bar from manual price
            q = _quote_from_custom(symbol)
            if not q:
                if cached:
                    return [_bar_dict(b) for b in cached[-limit:]]
                raise AppError("QUOTE_UNAVAILABLE", "自定义资产暂无估值")
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            bars = [
                BarDTO(
                    ts=day,
                    open=q.price,
                    high=q.price,
                    low=q.price,
                    close=q.price,
                    volume=0,
                    finalized=False,
                )
            ]
        else:
            provider = _provider_for(symbol)
            try:
                fut = _executor.submit(provider.get_bars, symbol, interval, adjust, limit)
                bars: list[BarDTO] = fut.result(timeout=15)
            except Exception as e:
                if cached:
                    return [_bar_dict(b) for b in cached[-limit:]]
                raise AppError("QUOTE_UNAVAILABLE", f"K 线暂时拉不到：{e}")
        # replace cache for this key
        db.query(Bar).filter(Bar.symbol == symbol, Bar.interval == interval, Bar.adjust == adjust).delete()
        for b in bars:
            db.add(
                Bar(
                    symbol=symbol,
                    interval=interval,
                    ts=b.ts,
                    adjust=adjust,
                    open_e4=price_to_e4(b.open),
                    high_e4=price_to_e4(b.high),
                    low_e4=price_to_e4(b.low),
                    close_e4=price_to_e4(b.close),
                    volume=b.volume,
                    finalized=b.finalized,
                )
            )
        db.commit()
        cached = (
            db.query(Bar)
            .filter(Bar.symbol == symbol, Bar.interval == interval, Bar.adjust == adjust)
            .order_by(Bar.ts.asc())
            .all()
        )

    return [_bar_dict(b) for b in cached[-limit:]]


def _bar_dict(b: Bar) -> dict:
    return {
        "ts": b.ts,
        "open": b.open_e4 / 10000,
        "high": b.high_e4 / 10000,
        "low": b.low_e4 / 10000,
        "close": b.close_e4 / 10000,
        "volume": b.volume,
        "finalized": b.finalized,
    }
