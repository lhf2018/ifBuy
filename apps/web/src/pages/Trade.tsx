import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { api, type ApiError, type TradeMarker } from '../api'
import { useAccount } from '../account'
import { KlineChart } from '../components/KlineChart'
import { classifyMarket } from '../lib/markets'
import { money, pct, pnlClass, price as fmtPrice } from '../lib/format'

export function Trade() {
  const { symbol: raw } = useParams()
  const symbol = decodeURIComponent(raw || '')
  const { accountId, account, refreshAccounts } = useAccount()
  const qc = useQueryClient()
  const [interval, setInterval] = useState<'1d' | '1w'>('1d')
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [qty, setQty] = useState(100)
  const [price, setPrice] = useState<number | ''>('')
  const [synced, setSynced] = useState(true)
  const [note, setNote] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const { data: instrument } = useQuery({
    queryKey: ['instrument', symbol],
    queryFn: () => api.instrument(symbol),
    enabled: !!symbol,
  })
  const { data: quotes } = useQuery({
    queryKey: ['quote', symbol],
    queryFn: () => api.quotes([symbol]),
    enabled: !!symbol,
    refetchInterval: 10_000,
  })
  const quote = quotes?.[0]
  const { data: bars = [] } = useQuery({
    queryKey: ['bars', symbol, interval],
    queryFn: () => api.bars(symbol, interval, 'none'),
    enabled: !!symbol,
  })
  const { data: positions = [] } = useQuery({
    queryKey: ['positions', accountId],
    queryFn: () => api.positions(accountId!),
    enabled: !!accountId,
  })
  const { data: orders = [] } = useQuery({
    queryKey: ['orders', accountId],
    queryFn: () => api.orders(accountId!),
    enabled: !!accountId && !!symbol,
  })
  const pos = positions.find((p) => p.symbol === symbol)
  const tradeMarkers: TradeMarker[] = useMemo(
    () =>
      orders
        .filter((o) => o.symbol === symbol && o.filled_at)
        .map((o) => ({
          time: o.filled_at!,
          side: o.side as 'buy' | 'sell',
          price: o.fill_price,
        })),
    [orders, symbol],
  )
  const market = instrument ? classifyMarket(instrument) : classifyMarket({ symbol })
  const marketLabel = market === 'cn' ? 'A股' : market === 'us' ? '美股' : '黄金'

  useEffect(() => {
    if (synced && quote?.price != null) setPrice(quote.price)
  }, [quote?.price, synced])

  useEffect(() => {
    if (instrument?.lot_size) setQty(instrument.lot_size)
  }, [instrument?.symbol])

  const tradeCcy = instrument?.currency || 'CNY'
  const wallets = account?.wallets || account?.cash_by_currency || {}
  const availableCash = wallets[tradeCcy] ?? (account?.currency === tradeCcy ? account?.cash_balance : 0)

  const submitOrder = async (confirmMoved: boolean) => {
    if (!accountId) throw new Error('请先创建账本')
    return api.placeOrder(accountId, {
      client_order_id: crypto.randomUUID(),
      symbol,
      side,
      qty: Number(qty),
      manual_price: synced ? null : Number(price),
      expected_price: typeof price === 'number' ? price : null,
      confirm_price_moved: confirmMoved,
      note: note || undefined,
    })
  }

  const orderMut = useMutation({
    mutationFn: () => submitOrder(false),
    onSuccess: (r) => {
      setMsg(`${r.side === 'buy' ? '买入' : '卖出'} ${r.qty} · ${r.fill_price} · 费用 ${r.fee}`)
      setErr(null)
      qc.invalidateQueries({ queryKey: ['positions', accountId] })
      qc.invalidateQueries({ queryKey: ['summary', accountId] })
      qc.invalidateQueries({ queryKey: ['orders', accountId] })
      refreshAccounts()
    },
    onError: async (e: Error & ApiError) => {
      if (e.code === 'PRICE_MOVED') {
        const ok = window.confirm(e.message)
        if (ok) {
          try {
            const r = await submitOrder(true)
            setMsg(`成交 @ ${r.fill_price}`)
            setErr(null)
            qc.invalidateQueries({ queryKey: ['positions', accountId] })
            refreshAccounts()
          } catch (err2) {
            setErr((err2 as Error).message)
          }
        }
        return
      }
      setErr(e.message)
      setMsg(null)
    },
  })

  return (
    <>
      {!accountId && (
        <section className="surface" style={{ marginBottom: 18 }}>
          <p className="muted" style={{ margin: 0 }}>
            请先到 <Link to="/">账本</Link> 创建。
          </p>
        </section>
      )}
      <div className="trade-head surface">
        <div className="row between">
          <div>
            <div className="row" style={{ marginBottom: 8 }}>
              <span className={`pill ${market}`}>{marketLabel}</span>
              <Link className="muted" to={`/markets?tab=${market}`}>
                ← 返回{marketLabel}
              </Link>
            </div>
            <h1>
              {instrument?.name || symbol} <span className="muted" style={{ fontSize: '0.55em' }}>{symbol}</span>
            </h1>
            <div className="hero-equity" style={{ fontSize: 'clamp(2.2rem, 4vw, 3rem)' }}>
              <span className={pnlClass(quote?.change_pct)}>{fmtPrice(quote?.price)}</span>
              {quote?.change_pct != null && (
                <span className={`pct-tag ${pnlClass(quote.change_pct)}`}>{pct(quote.change_pct)}</span>
              )}
            </div>
            <div className="muted">
              更新于 {quote?.as_of ? new Date(quote.as_of).toLocaleString() : '—'}
              {quote?.stale ? ' · 价格可能过期' : ''}
            </div>
          </div>
        </div>
      </div>

      <div className="trade-layout">
        <section className="surface">
          <div className="segment">
            <button className={interval === '1d' ? 'active' : ''} onClick={() => setInterval('1d')}>
              日K
            </button>
            <button className={interval === '1w' ? 'active' : ''} onClick={() => setInterval('1w')}>
              周K
            </button>
          </div>
          <KlineChart bars={bars} lastPrice={quote?.price} markers={tradeMarkers} />
        </section>

        <section className="surface">
          <div className="segment" style={{ width: '100%' }}>
            <button className={`btn-buy ${side === 'buy' ? 'active' : ''}`} style={{ flex: 1 }} onClick={() => setSide('buy')}>
              买入
            </button>
            <button className={`btn-sell ${side === 'sell' ? 'active' : ''}`} style={{ flex: 1 }} onClick={() => setSide('sell')}>
              卖出
            </button>
          </div>

          <div className="form-stack">
            <label>
              价格 {synced ? '· 跟随最新价' : '· 手填'}
              <input
                type="number"
                value={price}
                onChange={(e) => {
                  setSynced(false)
                  setPrice(e.target.value === '' ? '' : Number(e.target.value))
                }}
              />
            </label>
            {!synced && (
              <button className="ghost" onClick={() => setSynced(true)}>
                恢复最新价
              </button>
            )}
            <label>
              数量
              <input type="number" value={qty} onChange={(e) => setQty(Number(e.target.value))} />
            </label>
            <label>
              为啥买/卖（可选）
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="一句话记下理由" />
            </label>

            <p className="muted">
              可用 {tradeCcy} {availableCash != null ? money(availableCash, tradeCcy) : '—'}
              {' '}
              · 可卖{' '}
              {pos?.qty ?? 0}
            </p>

            <button
              className={side === 'buy' ? 'btn-buy primary' : 'btn-sell primary'}
              style={{ width: '100%' }}
              disabled={!accountId || orderMut.isPending}
              onClick={() => orderMut.mutate()}
            >
              确认{side === 'buy' ? '买入' : '卖出'}
            </button>
            {msg && <p className="ok">{msg}</p>}
            {err && <p className="warn">{err}</p>}
          </div>
        </section>
      </div>

      {pos && (
        <section className="surface mt">
          <div className="row between">
            <div>
              <div className="muted">持仓</div>
              <strong>
                {pos.qty} · 成本 {pos.avg_cost}
              </strong>
            </div>
            <div className={`quote-price ${pnlClass(pos.unrealized_pnl)}`}>
              现在赚了 {pos.unrealized_pnl?.toFixed(2) ?? '—'}
              {pos.unrealized_pct != null ? ` (${pct(pos.unrealized_pct)})` : ''}
            </div>
          </div>
        </section>
      )}
    </>
  )
}
