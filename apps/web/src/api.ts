const BASE = '/api/v1'

export type ApiError = { code: string; message: string; current_price?: number; expected_price?: number; drift?: number }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = data as ApiError
    throw Object.assign(new Error(err.message || res.statusText), err)
  }
  return data as T
}

export const api = {
  health: () => request<{ ok: boolean }>('/health'),
  listAccounts: () => request<Account[]>('/accounts'),
  createAccount: (body: {
    name: string
    currency?: 'CNY' | 'USD'
    base_currency?: 'CNY' | 'USD'
    initial_cash_cny?: number
    initial_cash_usd?: number
    initial_cash?: number
  }) => request<Account>('/accounts', { method: 'POST', body: JSON.stringify(body) }),
  summary: (id: number) => request<AccountSummary>(`/accounts/${id}/summary`),
  cashFlow: (
    id: number,
    body: { type: 'deposit' | 'withdraw'; amount: number; currency?: 'CNY' | 'USD'; note?: string },
  ) => request<Account>(`/accounts/${id}/cash-flows`, { method: 'POST', body: JSON.stringify(body) }),
  listCashFlows: (id: number) => request<CashFlowRow[]>(`/accounts/${id}/cash-flows`),
  equityCurve: (id: number, rebuild = false) =>
    request<EquityPoint[]>(`/accounts/${id}/equity-curve${rebuild ? '?rebuild=true' : ''}`),
  feeRules: () => request<FeeRuleRow[]>('/fee-rules'),
  fxExchange: (
    id: number,
    body: {
      from_currency: 'CNY' | 'USD'
      to_currency: 'CNY' | 'USD'
      from_amount: number
      rate?: number
      note?: string
    },
  ) => request<FxResult>(`/accounts/${id}/fx`, { method: 'POST', body: JSON.stringify(body) }),
  fxRate: (from_currency: string, to_currency: string) =>
    request<{ from_currency: string; to_currency: string; rate: number; source: string }>(
      `/fx/rate?from_currency=${from_currency}&to_currency=${to_currency}`,
    ),
  positions: (id: number) => request<Position[]>(`/accounts/${id}/positions`),
  orders: (id: number) => request<OrderRow[]>(`/accounts/${id}/orders`),
  placeOrder: (id: number, body: OrderBody) =>
    request<OrderRow>(`/accounts/${id}/orders`, { method: 'POST', body: JSON.stringify(body) }),
  search: (q: string, params?: { asset_class?: string; theme?: string }) => {
    const sp = new URLSearchParams({ q })
    if (params?.asset_class) sp.set('asset_class', params.asset_class)
    if (params?.theme) sp.set('theme', params.theme)
    return request<Instrument[]>(`/instruments/search?${sp}`)
  },
  instrument: (symbol: string) => request<Instrument>(`/instruments/${encodeURIComponent(symbol)}`),
  quotes: (symbols: string[]) =>
    request<Quote[]>(`/quotes?symbols=${encodeURIComponent(symbols.join(','))}`),
  bars: (symbol: string, interval: '1d' | '1w' = '1d', adjust = 'none') =>
    request<Bar[]>(`/bars/${encodeURIComponent(symbol)}?interval=${interval}&adjust=${adjust}&limit=250`),
  watchlist: () => request<WatchItem[]>('/watchlist'),
  addWatch: (symbol: string) => request('/watchlist', { method: 'POST', body: JSON.stringify({ symbol }) }),
  delWatch: (id: number) => request(`/watchlist/${id}`, { method: 'DELETE' }),
  exportData: () => request<unknown>('/export'),
}

export type Wallets = { CNY?: number; USD?: number; [k: string]: number | undefined }

export type Account = {
  id: number
  name: string
  currency: string
  base_currency?: string
  wallets?: Wallets
  cash_by_currency?: Wallets
  initial_cash: number
  cash_balance: number
  status: string
}

export type AccountSummary = Account & {
  market_value: number | null
  market_value_by_currency?: Wallets | null
  total_equity: number
  net_deposit?: number | null
  total_pnl?: number | null
  return_pct: number | null
  positions_count: number
}

export type EquityPoint = {
  date: string
  total_equity: number
  cash: number
  market_value: number
  currency: string
}

export type CashFlowRow = {
  id: number
  type: string
  currency: string
  amount: number
  note?: string | null
  occurred_at?: string | null
}

export type FeeRuleRow = {
  id: number
  market: string
  market_label: string
  instrument_type: string | null
  buy_commission_rate: number
  buy_min_commission: number
  buy_stamp_tax_rate: number
  sell_commission_rate: number
  sell_min_commission: number
  sell_stamp_tax_rate: number
}

export type TradeMarker = {
  time: string
  side: 'buy' | 'sell'
  price?: number
}

export type FxResult = {
  id: number
  from_currency: string
  to_currency: string
  from_amount: number
  to_amount: number
  rate: number
  rate_source: string
  account: Account
}

export type Instrument = {
  symbol: string
  ticker: string
  name: string
  currency: string
  market: string
  asset_class: string
  instrument_type: string
  lot_size: number
  tick_size: number
  theme?: string | null
}

export type Quote = {
  symbol: string
  price: number | null
  change: number | null
  change_pct: number | null
  as_of: string | null
  stale: boolean
  session: string
}

export type Bar = {
  ts: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  finalized: boolean
}

export type Position = {
  symbol: string
  name: string
  qty: number
  avg_cost: number
  price: number | null
  stale: boolean
  market_value: number | null
  unrealized_pnl: number | null
  unrealized_pct: number | null
  currency?: string | null
}

export type OrderRow = {
  id: number
  client_order_id: string
  symbol: string
  side: string
  qty: number
  fill_price: number
  fee: number
  price_source: string
  note?: string | null
  filled_at?: string | null
}

export type OrderBody = {
  client_order_id: string
  symbol: string
  side: 'buy' | 'sell'
  qty: number
  manual_price?: number | null
  expected_price?: number | null
  confirm_price_moved?: boolean
  note?: string
  emotion_tag?: string
}

export type WatchItem = {
  id: number
  symbol: string
  name?: string
  currency?: string
  market?: string
  asset_class?: string
  theme?: string | null
}
