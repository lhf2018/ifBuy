import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useMemo, useState } from 'react'
import { api } from '../api'
import { useAccount } from '../account'
import { classifyMarket, type MarketKey } from '../lib/markets'
import { money, pct, pnlClass } from '../lib/format'

type Tab = MarketKey | 'all'

function positionMarket(p: { symbol: string; name: string; currency?: string | null }): MarketKey {
  if (/GLD|IAU|SGOL|518880|159934|518800/i.test(p.symbol) || /黄金/.test(p.name)) return 'gold'
  return classifyMarket({
    symbol: p.symbol,
    market: p.currency === 'USD' ? 'US' : 'CN',
    asset_class: p.currency === 'USD' ? 'equity_us' : 'equity_cn',
  })
}

export function Positions() {
  const { accountId, account } = useAccount()
  const [tab, setTab] = useState<Tab>('all')
  const { data = [], isLoading } = useQuery({
    queryKey: ['positions', accountId],
    queryFn: () => api.positions(accountId!),
    enabled: !!accountId,
    refetchInterval: 60_000,
  })

  const counts = useMemo(() => {
    const c: Record<Tab, number> = { all: data.length, cn: 0, us: 0, gold: 0 }
    for (const p of data) c[positionMarket(p)] += 1
    return c
  }, [data])

  const filtered = useMemo(() => {
    if (tab === 'all') return data
    return data.filter((p) => positionMarket(p) === tab)
  }, [data, tab])

  if (!accountId) {
    return (
      <section className="surface">
        <p className="muted">请先创建账本</p>
      </section>
    )
  }

  return (
    <>
      <div className="page-head">
        <h1>持仓</h1>
        <p>
          {account?.name} · 多币种账本 · 按市场筛选
        </p>
      </div>

      <div className="market-tabs" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }}>
        {(
          [
            ['all', '全部', 'All'],
            ['cn', 'A股', 'China'],
            ['us', '美股', 'US'],
            ['gold', '黄金', 'Gold'],
          ] as const
        ).map(([key, label, en]) => (
          <button
            key={key}
            type="button"
            className={`market-tab market-${key === 'all' ? 'cn' : key} ${tab === key ? 'active' : ''}`}
            onClick={() => setTab(key)}
          >
            <span className="market-tab-en">{en}</span>
            <span className="market-tab-label">{label}</span>
            <span className="market-tab-count">{counts[key]}</span>
          </button>
        ))}
      </div>

      <section className="surface">
        {isLoading && <p className="muted">加载中…</p>}
        {!filtered.length && !isLoading && <div className="empty">这一类还没有持仓。</div>}
        {!!filtered.length && (
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
              {filtered.map((p) => (
                <tr key={p.symbol}>
                  <td>
                    <Link to={`/trade/${encodeURIComponent(p.symbol)}`}>
                      <strong>{p.name}</strong>
                    </Link>
                    <div className="muted">{p.symbol}</div>
                  </td>
                  <td>{p.qty}</td>
                  <td>{p.avg_cost}</td>
                  <td>
                    {p.price ?? '—'}
                    {p.stale && p.price != null ? ' *' : ''}
                  </td>
                  <td className={pnlClass(p.unrealized_pnl)}>
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
              const sum = filtered
                .filter((p) => (p.currency || account?.currency) === ccy)
                .reduce((s, p) => s + (p.market_value || 0), 0)
              return sum > 0 ? money(sum, ccy) : null
            })
            .filter(Boolean)
            .join(' · ') || '—'}
        </p>
      </section>
    </>
  )
}
