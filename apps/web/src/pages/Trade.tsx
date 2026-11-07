import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { api, type ApiError, type TradeMarker } from '../api'
import { useAccount } from '../account'
import { KlineChart } from '../components/KlineChart'
import { classifyMarket, marketLabel } from '../lib/markets'
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
  const [divPerShare, setDivPerShare] = useState(0.1)
  const [splitNum, setSplitNum] = useState(2)
  const [splitDen, setSplitDen] = useState(1)
  const [manualVal, setManualVal] = useState<number | ''>('')
  const [corpMsg, setCorpMsg] = useState<string | null>(null)

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
  const market = instrument
    ? classifyMarket(instrument)
    : classifyMarket({ symbol, instrument_type: symbol.endsWith('.OF') ? 'fund' : undefined })
  const mLabel = marketLabel(market)

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
              <span className={`pill ${market}`}>{mLabel}</span>
              <Link className="muted" to={`/markets?tab=${market}`}>
                ← 返回{mLabel}
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
              {market === 'fund' ? '净值' : '价格'}{' '}
              {synced ? (market === 'fund' ? '· 跟随最新净值' : '· 跟随最新价') : '· 手填'}
              <input
                type="number"
                step={market === 'fund' ? '0.0001' : '0.01'}
                value={price}
                onChange={(e) => {
                  setSynced(false)
                  setPrice(e.target.value === '' ? '' : Number(e.target.value))
                }}
              />
            </label>
            {!synced && (
              <button className="ghost" onClick={() => setSynced(true)}>
                {market === 'fund' ? '恢复最新净值' : '恢复最新价'}
              </button>
            )}
            <label>
              {market === 'fund' ? '份额' : '数量'}
              <input type="number" value={qty} onChange={(e) => setQty(Number(e.target.value))} />
            </label>
            <label>
              为啥买/卖（可选）
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="一句话记下理由" />
            </label>

            <p className="muted">
              可用 {tradeCcy} {availableCash != null ? money(availableCash, tradeCcy) : '—'}
              {' · '}
              可卖 {pos?.sellable_qty ?? pos?.qty ?? 0}
              {pos?.t1 && (pos.locked_qty || 0) > 0
                ? `（持仓 ${pos.qty}，T+1 锁定 ${pos.locked_qty}）`
                : ''}
            </p>
            {market === 'hk' && accountId != null && <HkConnectHint accountId={accountId} />}

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

      {pos && accountId && market !== 'custom' && (
        <section className="surface mt">
          <h2 className="section-title">分红 / 拆股</h2>
          <div className="form-grid form-grid-2">
            <label>
              每股分红（现金）
              <input
                type="number"
                step="0.0001"
                value={divPerShare}
                onChange={(e) => setDivPerShare(Number(e.target.value))}
              />
            </label>
            <div className="form-actions" style={{ marginTop: 0, alignItems: 'end' }}>
              <button
                className="btn-primary"
                disabled={!accountId}
                onClick={async () => {
                  try {
                    const r = await api.dividend(accountId, {
                      symbol,
                      cash_per_share: divPerShare,
                    })
                    setCorpMsg(r.note || '分红已入账')
                    refreshAccounts()
                    qc.invalidateQueries({ queryKey: ['summary', accountId] })
                    qc.invalidateQueries({ queryKey: ['positions', accountId] })
                  } catch (e) {
                    setCorpMsg((e as Error).message)
                  }
                }}
              >
                登记分红
              </button>
            </div>
            <label>
              拆股（新:旧）
              <div className="row">
                <input type="number" value={splitNum} onChange={(e) => setSplitNum(Number(e.target.value))} />
                <span>:</span>
                <input type="number" value={splitDen} onChange={(e) => setSplitDen(Number(e.target.value))} />
              </div>
            </label>
            <div className="form-actions" style={{ marginTop: 0, alignItems: 'end' }}>
              <button
                onClick={async () => {
                  try {
                    const r = await api.split(accountId, {
                      symbol,
                      ratio_num: splitNum,
                      ratio_den: splitDen,
                    })
                    setCorpMsg(r.note || '拆股已调整')
                    qc.invalidateQueries({ queryKey: ['positions', accountId] })
                    qc.invalidateQueries({ queryKey: ['summary', accountId] })
                  } catch (e) {
                    setCorpMsg((e as Error).message)
                  }
                }}
              >
                登记拆股
              </button>
            </div>
          </div>
          {corpMsg && <p className="muted mt">{corpMsg}</p>}
        </section>
      )}

      {market === 'custom' && accountId && (
        <section className="surface mt">
          <h2 className="section-title">更新估值</h2>
          <div className="form-stack">
            <label>
              当前估值 / 单价
              <input
                type="number"
                value={manualVal === '' ? quote?.price ?? '' : manualVal}
                onChange={(e) => setManualVal(e.target.value === '' ? '' : Number(e.target.value))}
              />
            </label>
            <button
              className="btn-primary"
              onClick={async () => {
                const px = typeof manualVal === 'number' ? manualVal : Number(quote?.price)
                try {
                  await api.setCustomPrice(symbol, { price: px })
                  setCorpMsg(`估值已更新为 ${px}`)
                  qc.invalidateQueries({ queryKey: ['quote', symbol] })
                  qc.invalidateQueries({ queryKey: ['positions', accountId] })
                  qc.invalidateQueries({ queryKey: ['summary', accountId] })
                } catch (e) {
                  setCorpMsg((e as Error).message)
                }
              }}
            >
              保存估值
            </button>
            {corpMsg && <p className="muted">{corpMsg}</p>}
          </div>
        </section>
      )}
    </>
  )
}

function HkConnectHint({ accountId }: { accountId: number }) {
  const { data } = useQuery({
    queryKey: ['account-settings', accountId],
    queryFn: () => api.accountSettings(accountId),
  })
  const hk = data?.hk_connect
  if (!hk) return null
  return (
    <p className="muted" style={{ margin: 0 }}>
      港股通今日额度剩余 ¥{Math.round(hk.remaining_cny).toLocaleString()} / ¥
      {Math.round(hk.quota_cny).toLocaleString()}
      {hk.exhausted ? ' · 已用尽' : ''}
    </p>
  )
}
