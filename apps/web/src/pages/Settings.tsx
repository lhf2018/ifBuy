import { useQuery } from '@tanstack/react-query'
import { api } from '../api'

export function Settings() {
  const { data: feeRules = [] } = useQuery({
    queryKey: ['fee-rules'],
    queryFn: api.feeRules,
  })

  const download = async () => {
    const data = await api.exportData()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ifbuy-export-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <div className="page-head">
        <h1>设置</h1>
      </div>
      <section className="surface">
        <h2 className="section-title">数据</h2>
        <div className="form-actions" style={{ marginTop: 0 }}>
          <button className="btn-primary" onClick={download}>
            导出
          </button>
        </div>
      </section>
      <section className="surface">
        <h2 className="section-title">费率</h2>
        <table className="data-table">
          <thead>
            <tr>
              <th>市场</th>
              <th>类型</th>
              <th>买佣金</th>
              <th>买最低</th>
              <th>卖佣金</th>
              <th>卖印花税</th>
            </tr>
          </thead>
          <tbody>
            {feeRules.map((r) => (
              <tr key={r.id}>
                <td>{r.market_label}</td>
                <td>{r.instrument_type || '—'}</td>
                <td className="num">{(r.buy_commission_rate * 100).toFixed(3)}%</td>
                <td className="num">{r.buy_min_commission}</td>
                <td className="num">{(r.sell_commission_rate * 100).toFixed(3)}%</td>
                <td className="num">{(r.sell_stamp_tax_rate * 100).toFixed(3)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  )
}
