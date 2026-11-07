import { MARKETS, type MarketKey } from '../lib/markets'

export function MarketTabs({
  value,
  onChange,
  counts,
}: {
  value: MarketKey
  onChange: (k: MarketKey) => void
  counts?: Partial<Record<MarketKey, number>>
}) {
  return (
    <div className="market-tabs" role="tablist" aria-label="市场分类">
      {MARKETS.map((m) => {
        const active = value === m.key
        const count = counts?.[m.key]
        return (
          <button
            key={m.key}
            type="button"
            role="tab"
            aria-selected={active}
            className={`market-tab market-${m.key} ${active ? 'active' : ''}`}
            onClick={() => onChange(m.key)}
          >
            <span className="market-tab-en">{m.en}</span>
            <span className="market-tab-label">{m.label}</span>
            {typeof count === 'number' && <span className="market-tab-count">{count}</span>}
          </button>
        )
      })}
    </div>
  )
}
