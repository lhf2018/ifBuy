"""Crypto spot via Binance public API (fallback: yfinance). Symbols: BTC-USD"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone

from app.providers.base import BarDTO, InstrumentDraft, QuoteDTO

_SYMBOL_RE = re.compile(r"^([A-Z0-9]{2,10})-USD$", re.I)

CRYPTO_PRESETS: dict[str, str] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "BNB": "BNB",
    "XRP": "XRP",
    "DOGE": "Dogecoin",
}

# Binance USDT pairs used as USD proxy
_BINANCE = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "BNB": "BNBUSDT",
    "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT",
}


def _parse(symbol: str) -> str:
    m = _SYMBOL_RE.match(symbol.upper())
    if not m:
        raise ValueError(f"invalid crypto symbol: {symbol}")
    return m.group(1).upper()


def _draft(base: str, name: str) -> InstrumentDraft:
    base = base.upper()
    return InstrumentDraft(
        symbol=f"{base}-USD",
        ticker=base,
        name=name or base,
        instrument_type="crypto",
        asset_class="crypto",
        market="CRYPTO",
        currency="USD",
        lot_size=1,
        tick_size=0.01,
        provider="binance",
    )


def crypto_presets() -> list[InstrumentDraft]:
    return [_draft(c, n) for c, n in CRYPTO_PRESETS.items()]


def _http_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "IfBuy/1.0"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))


class CryptoProvider:
    name = "binance"

    def search(self, keyword: str) -> list[InstrumentDraft]:
        keyword = keyword.strip()
        if not keyword:
            return crypto_presets()
        out: list[InstrumentDraft] = []
        m = re.fullmatch(r"([A-Za-z0-9]{2,10})(?:-USD)?", keyword)
        if m:
            base = m.group(1).upper()
            if base in CRYPTO_PRESETS or base in _BINANCE:
                out.append(_draft(base, CRYPTO_PRESETS.get(base, base)))
                return out
        kw = keyword.lower().replace("-usd", "")
        for base, name in CRYPTO_PRESETS.items():
            if kw in base.lower() or kw in name.lower():
                out.append(_draft(base, name))
        return out

    def get_quote(self, symbol: str) -> QuoteDTO:
        bars = self.get_bars(symbol, "1d", "none", 3)
        if not bars:
            raise RuntimeError(f"no crypto bars for {symbol}")
        price = bars[-1].close
        prev = bars[-2].close if len(bars) > 1 else None
        chg = (price - prev) if prev else None
        pct = ((price - prev) / prev * 100) if prev else None
        return QuoteDTO(
            symbol=symbol.upper(),
            price=price,
            change=chg,
            change_pct=pct,
            prev_close=prev,
            as_of=datetime.now(timezone.utc),
            session="regular",
            stale=False,
            provider=self.name,
        )

    def get_bars(self, symbol: str, interval: str, adjust: str, limit: int) -> list[BarDTO]:
        base = _parse(symbol)
        pair = _BINANCE.get(base)
        if not pair:
            raise RuntimeError(f"unsupported crypto {base}")
        binance_interval = "1w" if interval == "1w" else "1d"
        url = (
            f"https://api.binance.com/api/v3/klines?symbol={pair}"
            f"&interval={binance_interval}&limit={min(max(limit, 10), 500)}"
        )
        raw = _http_json(url)
        if not isinstance(raw, list) or not raw:
            raise RuntimeError("empty crypto klines")
        bars: list[BarDTO] = []
        for row in raw[-limit:]:
            # [open_time, open, high, low, close, volume, ...]
            ts = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            bars.append(
                BarDTO(
                    ts=ts,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=int(float(row[5])),
                    finalized=True,
                )
            )
        if bars:
            bars[-1].finalized = False
        return bars
