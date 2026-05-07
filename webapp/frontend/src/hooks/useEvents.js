import { useCallback, useEffect, useRef, useState } from 'react'
import { haversineKm } from '../utils/haversine'

const RADII = [30, 50, 100, 200]

function buildQuery(params) {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null) continue
    const s = String(v)
    if (s === '') continue
    qs.set(k, s)
  }
  return qs.toString()
}

export function useEvents({ takerId, taker, mode, startLocal, endLocal, initialLoadHours, refreshIntervalMs = 60_000 }) {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [stats, setStats] = useState({ total: 0, last5min: 0, byRing: [0, 0, 0, 0] })
  const inFlight = useRef(false)

  const fetchEvents = useCallback(async () => {
    if (takerId === '' || takerId === null || takerId === undefined) return
    if (!taker) return
    if (inFlight.current) return
    inFlight.current = true
    setLoading(true)
    setError('')

    try {
      const qs = buildQuery({
        takerId,
        mode,
        startLocal,
        endLocal,
        initialLoadHours: initialLoadHours || 3,
        _ts: Date.now(),
      })
      const res = await fetch(`/api/events?${qs}`)
      if (!res.ok) throw new Error(`Erro ao buscar eventos (${res.status})`)
      const data = await res.json()
      const arr = Array.isArray(data) ? data : []
      setEvents(arr)

      // Calculate stats
      const now = new Date()
      const fiveMinAgo = new Date(now.getTime() - 5 * 60 * 1000)
      let last5 = 0
      const rings = [0, 0, 0, 0]
      const hasTakerLocation = taker && taker.id !== 0

      for (const ev of arr) {
        const evTime = new Date(ev.eventTime)
        if (evTime >= fiveMinAgo) last5++

        if (hasTakerLocation) {
          const dist = haversineKm(taker.lat, taker.lon, ev.latitude, ev.longitude)
          for (let i = 0; i < RADII.length; i++) {
            if (dist <= RADII[i]) {
              rings[i]++
              break
            }
          }
        }
      }

      setStats({ total: arr.length, last5min: last5, byRing: rings })
    } catch (e) {
      setError(String(e?.message || e))
      setEvents([])
      setStats({ total: 0, last5min: 0, byRing: [0, 0, 0, 0] })
    } finally {
      inFlight.current = false
      setLoading(false)
    }
  }, [takerId, taker, mode, startLocal, endLocal, initialLoadHours])

  // Fetch on param change
  useEffect(() => {
    fetchEvents()
  }, [fetchEvents])

  // Auto-refresh
  useEffect(() => {
    if (!takerId || !taker) return
    const id = setInterval(fetchEvents, refreshIntervalMs)
    return () => clearInterval(id)
  }, [fetchEvents, takerId, taker, refreshIntervalMs])

  return { events, loading, error, stats, refetch: fetchEvents }
}
