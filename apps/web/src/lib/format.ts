export function money(v: number | null | undefined, currency = 'CNY') {
  if (v == null || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(v)
}

/** Signed money for PnL, e.g. +¥1,234.00 */
export function moneySigned(v: number | null | undefined, currency = 'CNY') {
  if (v == null || Number.isNaN(v)) return '—'
  const abs = money(Math.abs(v), currency)
  if (v > 0) return `+${abs}`
  if (v < 0) return `-${abs}`
  return abs
}

/** Price display — keep decimals so digits feel less stubby */
export function price(v: number | null | undefined, digits = 2) {
  if (v == null || Number.isNaN(v)) return '—'
  return v.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function pct(v: number | null | undefined, digits = 2) {
  if (v == null || Number.isNaN(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(digits)}%`
}

export function pnlClass(v: number | null | undefined) {
  if (v == null || v === 0) return 'flat'
  return v > 0 ? 'up' : 'down'
}
