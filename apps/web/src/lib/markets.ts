export type MarketKey = 'cn' | 'us' | 'gold'

export const MARKETS: {
  key: MarketKey
  label: string
  en: string
  hint: string
  currency: 'CNY' | 'USD' | 'BOTH'
}[] = [
  { key: 'cn', label: 'A股', en: 'China', hint: '', currency: 'CNY' },
  { key: 'us', label: '美股', en: 'US', hint: '', currency: 'USD' },
  { key: 'gold', label: '黄金', en: 'Gold', hint: '', currency: 'BOTH' },
]

export function classifyMarket(item: {
  asset_class?: string | null
  theme?: string | null
  market?: string | null
  symbol?: string
}): MarketKey {
  if (item.asset_class === 'gold' || item.theme === 'gold') return 'gold'
  if (item.market === 'US' || item.asset_class === 'equity_us') return 'us'
  if (item.market === 'CN' || item.asset_class === 'equity_cn') return 'cn'
  const s = (item.symbol || '').toUpperCase()
  if (/^\d{6}\.(SH|SZ|BJ)$/.test(s)) return 'cn'
  if (/^[A-Z][A-Z0-9.-]{0,10}$/.test(s)) return 'us'
  return 'cn'
}

export function marketSearchParams(key: MarketKey): { asset_class?: string; theme?: string } {
  if (key === 'gold') return { asset_class: 'gold', theme: 'gold' }
  if (key === 'us') return { asset_class: 'equity_us' }
  return { asset_class: 'equity_cn' }
}

export function marketPlaceholder(key: MarketKey): string {
  if (key === 'cn') return '搜 A 股代码或名称，如 600519 / 贵州茅台'
  if (key === 'us') return '搜美股代码，如 AAPL / TSLA'
  return '搜黄金相关，或点下方热门'
}
