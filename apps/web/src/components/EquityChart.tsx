import { useEffect, useRef } from 'react'
import {
  createChart,
  AreaSeries,
  type IChartApi,
  type ISeriesApi,
  type AreaData,
  type Time,
} from 'lightweight-charts'
import type { EquityPoint } from '../api'

export function EquityChart({ points }: { points: EquityPoint[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Area'> | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = createChart(ref.current, {
      height: 240,
      layout: {
        background: { color: '#e0e5ec' },
        textColor: '#6b7280',
        fontFamily: 'Outfit, Noto Sans SC, sans-serif',
      },
      grid: {
        vertLines: { color: 'rgba(184,188,194,0.35)' },
        horzLines: { color: 'rgba(184,188,194,0.35)' },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      crosshair: { horzLine: { labelBackgroundColor: '#6d5dfc' }, vertLine: { labelBackgroundColor: '#6d5dfc' } },
    })
    const series = chart.addSeries(AreaSeries, {
      lineColor: '#6d5dfc',
      topColor: 'rgba(109, 93, 252, 0.35)',
      bottomColor: 'rgba(109, 93, 252, 0.02)',
      lineWidth: 2,
    })
    chartRef.current = chart
    seriesRef.current = series
    const ro = new ResizeObserver(() => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth })
    })
    ro.observe(ref.current)
    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current || !points.length) return
    const data: AreaData[] = points.map((p) => ({
      time: p.date as Time,
      value: p.total_equity,
    }))
    seriesRef.current.setData(data)
    chartRef.current?.timeScale().fitContent()
  }, [points])

  if (!points.length) return <div className="empty">暂无曲线</div>
  return <div className="equity-chart" ref={ref} />
}
