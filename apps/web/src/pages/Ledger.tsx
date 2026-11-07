import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useAccount } from '../account'
import { AccountSelect } from '../components/AccountSelect'
import { EquityChart } from '../components/EquityChart'
import { classifyMarket, type MarketKey } from '../lib/markets'
import { money, moneySigned, pct, pnlClass } from '../lib/format'

type Section = 'overview' | 'positions' | 'orders' | 'create'

type PosTab = MarketKey | 'all'

function positionMarket(p: { symbol: string; name: string; currency?: string | null }): MarketKey {
  if (/GLD|IAU|SGOL|518880|159934|518800/i.test(p.symbol) || /黄金/.test(p.name)) return 'gold'
  return classifyMarket({
    symbol: p.symbol,
    market: p.currency === 'USD' ? 'US' : 'CN',
    asset_class: p.currency === 'USD' ? 'equity_us' : 'equity_cn',
  })
}

export function Ledger() {
  const { accountId, accounts, setAccountId, refreshAccounts, account, ready } = useAccount()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const rawTab = params.get('tab')
  const section: Section =
    rawTab === 'positions' || rawTab === 'orders' || rawTab === 'create' || rawTab === 'overview'
      ? rawTab
      : 'overview'
  const setSection = (tab: Section) => {
    if (tab === 'overview') setParams({})
    else setParams({ tab })
  }

  const [name, setName] = useState('账本1')
  const [baseCurrency, setBaseCurrency] = useState<'CNY' | 'USD'>('CNY')
  const [cashCny, setCashCny] = useState(100000)
  const [cashUsd, setCashUsd] = useState(10000)
  const [creating, setCreating] = useState(false)

  const [fxFrom, setFxFrom] = useState<'CNY' | 'USD'>('CNY')
  const [fxTo, setFxTo] = useState<'CNY' | 'USD'>('USD')
  const [fxAmount, setFxAmount] = useState(1000)
  const [fxRate, setFxRate] = useState<number | ''>('')
  const [fxMsg, setFxMsg] = useState<string | null>(null)
  const [fxErr, setFxErr] = useState<string | null>(null)

  const [posTab, setPosTab] = useState<PosTab>('all')
  const [cashType, setCashType] = useState<'deposit' | 'withdraw'>('deposit')
  const [cashCcy, setCashCcy] = useState<'CNY' | 'USD'>('CNY')
  const [cashAmt, setCashAmt] = useState(10000)
  const [cashMsg, setCashMsg] = useState<string | null>(null)
  const [cashErr, setCashErr] = useState<string | null>(null)

  const needsAccount = section !== 'create'
  const { data: summary, refetch } = useQuery({
    queryKey: ['summary', accountId],
    queryFn: () => api.summary(accountId!),
    enabled: !!accountId && needsAccount,
  })

  const { data: rateInfo } = useQuery({
    queryKey: ['fx-rate', fxFrom, fxTo],
    queryFn: () => api.fxRate(fxFrom, fxTo),
    enabled: !!accountId && section === 'overview' && fxFrom !== fxTo,
    refetchInterval: 60_000,
  })

  const { data: equityPoints = [] } = useQuery({
    queryKey: ['equity-curve', accountId],
    queryFn: () => api.equityCurve(accountId!),
    enabled: !!accountId && section === 'overview',
  })

  const { data: positions = [], isLoading: posLoading } = useQuery({
    queryKey: ['positions', accountId],
    queryFn: () => api.positions(accountId!),
    enabled: !!accountId && section === 'positions',
    refetchInterval: 60_000,
  })

  const { data: orders = [] } = useQuery({
    queryKey: ['orders', accountId],
    queryFn: () => api.orders(accountId!),
    enabled: !!accountId && section === 'orders',
  })

  const { data: cashFlows = [] } = useQuery({
    queryKey: ['cash-flows', accountId],
    queryFn: () => api.listCashFlows(accountId!),
    enabled: !!accountId && section === 'orders',
  })

  useEffect(() => {
    if (rateInfo?.rate && fxRate === '') setFxRate(Number(rateInfo.rate.toFixed(6)))
  }, [rateInfo?.rate, fxRate])

  useEffect(() => {
    if (!ready) return
    if (!accounts.length && accountId == null && section !== 'create') setSection('create')
  }, [ready, accounts.length, accountId, section])

  const create = async () => {
    setCreating(true)
    try {
      const a = await api.createAccount({
        name,
        currency: baseCurrency,
        base_currency: baseCurrency,
        initial_cash_cny: cashCny,
        initial_cash_usd: cashUsd,
      })
      await refreshAccounts()
      setAccountId(a.id)
      setSection('overview')
      await refetch()
    } finally {
      setCreating(false)
    }
  }

  const fxMut = useMutation({
    mutationFn: () =>
      api.fxExchange(accountId!, {
        from_currency: fxFrom,
        to_currency: fxTo,
        from_amount: fxAmount,
        rate: typeof fxRate === 'number' ? fxRate : undefined,
      }),
    onSuccess: (r) => {
      setFxMsg(`已换汇：${r.from_amount} ${r.from_currency} → ${r.to_amount} ${r.to_currency}`)
      setFxErr(null)
      refreshAccounts()
      qc.invalidateQueries({ queryKey: ['summary', accountId] })
      qc.invalidateQueries({ queryKey: ['equity-curve', accountId] })
      qc.invalidateQueries({ queryKey: ['cash-flows', accountId] })
    },
    onError: (e: Error) => {
      setFxErr(e.message)
      setFxMsg(null)
    },
  })

  const cashMut = useMutation({
    mutationFn: () =>
      api.cashFlow(accountId!, {
        type: cashType,
        amount: cashAmt,
        currency: cashCcy,
      }),
    onSuccess: () => {
      setCashMsg(cashType === 'deposit' ? '已入金' : '已出金')
      setCashErr(null)
      refreshAccounts()
      qc.invalidateQueries({ queryKey: ['summary', accountId] })
      qc.invalidateQueries({ queryKey: ['equity-curve', accountId] })
      qc.invalidateQueries({ queryKey: ['cash-flows', accountId] })
    },
    onError: (e: Error) => {
      setCashErr(e.message)
      setCashMsg(null)
    },
  })

  const wallets = summary?.wallets || summary?.cash_by_currency || account?.wallets || {}

  const posCounts = useMemo(() => {
    const c: Record<PosTab, number> = { all: positions.length, cn: 0, us: 0, gold: 0 }
    for (const p of positions) c[positionMarket(p)] += 1
    return c
  }, [positions])

  const filteredPos = useMemo(() => {
    if (posTab === 'all') return positions
    return positions.filter((p) => positionMarket(p) === posTab)
  }, [positions, posTab])

  const sections: { key: Section; label: string }[] = [
    { key: 'overview', label: '总览' },
    { key: 'positions', label: '持仓' },
    { key: 'orders', label: '流水' },
    { key: 'create', label: '新建' },
  ]

  return (
    <>
      <div className="page-head">
        <h1>账本</h1>
      </div>

      {(!ready || accounts.length > 0) && (
        <AccountSelect
          accounts={accounts}
          value={accountId}
          loading={!ready}
          onChange={(id) => {
            setAccountId(id)
            if (section === 'create') setSection('overview')
          }}
        />
      )}

      <div className="subnav">
        {sections
          .filter((s) => s.key === 'create' || accounts.length > 0 || accountId != null)
          .map((s) => (
            <button
              key={s.key}
              type="button"
              className={`subnav-item ${section === s.key ? 'active' : ''}`}
              onClick={() => {
                if (s.key !== 'create' && !accounts.length) {
                  refreshAccounts().catch(() => {})
                }
                setSection(s.key)
              }}
            >
              {s.label}
            </button>
          ))}
      </div>

      {section === 'create' && (
        <section className="surface">
          <h2 className="section-title">新建账本</h2>
          <div className="form-grid form-grid-2">
            <label>
              名称
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              汇总币种
              <select value={baseCurrency} onChange={(e) => setBaseCurrency(e.target.value as 'CNY' | 'USD')}>
                <option value="CNY">CNY 人民币</option>
                <option value="USD">USD 美元</option>
              </select>
            </label>
            <label>
              人民币本金
              <input type="number" value={cashCny} onChange={(e) => setCashCny(Number(e.target.value))} />
            </label>
            <label>
              美元本金
              <input type="number" value={cashUsd} onChange={(e) => setCashUsd(Number(e.target.value))} />
            </label>
          </div>
          <div className="form-actions">
            <button
              className="btn-primary"
              disabled={creating || (cashCny <= 0 && cashUsd <= 0)}
              onClick={create}
            >
              创建账本
            </button>
          </div>
        </section>
      )}

      {section === 'overview' && accountId && (
        <>
          <section className="surface">
            <div className="muted">{summary?.name || account?.name}</div>
            <div className="hero-equity">
              {money(summary?.total_equity, summary?.currency)}
            </div>
            <div className={`hero-pnl ${pnlClass(summary?.total_pnl)}`}>
              <span className="hero-pnl-label">总收益</span>
              <span className="hero-pnl-value num">
                {moneySigned(summary?.total_pnl, summary?.currency)}
              </span>
              {summary?.return_pct != null && (
                <span className="pct-tag">{pct(summary.return_pct)}</span>
              )}
            </div>
            <div className="stat-grid">
              <div className="stat">
                <div className="label">人民币现金</div>
                <div className="value">{money(wallets.CNY ?? 0, 'CNY')}</div>
              </div>
              <div className="stat">
                <div className="label">美元现金</div>
                <div className="value">{money(wallets.USD ?? 0, 'USD')}</div>
              </div>
              <div className="stat">
                <div className="label">持仓市值</div>
                <div className="value">{money(summary?.market_value, summary?.currency)}</div>
              </div>
              <div className="stat">
                <div className="label">净入金</div>
                <div className="value">{money(summary?.net_deposit, summary?.currency)}</div>
              </div>
            </div>
          </section>

          <section className="surface">
            <h2 className="section-title">资产曲线</h2>
            <EquityChart points={equityPoints} />
          </section>

          <section className="surface">
            <h2 className="section-title">出入金</h2>
            <div className="form-grid form-grid-2">
              <label>
                类型
                <select value={cashType} onChange={(e) => setCashType(e.target.value as 'deposit' | 'withdraw')}>
                  <option value="deposit">入金</option>
                  <option value="withdraw">出金</option>
                </select>
              </label>
              <label>
                币种
                <select value={cashCcy} onChange={(e) => setCashCcy(e.target.value as 'CNY' | 'USD')}>
                  <option value="CNY">CNY</option>
                  <option value="USD">USD</option>
                </select>
              </label>
              <label>
                金额
                <input type="number" value={cashAmt} onChange={(e) => setCashAmt(Number(e.target.value))} />
              </label>
            </div>
            <div className="form-actions">
              <button
                className="btn-primary"
                disabled={!accountId || cashMut.isPending || cashAmt <= 0}
                onClick={() => cashMut.mutate()}
              >
                确认
              </button>
            </div>
            {cashMsg && <p className="ok">{cashMsg}</p>}
            {cashErr && <p className="warn">{cashErr}</p>}
          </section>

          <section className="surface">
            <h2 className="section-title">换汇</h2>
            <div className="form-grid form-grid-2">
              <label>
                从
                <select
                  value={fxFrom}
                  onChange={(e) => {
                    const v = e.target.value as 'CNY' | 'USD'
                    setFxFrom(v)
                    if (v === fxTo) setFxTo(v === 'CNY' ? 'USD' : 'CNY')
                    setFxRate('')
                  }}
                >
                  <option value="CNY">CNY</option>
                  <option value="USD">USD</option>
                </select>
              </label>
              <label>
                到
                <select
                  value={fxTo}
                  onChange={(e) => {
                    const v = e.target.value as 'CNY' | 'USD'
                    setFxTo(v)
                    if (v === fxFrom) setFxFrom(v === 'CNY' ? 'USD' : 'CNY')
                    setFxRate('')
                  }}
                >
                  <option value="CNY">CNY</option>
                  <option value="USD">USD</option>
                </select>
              </label>
              <label>
                金额（{fxFrom}）
                <input type="number" value={fxAmount} onChange={(e) => setFxAmount(Number(e.target.value))} />
              </label>
              <label>
                汇率（1 {fxFrom} = ? {fxTo}）
                <input
                  type="number"
                  step="0.0001"
                  value={fxRate}
                  onChange={(e) => setFxRate(e.target.value === '' ? '' : Number(e.target.value))}
                />
              </label>
            </div>
            <div className="form-actions">
              <button
                className="btn-primary"
                disabled={!accountId || fxMut.isPending || fxFrom === fxTo}
                onClick={() => fxMut.mutate()}
              >
                确认换汇
              </button>
              <button
                type="button"
                onClick={() => {
                  setFxFrom(fxTo)
                  setFxTo(fxFrom)
                  setFxRate('')
                }}
              >
                对调币种
              </button>
            </div>
            {fxMsg && <p className="ok">{fxMsg}</p>}
            {fxErr && <p className="warn">{fxErr}</p>}
          </section>
        </>
      )}

      {section === 'positions' && accountId && (
        <>
          <div className="chip-row">
            {(
              [
                ['all', '全部'],
                ['cn', 'A股'],
                ['us', '美股'],
                ['gold', '黄金'],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`chip ${posTab === key ? 'active' : ''}`}
                onClick={() => setPosTab(key)}
              >
                {label}
                <span className="chip-count">{posCounts[key]}</span>
              </button>
            ))}
          </div>
          <section className="surface">
            {posLoading && <p className="muted">加载中…</p>}
            {!filteredPos.length && !posLoading && <div className="empty">暂无持仓</div>}
            {!!filteredPos.length && (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>标的</th>
                    <th>数量</th>
                    <th>成本</th>
                    <th>现价</th>
                    <th>现在赚了</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredPos.map((p) => (
                    <tr key={p.symbol}>
                      <td>
                        <Link to={`/trade/${encodeURIComponent(p.symbol)}`}>
                          <strong>{p.name}</strong>
                        </Link>
                        <div className="muted">{p.symbol}</div>
                      </td>
                      <td className="num">{p.qty}</td>
                      <td className="num">{p.avg_cost}</td>
                      <td className="num">
                        {p.price ?? '—'}
                        {p.stale && p.price != null ? ' *' : ''}
                      </td>
                      <td className={`num ${pnlClass(p.unrealized_pnl)}`}>
                        {p.unrealized_pnl?.toFixed(2) ?? '—'}
                        {p.unrealized_pct != null ? ` (${pct(p.unrealized_pct)})` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="muted mt">
              筛选市值：
              {(['CNY', 'USD'] as const)
                .map((ccy) => {
                  const sum = filteredPos
                    .filter((p) => (p.currency || account?.currency) === ccy)
                    .reduce((s, p) => s + (p.market_value || 0), 0)
                  return sum > 0 ? money(sum, ccy) : null
                })
                .filter(Boolean)
                .join(' · ') || '—'}
            </p>
          </section>
        </>
      )}

      {section === 'orders' && accountId && (
        <>
          <section className="surface">
            <h2 className="section-title">成交</h2>
            {!orders.length && <div className="empty">暂无成交</div>}
            {orders.map((o) => {
              const mk = classifyMarket({ symbol: o.symbol })
              const label = mk === 'cn' ? 'A股' : mk === 'us' ? '美股' : '黄金'
              return (
                <div className="flow-item" key={o.id}>
                  <div className="row between">
                    <div className="row">
                      <span className={`pill ${mk}`}>{label}</span>
                      <strong>
                        {o.side === 'buy' ? '买' : '卖'}{' '}
                        <Link to={`/trade/${encodeURIComponent(o.symbol)}`}>{o.symbol}</Link>
                      </strong>
                    </div>
                    <div className={`num ${o.side === 'buy' ? 'up' : 'down'}`}>
                      {o.qty} @ {o.fill_price}
                    </div>
                  </div>
                  <div className="muted tight">
                    费用 {o.fee} · {o.filled_at ? new Date(o.filled_at).toLocaleString() : ''}
                    {o.note ? ` · ${o.note}` : ''}
                  </div>
                </div>
              )
            })}
          </section>
          <section className="surface">
            <h2 className="section-title">资金</h2>
            {!cashFlows.length && <div className="empty">暂无资金流水</div>}
            {cashFlows.map((f) => {
              const label =
                f.type === 'deposit'
                  ? '入金'
                  : f.type === 'withdraw'
                    ? '出金'
                    : f.type === 'initial'
                      ? '本金'
                      : f.type === 'fx_in'
                        ? '换汇入'
                        : f.type === 'fx_out'
                          ? '换汇出'
                          : f.type
              return (
                <div className="flow-item" key={`cf-${f.id}`}>
                  <div className="row between">
                    <strong>
                      {label} · {f.currency}
                    </strong>
                    <div className="num">{money(f.amount, f.currency)}</div>
                  </div>
                  <div className="muted tight">
                    {f.occurred_at ? new Date(f.occurred_at).toLocaleString() : ''}
                    {f.note ? ` · ${f.note}` : ''}
                  </div>
                </div>
              )
            })}
          </section>
        </>
      )}

      {needsAccount && !accountId && !!accounts.length && (
        <section className="surface">
          <p className="muted">请选择一个账本。</p>
        </section>
      )}
    </>
  )
}
