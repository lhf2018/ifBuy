import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAccount } from '../account'
import { classifyMarket } from '../lib/markets'

export function Orders() {
  const { accountId, account } = useAccount()
  const { data = [] } = useQuery({
    queryKey: ['orders', accountId],
    queryFn: () => api.orders(accountId!),
    enabled: !!accountId,
  })

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
        <h1>流水</h1>
        <p>
          {account?.name} · 每一笔模拟成交
        </p>
      </div>
      <section className="surface">
        {!data.length && <div className="empty">还没有成交记录。</div>}
        {data.map((o) => {
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
                <div className={o.side === 'buy' ? 'up' : 'down'}>
                  {o.qty} @ {o.fill_price}
                </div>
              </div>
              <div className="muted" style={{ marginTop: 6 }}>
                费用 {o.fee} · {o.filled_at ? new Date(o.filled_at).toLocaleString() : ''} · {o.price_source}
                {o.note ? ` · ${o.note}` : ''}
              </div>
            </div>
          )
        })}
      </section>
    </>
  )
}
