from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache

from app.providers.base import BarDTO, InstrumentDraft, QuoteDTO

_SYMBOL_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$")
_NAME_CACHE: dict[str, str] = {}
_CODE_NAME_DF = None


def _parse_symbol(symbol: str) -> tuple[str, str]:
    m = _SYMBOL_RE.match(symbol.upper())
    if not m:
        raise ValueError(f"invalid CN symbol: {symbol}")
    return m.group(1), m.group(2)


def _suffix_for_code(code: str) -> str:
    if code.startswith(("5", "6", "9")):
        return "SH"
    if code.startswith(("4", "8")):
        return "BJ"
    return "SZ"


def _itype(code: str) -> str:
    return "etf" if code.startswith(("15", "16", "51", "56", "58")) else "equity"


def _draft(code: str, name: str, suffix: str | None = None) -> InstrumentDraft:
    suffix = suffix or _suffix_for_code(code)
    theme = "gold" if ("黄金" in name or "金ETF" in name) else None
    itype = _itype(code)
    return InstrumentDraft(
        symbol=f"{code}.{suffix}",
        ticker=code,
        name=name or code,
        instrument_type=itype,
        asset_class="gold" if theme else "equity_cn",
        market="CN",
        currency="CNY",
        lot_size=100,
        theme=theme,
        provider="akshare",
    )


def _load_code_name():
    global _CODE_NAME_DF
    if _CODE_NAME_DF is not None:
        return _CODE_NAME_DF
    import akshare as ak

    _CODE_NAME_DF = ak.stock_info_a_code_name()
    return _CODE_NAME_DF


def get_cached_name(symbol: str) -> str | None:
    return _NAME_CACHE.get(symbol)


class AkshareCNProvider:
    name = "akshare"

    def search(self, keyword: str) -> list[InstrumentDraft]:
        keyword = keyword.strip()
        out: list[InstrumentDraft] = []

        # Fast path: exact 6-digit code — no network required for listing
        m = re.fullmatch(r"(\d{6})(?:\.(SH|SZ|BJ))?", keyword, re.I)
        if m:
            code = m.group(1)
            suffix = (m.group(2) or _suffix_for_code(code)).upper()
            name = code
            try:
                df = _load_code_name()
                hit = df[df["code"].astype(str).str.zfill(6) == code]
                if not hit.empty:
                    name = str(hit.iloc[0]["name"])
            except Exception:
                pass
            out.append(_draft(code, name, suffix))
            return out

        # Name search
        try:
            df = _load_code_name()
            kw = keyword.lower()
            hits = df[
                df["code"].astype(str).str.contains(keyword)
                | df["name"].astype(str).str.lower().str.contains(kw)
            ]
            for _, row in hits.head(20).iterrows():
                code = str(row["code"]).zfill(6)
                out.append(_draft(code, str(row["name"])))
        except Exception:
            pass

        seen: set[str] = set()
        uniq: list[InstrumentDraft] = []
        for i in out:
            if i.symbol in seen:
                continue
            seen.add(i.symbol)
            uniq.append(i)
        return uniq

    def get_quote(self, symbol: str) -> QuoteDTO:
        import akshare as ak

        code, _ = _parse_symbol(symbol)
        is_etf = _itype(code) == "etf"

        if not is_etf:
            try:
                df = ak.stock_bid_ask_em(symbol=code)
                mapping = {str(r.iloc[0]): r.iloc[1] for _, r in df.iterrows()}
                price = float(mapping.get("最新", mapping.get("最新价", 0)) or 0)
                prev = float(mapping.get("昨收", 0) or 0) or None
                if price:
                    chg = (price - prev) if prev else None
                    pct = ((price - prev) / prev * 100) if prev else None
                    return QuoteDTO(
                        symbol=symbol,
                        price=price,
                        change=chg,
                        change_pct=pct,
                        prev_close=prev,
                        as_of=datetime.now(timezone.utc),
                        session="regular",
                        provider=self.name,
                    )
            except Exception:
                pass

        # ETF / fallback: last daily bar close
        try:
            bars = self.get_bars(symbol, "1d", "none", 2)
            if not bars:
                raise RuntimeError("no bars")
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
        except Exception as e:
            raise RuntimeError(f"CN quote failed for {symbol}: {e}") from e

    def get_bars(self, symbol: str, interval: str, adjust: str, limit: int) -> list[BarDTO]:
        import akshare as ak

        code, _ = _parse_symbol(symbol)
        adjust_map = {"none": "", "forward": "qfq", "backward": "hfq"}
        adj = adjust_map.get(adjust, "")
        is_etf = _itype(code) == "etf"
        df = None

        if is_etf and interval == "1d":
            try:
                df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust=adj)
            except Exception:
                df = None
        elif is_etf and interval == "1w":
            try:
                df = ak.fund_etf_hist_em(symbol=code, period="weekly", adjust=adj)
            except Exception:
                df = None

        if df is None or df.empty:
            if interval == "1d":
                df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust=adj)
            elif interval == "1w":
                df = ak.stock_zh_a_hist(symbol=code, period="weekly", adjust=adj)
            else:
                raise ValueError(f"unsupported interval: {interval}")

        if df is None or df.empty:
            return []
        rows = df.tail(limit)
        bars: list[BarDTO] = []
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
            _NAME_CACHE[symbol] = _NAME_CACHE.get(symbol) or code
        return bars


@lru_cache(maxsize=1)
def get_akshare_provider() -> AkshareCNProvider:
    return AkshareCNProvider()
