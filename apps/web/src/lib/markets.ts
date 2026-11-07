export type MarketKey = 'cn' | 'us' | 'hk' | 'fund' | 'gold' | 'futures' | 'crypto' | 'custom'

export const MARKETS: {
  key: MarketKey
  label: string
  en: string
  hint: string
  currency: 'CNY' | 'USD' | 'HKD' | 'BOTH'
}[] = [
  { key: 'cn', label: 'A股', en: 'China', hint: '', currency: 'CNY' },
  { key: 'hk', label: '港股', en: 'HK', hint: '', currency: 'HKD' },
  { key: 'us', label: '美股', en: 'US', hint: '', currency: 'USD' },
  { key: 'fund', label: '基金', en: 'Fund', hint: '', currency: 'CNY' },
  { key: 'futures', label: '期货', en: 'Futures', hint: '', currency: 'CNY' },
  { key: 'crypto', label: '加密', en: 'Crypto', hint: '', currency: 'USD' },
  { key: 'gold', label: '黄金', en: 'Gold', hint: '', currency: 'BOTH' },
  { key: 'custom', label: '自定义', en: 'Custom', hint: '房产等', currency: 'BOTH' },
]

export function marketLabel(key: MarketKey): string {
  return MARKETS.find((m) => m.key === key)?.label || key
}

const GOLD_SYMBOLS = /^(GLD|IAU|SGOL|518880\.SH|159934\.SZ|518800\.SH|518850\.SH|159937\.SZ)$/i

export function classifyMarket(item: {
  asset_class?: string | null
  theme?: string | null
  market?: string | null
  instrument_type?: string | null
  name?: string | null
  symbol?: string
}): MarketKey {
  if (item.asset_class === 'custom' || item.instrument_type === 'custom') return 'custom'
  if (item.asset_class === 'crypto' || item.instrument_type === 'crypto') return 'crypto'
  if (item.asset_class === 'commodity' || item.instrument_type === 'future') return 'futures'
  if (item.asset_class === 'fund_cn' || item.instrument_type === 'fund') return 'fund'
  if (item.asset_class === 'gold' || item.theme === 'gold') return 'gold'
  if (item.asset_class === 'equity_hk' || item.market === 'HK') return 'hk'
  if (item.market === 'US' || item.asset_class === 'equity_us') return 'us'
  if (item.market === 'CN' || item.asset_class === 'equity_cn') return 'cn'
  const s = (item.symbol || '').toUpperCase()
  const name = item.name || ''
  if (s.startsWith('CUST.')) return 'custom'
  if (/-USD$/.test(s)) return 'crypto'
  if (/\.FUT$/.test(s)) return 'futures'
  if (/\.OF$/.test(s)) return 'fund'
  if (GOLD_SYMBOLS.test(s) || /黄金/.test(name)) return 'gold'
  if (/\.HK$/.test(s)) return 'hk'
  if (/^\d{6}\.(SH|SZ|BJ)$/.test(s)) return 'cn'
  if (/^[A-Z][A-Z0-9.-]{0,10}$/.test(s)) return 'us'
  return 'cn'
}

export function marketSearchParams(key: MarketKey): { asset_class?: string; theme?: string } {
  if (key === 'gold') return { asset_class: 'gold', theme: 'gold' }
  if (key === 'us') return { asset_class: 'equity_us' }
  if (key === 'hk') return { asset_class: 'equity_hk' }
  if (key === 'fund') return { asset_class: 'fund_cn' }
  if (key === 'futures') return { asset_class: 'commodity' }
  if (key === 'crypto') return { asset_class: 'crypto' }
  if (key === 'custom') return { asset_class: 'custom' }
  return { asset_class: 'equity_cn' }
}

export function marketPlaceholder(key: MarketKey): string {
  if (key === 'cn') return '搜 A 股代码或名称，如 600519 / 贵州茅台'
  if (key === 'hk') return '搜港股，如 00700 / 腾讯'
  if (key === 'us') return '搜美股代码，如 AAPL / TSLA'
  if (key === 'fund') return '搜基金代码或名称，如 110022 / 易方达消费'
  if (key === 'futures') return '搜期货，如 AU0 / 沪金'
  if (key === 'crypto') return '搜加密货币，如 BTC / ETH'
  if (key === 'custom') return '搜已创建的自定义资产，或下方新建'
  return '搜黄金相关，或点下方热门'
}
