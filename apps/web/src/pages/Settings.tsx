import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useAccount } from '../account'

export function Settings() {
  const { accountId } = useAccount()
  const qc = useQueryClient()
  const { data: feeRules = [] } = useQuery({
    queryKey: ['fee-rules'],
    queryFn: api.feeRules,
  })
  const { data: settingsData } = useQuery({
    queryKey: ['account-settings', accountId],
    queryFn: () => api.accountSettings(accountId!),
    enabled: !!accountId,
  })

  const [maxWeight, setMaxWeight] = useState(40)
  const [lossPct, setLossPct] = useState(15)
  const [lowCash, setLowCash] = useState(5)
  const [hkQuota, setHkQuota] = useState(1_000_000)
  const [msg, setMsg] = useState<string | null>(null)

  useEffect(() => {
    const s = settingsData?.settings
    if (!s) return
    setMaxWeight(s.alert_max_weight_pct)
    setLossPct(s.alert_loss_pct)
    setLowCash(s.alert_low_cash_pct)
    setHkQuota(s.hk_connect_daily_quota_cny)
  }, [settingsData])

  const saveMut = useMutation({
    mutationFn: () =>
      api.updateAccountSettings(accountId!, {
        alert_max_weight_pct: maxWeight,
        alert_loss_pct: lossPct,
        alert_low_cash_pct: lowCash,
        hk_connect_daily_quota_cny: hkQuota,
      }),
    onSuccess: () => {
      setMsg('已保存')
      qc.invalidateQueries({ queryKey: ['account-settings', accountId] })
      qc.invalidateQueries({ queryKey: ['risk', accountId] })
      qc.invalidateQueries({ queryKey: ['summary', accountId] })
    },
    onError: (e: Error) => setMsg(e.message),
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

  const hk = settingsData?.hk_connect

  return (
    <>
      <div className="page-head">
        <h1>设置</h1>
      </div>

      {accountId && (
        <section className="surface">
          <h2 className="section-title">持仓预警</h2>
          <p className="section-desc muted">按当前账本生效，用于总览风险提示。</p>
          <div className="form-grid form-grid-2">
            <label>
              单票集中度告警（%）
              <input
                type="number"
                value={maxWeight}
                onChange={(e) => setMaxWeight(Number(e.target.value))}
              />
            </label>
            <label>
              浮亏告警（%）
              <input type="number" value={lossPct} onChange={(e) => setLossPct(Number(e.target.value))} />
            </label>
            <label>
              现金过低告警（%）
              <input type="number" value={lowCash} onChange={(e) => setLowCash(Number(e.target.value))} />
            </label>
            <label>
              港股通日额度（CNY）
              <input type="number" value={hkQuota} onChange={(e) => setHkQuota(Number(e.target.value))} />
            </label>
          </div>
          {hk && (
            <p className="muted mt">
              今日已用 ¥{Math.round(hk.used_cny).toLocaleString()} · 剩余 ¥
              {Math.round(hk.remaining_cny).toLocaleString()}（{hk.trade_date}）
            </p>
          )}
          <div className="form-actions">
            <button className="btn-primary" disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>
              保存预警与额度
            </button>
            {msg && <span className="muted">{msg}</span>}
          </div>
          <p className="muted mt">
            A 股 / 港股默认 T+1：当日买入份额次日才可卖。美股、加密、期货纸面按 T+0。
          </p>
        </section>
      )}

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
