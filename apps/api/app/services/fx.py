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

    fb = {
        ("USD", "CNY"): 7.2,
        ("CNY", "USD"): 1 / 7.2,
        ("HKD", "CNY"): 0.92,
        ("CNY", "HKD"): 1 / 0.92,
        ("HKD", "USD"): 0.128,
        ("USD", "HKD"): 1 / 0.128,
    }
    try:
        if {from_ccy, to_ccy} <= {"USD", "CNY"}:
            fut = _executor.submit(_fetch_pair, "USDCNY=X")
            usd_cny = fut.result(timeout=2)  # keep summary snappy
            rate = usd_cny if (from_ccy == "USD" and to_ccy == "CNY") else 1.0 / usd_cny
        elif {from_ccy, to_ccy} <= {"HKD", "CNY"}:
            fut = _executor.submit(_fetch_pair, "HKDCNY=X")
            hkd_cny = fut.result(timeout=2)
            rate = hkd_cny if (from_ccy == "HKD" and to_ccy == "CNY") else 1.0 / hkd_cny
        elif {from_ccy, to_ccy} <= {"HKD", "USD"}:
            r1, _ = get_fx_rate(from_ccy, "CNY")
            r2, _ = get_fx_rate("CNY", to_ccy)
            rate = r1 * r2
        else:
            raise AppError("FX_UNSUPPORTED", f"暂不支持 {from_ccy}→{to_ccy} 换汇")
        _cache[key] = (now, rate)
        return rate, "yfinance"
    except AppError:
        raise
    except Exception:
        if (from_ccy, to_ccy) in fb:
            _cache[key] = (now, fb[(from_ccy, to_ccy)])
            return fb[(from_ccy, to_ccy)], "fallback"
        raise AppError("FX_UNAVAILABLE", "暂时拿不到汇率，请手填汇率后再换。")


def _fetch_pair(ticker: str) -> float:
    import yfinance as yf

    t = yf.Ticker(ticker)
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
