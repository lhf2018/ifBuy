import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useMemo, useState } from 'react'
import { api } from '../api'
import { useAccount } from '../account'
import { MARKETS, classifyMarket, marketLabel, type MarketKey } from '../lib/markets'
import { money, pct, pnlClass } from '../lib/format'

type Tab = MarketKey | 'all'

function positionMarket(p: { symbol: string; name: string; currency?: string | null }): MarketKey {
  return classifyMarket({ symbol: p.symbol })
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
    const c: Record<string, number> = { all: data.length }
    for (const m of MARKETS) c[m.key] = 0
    for (const p of data) c[positionMarket(p)] = (c[positionMarket(p)] || 0) + 1
    return c as Record<Tab, number>
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

      <div className="market-tabs">
        {([['all', '全部', 'All'], ...MARKETS.map((m) => [m.key, m.label, m.en])] as const).map(
          ([key, label, en]) => (
            <button
              key={key}
              type="button"
              className={`market-tab market-${key === 'all' ? 'cn' : key} ${tab === key ? 'active' : ''}`}
              onClick={() => setTab(key as Tab)}
            >
              <span className="market-tab-en">{en}</span>
              <span className="market-tab-label">{label}</span>
              <span className="market-tab-count">{counts[key as Tab] || 0}</span>
            </button>
          ),
        )}
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
                    <div className="muted">
                      {p.symbol} · {marketLabel(positionMarket(p))}
                    </div>
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
          合计市值：
          {money(
            filtered.reduce((s, p) => s + (p.market_value || 0), 0),
            account?.currency,
          )}
        </p>
      </section>
    </>
  )
}
