"""Hong Kong equities via AKShare. Symbols: 00700.HK"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.providers.base import BarDTO, InstrumentDraft, QuoteDTO

_SYMBOL_RE = re.compile(r"^(\d{1,5})\.HK$", re.I)

HK_PRESETS: dict[str, str] = {
    "00700": "腾讯控股",
    "09988": "阿里巴巴-SW",
    "03690": "美团-W",
    "01810": "小米集团-W",
    "00941": "中国移动",
    "01299": "友邦保险",
    "02318": "中国平安",
    "00388": "香港交易所",
}


def normalize_hk_code(code: str) -> str:
    return code.zfill(5)


def _parse(symbol: str) -> str:
    m = _SYMBOL_RE.match(symbol.upper())
    if not m:
        raise ValueError(f"invalid HK symbol: {symbol}")
    return normalize_hk_code(m.group(1))


def _draft(code: str, name: str) -> InstrumentDraft:
    code = normalize_hk_code(code)
    return InstrumentDraft(
        symbol=f"{code}.HK",
        ticker=code,
        name=name or code,
        instrument_type="equity",
        asset_class="equity_hk",
        market="HK",
        currency="HKD",
        lot_size=100,
        tick_size=0.01,
        provider="akshare_hk",
    )


def hk_presets() -> list[InstrumentDraft]:
    return [_draft(c, n) for c, n in HK_PRESETS.items()]


class AkshareHKProvider:
    name = "akshare_hk"

    def search(self, keyword: str) -> list[InstrumentDraft]:
        keyword = keyword.strip()
        if not keyword:
            return hk_presets()
        out: list[InstrumentDraft] = []
        m = re.fullmatch(r"(\d{1,5})(?:\.HK)?", keyword, re.I)
        if m:
            code = normalize_hk_code(m.group(1))
            out.append(_draft(code, HK_PRESETS.get(code, code)))
            return out
        kw = keyword.lower()
        for code, name in HK_PRESETS.items():
            if kw in name.lower() or kw in code:
                out.append(_draft(code, name))
        return out

    def get_quote(self, symbol: str) -> QuoteDTO:
        bars = self.get_bars(symbol, "1d", "none", 3)
        if not bars:
            raise RuntimeError(f"no HK bars for {symbol}")
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
        adj = "" if adjust == "none" else ("qfq" if adjust == "forward" else "hfq")
        end = datetime.now().strftime("%Y%m%d")
        start = "20180101"
        df = ak.stock_hk_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust=adj)
        if df is None or df.empty:
            return []
        if interval == "1w":
            # resample last close of ISO week
            daily: list[BarDTO] = []
            for _, r in df.iterrows():
                daily.append(
                    BarDTO(
                        ts=str(r["日期"])[:10],
                        open=float(r["开盘"]),
                        high=float(r["最高"]),
                        low=float(r["最低"]),
                        close=float(r["收盘"]),
                        volume=int(r["成交量"]) if "成交量" in r else 0,
                        finalized=True,
                    )
                )
            by_week: dict[str, BarDTO] = {}
            for b in daily:
                key = datetime.fromisoformat(b.ts).strftime("%G-W%V")
                by_week[key] = b
            bars = list(by_week.values())[-limit:]
        else:
            rows = df.tail(limit)
            bars = []
            for _, r in rows.iterrows():
                bars.append(
                    BarDTO(
                        ts=str(r["日期"])[:10],
                        open=float(r["开盘"]),
                        high=float(r["最高"]),
                        low=float(r["最低"]),
                        close=float(r["收盘"]),
                        volume=int(r["成交量"]) if "成交量" in r else 0,
                        finalized=True,
                    )
                )
        if bars:
            bars[-1].finalized = False
        return bars
