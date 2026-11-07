import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, type Instrument } from '../api'
import { MarketTabs } from '../components/MarketTabs'
import {
  MARKETS,
  classifyMarket,
  marketLabel,
  marketPlaceholder,
  marketSearchParams,
  type MarketKey,
} from '../lib/markets'
import { pct, pnlClass, price as fmtPrice } from '../lib/format'

export function Markets() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as MarketKey) || 'cn'
  const market = MARKETS.find((m) => m.key === tab) || MARKETS[0]

  const [q, setQ] = useState('')
  const [results, setResults] = useState<Instrument[]>([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)

  const [custCode, setCustCode] = useState('HOUSE1')
  const [custName, setCustName] = useState('自住房')
  const [custPrice, setCustPrice] = useState(3000000)
  const [custCcy, setCustCcy] = useState<'CNY' | 'USD' | 'HKD'>('CNY')
  const [custMsg, setCustMsg] = useState<string | null>(null)

  const { data: list = [] } = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist })

  const filtered = useMemo(
    () => list.filter((item) => classifyMarket(item) === tab),
    [list, tab],
  )

  const counts = useMemo(() => {
    const c: Partial<Record<MarketKey, number>> = {}
    for (const m of MARKETS) c[m.key] = 0
    for (const item of list) c[classifyMarket(item)] = (c[classifyMarket(item)] || 0) + 1
    return c
  }, [list])

  const symbols = filtered.map((i) => i.symbol)
  const { data: quotes = [] } = useQuery({
    queryKey: ['quotes', tab, symbols.join(',')],
    queryFn: () => api.quotes(symbols),
    enabled: symbols.length > 0,
    refetchInterval: 60_000,
  })
  const quoteMap = Object.fromEntries(quotes.map((x) => [x.symbol, x]))

  const add = useMutation({
    mutationFn: (symbol: string) => api.addWatch(symbol),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  })
  const del = useMutation({
    mutationFn: (id: number) => api.delWatch(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  })
  const createCustom = useMutation({
    mutationFn: () =>
      api.createCustom({
        code: custCode,
        name: custName,
        currency: custCcy,
        price: custPrice,
      }),
    onSuccess: async (r) => {
      setCustMsg(`已创建 ${r.symbol}`)
      await add.mutateAsync(r.symbol)
      setResults([r as Instrument])
    },
    onError: (e: Error) => setCustMsg(e.message),
  })

  useEffect(() => {
    setResults([])
    setSearchError(null)
    setCustMsg(null)
    setQ('')
  }, [tab])

  const setTab = (k: MarketKey) => {
    setParams({ tab: k })
  }

  const runSearch = async (keyword = q) => {
    setSearching(true)
    setSearchError(null)
    try {
      const sp = marketSearchParams(tab)
      const r = keyword.trim()
        ? await api.search(keyword.trim(), tab === 'cn' ? undefined : sp)
        : await api.search('', sp)
      const scoped = r.filter((i) => classifyMarket(i) === tab)
      setResults(scoped.length ? scoped : r)
      if (!(scoped.length || r.length)) setSearchError('没有搜到结果')
    } catch (e) {
      setSearchError((e as Error).message || '搜索失败')
      setResults([])
    } finally {
      setSearching(false)
    }
  }

  const showHot = tab === 'gold' || tab === 'fund' || tab === 'hk' || tab === 'futures' || tab === 'crypto'

  return (
    <>
      <div className="page-head">
        <h1>行情</h1>
      </div>

      <MarketTabs value={tab} onChange={setTab} counts={counts} />

      <section className="surface">
        <div className="search-bar">
          <input
            placeholder={marketPlaceholder(tab)}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runSearch()}
          />
          <button className="btn-primary" onClick={() => runSearch()} disabled={searching}>
            {searching ? '搜索中…' : '搜索'}
          </button>
          {showHot && (
            <button className="ghost" onClick={() => runSearch('')} disabled={searching}>
              热门{market.label}
            </button>
          )}
        </div>
        {searchError && <p className="warn">{searchError}</p>}

        {tab === 'custom' && (
          <div className="form-grid form-grid-2" style={{ marginBottom: 20 }}>
            <label>
              代码
              <input value={custCode} onChange={(e) => setCustCode(e.target.value)} placeholder="HOUSE1" />
            </label>
            <label>
              名称
              <input value={custName} onChange={(e) => setCustName(e.target.value)} placeholder="自住房" />
            </label>
            <label>
              估值
              <input
                type="number"
                value={custPrice}
                onChange={(e) => setCustPrice(Number(e.target.value))}
              />
            </label>
            <label>
              币种
              <select value={custCcy} onChange={(e) => setCustCcy(e.target.value as 'CNY' | 'USD' | 'HKD')}>
                <option value="CNY">CNY</option>
                <option value="USD">USD</option>
                <option value="HKD">HKD</option>
              </select>
            </label>
            <div className="form-actions" style={{ gridColumn: '1 / -1', marginTop: 0 }}>
              <button className="btn-primary" onClick={() => createCustom.mutate()} disabled={createCustom.isPending}>
                创建/更新自定义资产
              </button>
              {custMsg && <span className="muted">{custMsg}</span>}
            </div>
            <p className="muted" style={{ gridColumn: '1 / -1', margin: 0 }}>
              房产、私募份额等无公开行情的标的：手填估值后按「份数 × 估值」计入权益。
            </p>
          </div>
        )}

        {!!results.length && (
          <div className="quote-list" style={{ marginBottom: 20 }}>
            {results.map((r) => (
              <InstrumentRow
                key={r.symbol}
                name={r.name}
                symbol={r.symbol}
                market={classifyMarket(r)}
                actions={
                  <>
                    <button onClick={() => add.mutate(r.symbol)}>加关注</button>
                    <Link className="btn btn-primary" to={`/trade/${encodeURIComponent(r.symbol)}`}>
                      交易
                    </Link>
                  </>
                }
              />
            ))}
          </div>
        )}

        <div className="row between" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: '1.2rem' }}>
            我的{market.label}关注
          </h2>
        </div>

        {!filtered.length && <div className="empty">暂无关注</div>}

        <div className="quote-list">
          {filtered.map((item) => {
            const qt = quoteMap[item.symbol]
            return (
              <InstrumentRow
                key={item.id}
                name={item.name || item.symbol}
                symbol={item.symbol}
                market={classifyMarket(item)}
                price={qt?.price ?? undefined}
                changePct={qt?.change_pct ?? undefined}
                stale={qt?.stale}
                actions={
                  <>
                    <Link className="btn btn-primary" to={`/trade/${encodeURIComponent(item.symbol)}`}>
                      交易
                    </Link>
                    <button className="ghost" onClick={() => del.mutate(item.id)}>
                      移除
                    </button>
                  </>
                }
              />
            )
          })}
        </div>
      </section>
    </>
  )
}

function InstrumentRow({
  name,
  symbol,
  market,
  price,
  changePct,
  stale,
  actions,
}: {
  name: string
  symbol: string
  market: MarketKey
  price?: number
  changePct?: number
  stale?: boolean
  actions: ReactNode
}) {
  return (
    <div className="quote-row">
      <div className="quote-main">
        <div className="quote-name">
          <strong>{name}</strong>
          <span className={`pill ${market}`}>{marketLabel(market)}</span>
        </div>
        <div className="quote-symbol">{symbol}</div>
      </div>
      <div className={`quote-price ${pnlClass(changePct)}`}>
        {price != null ? fmtPrice(price) : '—'}
        {changePct != null && <div style={{ fontSize: '0.85rem' }}>{pct(changePct)}</div>}
        {stale && price != null && (
          <div className="muted" style={{ fontSize: '0.75rem' }}>
            可能过期
          </div>
        )}
      </div>
      <div className="quote-actions">{actions}</div>
    </div>
  )
}
