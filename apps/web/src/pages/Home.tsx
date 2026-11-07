import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAccount } from '../account'
import { money, pct, pnlClass } from '../lib/format'
import { MARKETS } from '../lib/markets'

export function Home() {
  const { accountId, accounts, setAccountId, refreshAccounts, account } = useAccount()
  const qc = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('我的练习账本')
  const [baseCurrency, setBaseCurrency] = useState<'CNY' | 'USD'>('CNY')
  const [cashCny, setCashCny] = useState(100000)
  const [cashUsd, setCashUsd] = useState(10000)

  const [fxFrom, setFxFrom] = useState<'CNY' | 'USD'>('CNY')
  const [fxTo, setFxTo] = useState<'CNY' | 'USD'>('USD')
  const [fxAmount, setFxAmount] = useState(1000)
  const [fxRate, setFxRate] = useState<number | ''>('')
  const [fxMsg, setFxMsg] = useState<string | null>(null)
  const [fxErr, setFxErr] = useState<string | null>(null)

  const { data: summary, refetch } = useQuery({
    queryKey: ['summary', accountId],
    queryFn: () => api.summary(accountId!),
    enabled: !!accountId,
  })

  const { data: rateInfo } = useQuery({
    queryKey: ['fx-rate', fxFrom, fxTo],
    queryFn: () => api.fxRate(fxFrom, fxTo),
    enabled: fxFrom !== fxTo,
    refetchInterval: 60_000,
  })

  useEffect(() => {
    if (rateInfo?.rate && fxRate === '') setFxRate(Number(rateInfo.rate.toFixed(6)))
  }, [rateInfo?.rate])

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
      setFxMsg(`已换汇：${r.from_amount} ${r.from_currency} → ${r.to_amount} ${r.to_currency}（汇率 ${r.rate}）`)
      setFxErr(null)
      refreshAccounts()
      qc.invalidateQueries({ queryKey: ['summary', accountId] })
    },
    onError: (e: Error) => {
      setFxErr(e.message)
      setFxMsg(null)
    },
  })

  const wallets = summary?.wallets || summary?.cash_by_currency || account?.wallets || {}
  const swapFx = () => {
    setFxFrom(fxTo)
    setFxTo(fxFrom)
    setFxRate('')
  }

  if (!accounts.length) {
    return (
      <>
        <div className="page-head">
          <h1>开一个账本，开始练手</h1>
          <p>一个账本可同时持有人民币和美元现金，买卖时扣对应币种，中间可自由换汇。</p>
        </div>
        <section className="surface">
          <div className="form-grid">
            <label>
              名称
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              汇总币种
              <select value={baseCurrency} onChange={(e) => setBaseCurrency(e.target.value as 'CNY' | 'USD')}>
                <option value="CNY">CNY 人民币（总资产按人民币折算）</option>
                <option value="USD">USD 美元（总资产按美元折算）</option>
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
          <button className="btn-primary" disabled={creating || (cashCny <= 0 && cashUsd <= 0)} onClick={create}>
            创建账本
          </button>
        </section>
      </>
    )
  }

  return (
    <>
      <div className="page-head">
        <h1>账本总览</h1>
        <p>假钱、真行情。资产可同时有人民币与美元，需要时在本页换汇。</p>
      </div>

      <div className="hero-board">
        <section className="surface">
          <div className="row between">
            <span className="badge">模拟 · 非真实下单</span>
            <select value={accountId ?? ''} onChange={(e) => setAccountId(Number(e.target.value))}>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
          <div className="muted mt">{summary?.name || account?.name}</div>
          <div className="hero-equity">
            {money(summary?.total_equity, summary?.currency)}
            {summary?.return_pct != null && (
              <span className={`pct-tag ${pnlClass(summary.return_pct)}`}>{pct(summary.return_pct)}</span>
            )}
          </div>
          <p className="muted" style={{ marginTop: 4 }}>
            总权益按 {summary?.base_currency || summary?.currency} 折算
          </p>
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
              <div className="label">持仓市值（折算）</div>
              <div className="value">{money(summary?.market_value, summary?.currency)}</div>
            </div>
            <div className="stat">
              <div className="label">持仓只数</div>
              <div className="value">{summary?.positions_count ?? 0}</div>
            </div>
          </div>
          <div className="row mt">
            <Link className="btn btn-primary" to="/markets">
              去行情
            </Link>
            <Link className="btn" to="/positions">
              看持仓
            </Link>
          </div>
        </section>

        <section className="surface">
          <h2 style={{ marginTop: 0, fontFamily: 'var(--font-display)' }}>换汇</h2>
          <p className="muted">账本内 CNY ↔ USD，可跟参考汇率或手填。</p>
          <div className="form-grid">
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
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <button className="btn-primary" disabled={!accountId || fxMut.isPending || fxFrom === fxTo} onClick={() => fxMut.mutate()}>
              确认换汇
            </button>
            <button type="button" onClick={swapFx}>
              对调币种
            </button>
          </div>
          {rateInfo && (
            <p className="muted" style={{ marginTop: 8 }}>
              参考汇率 {rateInfo.rate.toFixed(6)}（{rateInfo.source}）
            </p>
          )}
          {fxMsg && <p className="ok">{fxMsg}</p>}
          {fxErr && <p className="warn">{fxErr}</p>}
        </section>
      </div>

      <div className="gate-cards">
        {MARKETS.map((m) => (
          <Link key={m.key} className={`gate-card ${m.key}`} to={`/markets?tab=${m.key}`}>
            <div className="en">{m.en}</div>
            <div className="zh">{m.label}</div>
            <div className="desc">{m.hint}</div>
          </Link>
        ))}
      </div>

      <section className="surface mt">
        <h2 style={{ marginTop: 0, fontFamily: 'var(--font-display)' }}>再开账本</h2>
        <p className="muted">想分开策略时再建一个，每个账本都可持有多币种现金。</p>
        <div className="form-grid">
          <label>
            名称
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            汇总币种
            <select value={baseCurrency} onChange={(e) => setBaseCurrency(e.target.value as 'CNY' | 'USD')}>
              <option value="CNY">CNY</option>
              <option value="USD">USD</option>
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
        <button disabled={creating || (cashCny <= 0 && cashUsd <= 0)} onClick={create}>
          创建
        </button>
      </section>
    </>
  )
}
