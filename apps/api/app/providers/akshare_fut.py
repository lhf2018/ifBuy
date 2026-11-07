"""CN commodity futures continuous contracts via AKShare. Symbols: AU0.FUT"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.providers.base import BarDTO, InstrumentDraft, QuoteDTO

_SYMBOL_RE = re.compile(r"^([A-Z]{1,3}0)\.FUT$", re.I)

# sina continuous contract codes
FUT_PRESETS: dict[str, str] = {
    "AU0": "沪金主连",
    "AG0": "沪银主连",
    "CU0": "沪铜主连",
    "AL0": "沪铝主连",
    "RB0": "螺纹钢主连",
    "I0": "铁矿石主连",
    "SC0": "原油主连",
    "M0": "豆粕主连",
    "Y0": "豆油主连",
    "CF0": "棉花主连",
}


def _parse(symbol: str) -> str:
    m = _SYMBOL_RE.match(symbol.upper())
    if not m:
        raise ValueError(f"invalid futures symbol: {symbol}")
    return m.group(1).upper()


def _draft(code: str, name: str) -> InstrumentDraft:
    code = code.upper()
    return InstrumentDraft(
        symbol=f"{code}.FUT",
        ticker=code,
        name=name or code,
        instrument_type="future",
        asset_class="commodity",
        market="CN",
        currency="CNY",
        lot_size=1,
        tick_size=0.01,
        theme="commodity",
        provider="akshare_fut",
    )


def fut_presets() -> list[InstrumentDraft]:
    return [_draft(c, n) for c, n in FUT_PRESETS.items()]


class AkshareFutProvider:
    name = "akshare_fut"

    def search(self, keyword: str) -> list[InstrumentDraft]:
        keyword = keyword.strip()
        if not keyword:
            return fut_presets()
        out: list[InstrumentDraft] = []
        m = re.fullmatch(r"([A-Za-z]{1,3}0)(?:\.FUT)?", keyword)
        if m:
            code = m.group(1).upper()
            out.append(_draft(code, FUT_PRESETS.get(code, code)))
            return out
        kw = keyword.lower()
        for code, name in FUT_PRESETS.items():
            if kw in name.lower() or kw in code.lower():
                out.append(_draft(code, name))
        return out

    def get_quote(self, symbol: str) -> QuoteDTO:
        bars = self.get_bars(symbol, "1d", "none", 3)
        if not bars:
            raise RuntimeError(f"no futures bars for {symbol}")
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
            session="closed",
            stale=True,
            provider=self.name,
        )

    def get_bars(self, symbol: str, interval: str, adjust: str, limit: int) -> list[BarDTO]:
        import akshare as ak

        code = _parse(symbol)
        df = ak.futures_main_sina(symbol=code)
        if df is None or df.empty:
            return []
        # columns: 日期 开盘价 最高价 最低价 收盘价 成交量 ...
        rows = df.tail(max(limit * 6, limit) if interval == "1w" else limit)
        daily: list[BarDTO] = []
        for _, r in rows.iterrows():
            daily.append(
                BarDTO(
                    ts=str(r["日期"])[:10],
                    open=float(r["开盘价"]),
                    high=float(r["最高价"]),
                    low=float(r["最低价"]),
                    close=float(r["收盘价"]),
                    volume=int(r["成交量"]) if "成交量" in r and r["成交量"] == r["成交量"] else 0,
                    finalized=True,
                )
            )
        if interval == "1w":
            by_week: dict[str, BarDTO] = {}
            for b in daily:
                key = datetime.fromisoformat(b.ts).strftime("%G-W%V")
                by_week[key] = b
            bars = list(by_week.values())[-limit:]
        else:
            bars = daily[-limit:]
        if bars:
            bars[-1].finalized = False
        return bars
