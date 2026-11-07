from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_HALF_UP

from app.core.errors import AppError
from app.core.money import d

_executor = ThreadPoolExecutor(max_workers=2)
_cache: dict[str, tuple[float, float]] = {}  # pair -> (ts, rate)  rate = USD per 1 CNY? We'll use: amount_to = amount_from * rate where rate = to/from


def get_fx_rate(from_ccy: str, to_ccy: str) -> tuple[float, str]:
    """Return (rate, source) where 1 from_ccy = rate to_ccy."""
    from_ccy = from_ccy.upper()
    to_ccy = to_ccy.upper()
    if from_ccy == to_ccy:
        return 1.0, "identity"
    key = f"{from_ccy}/{to_ccy}"
    import time

    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached[0] < 300:
        return cached[1], "cache"

    # Prefer USD/CNY then invert
    try:
        fut = _executor.submit(_fetch_usd_cny)
        usd_cny = fut.result(timeout=8)  # CNY per 1 USD
        if from_ccy == "USD" and to_ccy == "CNY":
            rate = usd_cny
        elif from_ccy == "CNY" and to_ccy == "USD":
            rate = 1.0 / usd_cny
        else:
            raise AppError("FX_UNSUPPORTED", f"暂不支持 {from_ccy}→{to_ccy} 换汇")
        _cache[key] = (now, rate)
        return rate, "yfinance"
    except AppError:
        raise
    except Exception:
        # fallback approximate
        if from_ccy == "USD" and to_ccy == "CNY":
            return 7.2, "fallback"
        if from_ccy == "CNY" and to_ccy == "USD":
            return 1 / 7.2, "fallback"
        raise AppError("FX_UNAVAILABLE", "暂时拿不到汇率，请手填汇率后再换。")


def _fetch_usd_cny() -> float:
    import yfinance as yf

    t = yf.Ticker("USDCNY=X")
    info = t.fast_info
    price = float(getattr(info, "last_price", None) or getattr(info, "lastPrice", None) or 0)
    if not price:
        hist = t.history(period="5d")
        if hist.empty:
            raise RuntimeError("no fx")
        price = float(hist["Close"].iloc[-1])
    if price <= 0:
        raise RuntimeError("bad fx")
    return price


def convert_cents(amount_cents: int, rate: float) -> int:
    """from_cents * rate -> to_cents (both integer minor units)."""
    out = (Decimal(amount_cents) * d(rate)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(out)
