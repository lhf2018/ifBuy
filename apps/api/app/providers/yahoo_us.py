from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from app.providers.base import BarDTO, InstrumentDraft, QuoteDTO

_US_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,10}$")

GOLD_PRESETS = {
    "GLD": "SPDR Gold Shares",
    "IAU": "iShares Gold Trust",
    "SGOL": "abrdn Physical Gold Shares",
}


class YahooUSProvider:
    name = "yfinance"

    def search(self, keyword: str) -> list[InstrumentDraft]:
        kw = keyword.strip().upper()
        out: list[InstrumentDraft] = []
        if kw in GOLD_PRESETS or "GOLD" in kw or "黄金" in keyword:
            for sym, name in GOLD_PRESETS.items():
                if kw in ("GOLD", "黄金") or kw == sym or kw in name.upper():
                    out.append(self._draft(sym, name, etf=True, gold=True))
        if _US_RE.match(kw):
            name = GOLD_PRESETS.get(kw, kw)
            try:
                import yfinance as yf

                info = yf.Ticker(kw).fast_info
                name = getattr(info, "shortName", None) or name
            except Exception:
                pass
            gold = kw in GOLD_PRESETS
            out.append(self._draft(kw, str(name), etf=gold, gold=gold))
        seen = set()
        uniq = []
        for i in out:
            if i.symbol in seen:
                continue
            seen.add(i.symbol)
            uniq.append(i)
        return uniq

    def _draft(self, symbol: str, name: str, etf: bool = False, gold: bool = False) -> InstrumentDraft:
        return InstrumentDraft(
            symbol=symbol,
            ticker=symbol,
            name=name,
            instrument_type="etf" if etf else "equity",
            asset_class="gold" if gold else "equity_us",
            market="US",
            currency="USD",
            lot_size=1,
            tick_size=0.01,
            theme="gold" if gold else None,
            provider=self.name,
        )

    def get_quote(self, symbol: str) -> QuoteDTO:
        import yfinance as yf

        sym = symbol.upper()
        if not _US_RE.match(sym):
            raise ValueError(f"invalid US symbol: {symbol}")

        last_err: Exception | None = None
        t = yf.Ticker(sym)
        try:
            info = t.fast_info
            price = float(getattr(info, "last_price", None) or getattr(info, "lastPrice", None) or 0)
            prev = float(getattr(info, "previous_close", None) or getattr(info, "previousClose", None) or 0) or None
            if price:
                chg = (price - prev) if prev else None
                pct = ((price - prev) / prev * 100) if prev else None
                return QuoteDTO(
                    symbol=sym,
                    price=price,
                    change=chg,
                    change_pct=pct,
                    prev_close=prev,
                    as_of=datetime.now(timezone.utc),
                    session="regular",
                    provider=self.name,
                )
        except Exception as e:
            last_err = e

        try:
            hist = t.history(period="10d", auto_adjust=False)
            if hist is not None and not hist.empty:
                price = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else None
                chg = (price - prev) if prev else None
                pct = ((price - prev) / prev * 100) if prev else None
                return QuoteDTO(
                    symbol=sym,
                    price=price,
                    change=chg,
                    change_pct=pct,
                    prev_close=prev,
                    as_of=datetime.now(timezone.utc),
                    session="closed",
                    stale=True,
                    provider=self.name,
                )
        except Exception as e:
            last_err = e
        raise RuntimeError(f"US quote failed for {symbol}: {last_err}")

    def get_bars(self, symbol: str, interval: str, adjust: str, limit: int) -> list[BarDTO]:
        import yfinance as yf

        auto_adjust = adjust != "none"
        interval_map = {"1d": "1d", "1w": "1wk"}
        yf_interval = interval_map.get(interval)
        if not yf_interval:
            raise ValueError(f"unsupported interval: {interval}")
        t = yf.Ticker(symbol.upper())
        period = "2y" if interval == "1d" else "5y"
        last_err: Exception | None = None
        df = None
        for attempt in range(3):
            try:
                df = t.history(period=period, interval=yf_interval, auto_adjust=auto_adjust)
                break
            except Exception as e:
                last_err = e
                if "rate" in str(e).lower() or "too many" in str(e).lower():
                    time.sleep(0.8 * (attempt + 1))
                    continue
                raise
        if df is None or df.empty:
            raise RuntimeError(f"US bars failed for {symbol}: {last_err}")
        df = df.tail(limit)
        bars: list[BarDTO] = []
        for idx, r in df.iterrows():
            ts = idx.strftime("%Y-%m-%d")
            bars.append(
                BarDTO(
                    ts=ts,
                    open=float(r["Open"]),
                    high=float(r["High"]),
                    low=float(r["Low"]),
                    close=float(r["Close"]),
                    volume=int(r["Volume"]) if "Volume" in r else 0,
                    finalized=True,
                )
            )
        if bars:
            bars[-1].finalized = False
        return bars
