"""Open-end CN mutual funds via AKShare (NAV-based). Symbols: XXXXXX.OF"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache

from app.providers.base import BarDTO, InstrumentDraft, QuoteDTO

_SYMBOL_RE = re.compile(r"^(\d{6})\.OF$", re.I)

# Popular paper-trading presets (open-end funds)
FUND_PRESETS: dict[str, str] = {
    "000001": "华夏成长混合",
    "110011": "易方达优质精选混合",
    "110022": "易方达消费行业股票",
    "005827": "易方达蓝筹精选混合",
    "161725": "招商中证白酒指数(LOF)",
    "163406": "兴全合润混合",
    "519736": "交银优势行业混合",
    "001718": "工银物流产业股票",
    "000248": "汇添富中证主要消费ETF联接A",
    "100032": "富国中证红利指数增强",
}

_NAME_DF = None


def _parse(symbol: str) -> str:
    m = _SYMBOL_RE.match(symbol.upper())
    if not m:
        raise ValueError(f"invalid fund symbol: {symbol}")
    return m.group(1)


def _draft(code: str, name: str) -> InstrumentDraft:
    return InstrumentDraft(
        symbol=f"{code}.OF",
        ticker=code,
        name=name or code,
        instrument_type="fund",
        asset_class="fund_cn",
        market="CN",
        currency="CNY",
        lot_size=1,
        tick_size=0.0001,
        theme=None,
        provider="akshare_fund",
    )


def _load_names():
    global _NAME_DF
    if _NAME_DF is not None:
        return _NAME_DF
    import akshare as ak

    _NAME_DF = ak.fund_name_em()
    return _NAME_DF


def fund_presets() -> list[InstrumentDraft]:
    return [_draft(code, name) for code, name in FUND_PRESETS.items()]


class AkshareFundProvider:
    name = "akshare_fund"

    def search(self, keyword: str) -> list[InstrumentDraft]:
        keyword = keyword.strip()
        if not keyword:
            return fund_presets()

        out: list[InstrumentDraft] = []
        m = re.fullmatch(r"(\d{6})(?:\.OF)?", keyword, re.I)
        if m:
            code = m.group(1)
            name = FUND_PRESETS.get(code, code)
            try:
                df = _load_names()
                hit = df[df["基金代码"].astype(str).str.zfill(6) == code]
                if not hit.empty:
                    name = str(hit.iloc[0]["基金简称"])
            except Exception:
                pass
            out.append(_draft(code, name))
            return out

        try:
            df = _load_names()
            kw = keyword.lower()
            hits = df[
                df["基金代码"].astype(str).str.contains(keyword)
                | df["基金简称"].astype(str).str.lower().str.contains(kw)
                | df["拼音缩写"].astype(str).str.lower().str.contains(kw)
            ]
            for _, row in hits.head(25).iterrows():
                code = str(row["基金代码"]).zfill(6)
                out.append(_draft(code, str(row["基金简称"])))
        except Exception:
            # offline fallback: filter presets by name/code
            for code, name in FUND_PRESETS.items():
                if keyword in code or keyword.lower() in name.lower():
                    out.append(_draft(code, name))

        seen: set[str] = set()
        uniq: list[InstrumentDraft] = []
        for i in out:
            if i.symbol in seen:
                continue
            seen.add(i.symbol)
            uniq.append(i)
        return uniq

    def get_quote(self, symbol: str) -> QuoteDTO:
        bars = self.get_bars(symbol, "1d", "none", 3)
        if not bars:
            raise RuntimeError(f"no NAV for {symbol}")
        price = bars[-1].close
        prev = bars[-2].close if len(bars) > 1 else None
        chg = (price - prev) if prev else None
        pct = ((price - prev) / prev * 100) if prev else None
        return QuoteDTO(
            symbol=symbol,
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
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        if df is None or df.empty:
            return []

        rows = df.tail(max(limit * 6, limit) if interval == "1w" else limit)
        daily: list[BarDTO] = []
        for _, r in rows.iterrows():
            nav = float(r["单位净值"])
            daily.append(
                BarDTO(
                    ts=str(r["净值日期"])[:10],
                    open=nav,
                    high=nav,
                    low=nav,
                    close=nav,
                    volume=0,
                    finalized=True,
                )
            )

        if interval == "1d":
            bars = daily[-limit:]
        elif interval == "1w":
            # one point per calendar week (last NAV of that week)
            by_week: dict[str, BarDTO] = {}
            for b in daily:
                key = datetime.fromisoformat(b.ts).strftime("%G-W%V")
                by_week[key] = b
            bars = list(by_week.values())[-limit:]
        else:
            raise ValueError(f"unsupported interval: {interval}")

        if bars:
            bars[-1].finalized = False
        return bars


@lru_cache(maxsize=1)
def get_fund_provider() -> AkshareFundProvider:
    return AkshareFundProvider()
