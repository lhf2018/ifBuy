import { useEffect, useRef } from 'react'
import {
  createChart,
  CandlestickSeries,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type SeriesMarker,
  type ISeriesMarkersPluginApi,
  type Time,
} from 'lightweight-charts'
import type { Bar, TradeMarker } from '../api'

function toChartTime(ts: string): Time {
  // bars use YYYY-MM-DD or ISO; markers may be full ISO — normalize to YYYY-MM-DD for daily
  return ts.slice(0, 10) as Time
}

export function KlineChart({
  bars,
  lastPrice,
  markers = [],
}: {
  bars: Bar[]
  lastPrice?: number | null
  markers?: TradeMarker[]
}) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const markersApiRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = createChart(ref.current, {
      height: 420,
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
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#e85d4c',
      downColor: '#2f9e6e',
      borderUpColor: '#e85d4c',
      borderDownColor: '#2f9e6e',
      wickUpColor: '#e85d4c',
      wickDownColor: '#2f9e6e',
    })
    markersApiRef.current = createSeriesMarkers(series, [])
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
      markersApiRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current || !bars.length) return
    const data: CandlestickData[] = bars.map((b, i) => {
      let close = b.close
      let high = b.high
      let low = b.low
      if (!b.finalized && lastPrice && i === bars.length - 1) {
        const drift = Math.abs(lastPrice - b.close) / b.close
        if (drift < 0.05) {
          close = lastPrice
          high = Math.max(high, lastPrice)
          low = Math.min(low, lastPrice)
        }
      }
      return {
        time: toChartTime(b.ts),
        open: b.open,
        high,
        low,
        close,
      }
    })
    seriesRef.current.setData(data)
    chartRef.current?.timeScale().fitContent()
  }, [bars, lastPrice])

  useEffect(() => {
    if (!markersApiRef.current || !bars.length) {
      markersApiRef.current?.setMarkers([])
      return
    }
    const mapped: SeriesMarker<Time>[] = []
    for (const m of markers) {
      const mt = Date.parse(m.time.slice(0, 10))
      let best = bars[0]
      let bestDiff = Infinity
      for (const b of bars) {
        const diff = Math.abs(Date.parse(b.ts.slice(0, 10)) - mt)
        if (diff < bestDiff) {
          bestDiff = diff
          best = b
        }
      }
      const buy = m.side === 'buy'
      mapped.push({
        time: toChartTime(best.ts),
        position: buy ? 'belowBar' : 'aboveBar',
        color: buy ? '#e85d4c' : '#2f9e6e',
        shape: buy ? 'arrowUp' : 'arrowDown',
        text: buy ? 'B' : 'S',
      })
    }
    const uniq = new Map<string, SeriesMarker<Time>>()
    for (const m of mapped) uniq.set(`${String(m.time)}-${m.text}`, m)
    markersApiRef.current.setMarkers(
      [...uniq.values()].sort((a, b) => String(a.time).localeCompare(String(b.time))),
    )
  }, [markers, bars])

  return <div className="kline" ref={ref} />
}
