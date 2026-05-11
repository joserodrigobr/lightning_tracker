import { useCallback, useEffect, useRef, useState } from 'react'

export function useNowcast({ takerId, refreshIntervalMs = 60_000 }) {
  const [nowcast, setNowcast] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const inFlight = useRef(false)

  const fetchNowcast = useCallback(async () => {
    // We can fetch nowcast even for takerId 0 (all)
    if (inFlight.current) return
    inFlight.current = true
    setLoading(true)
    setError('')

    try {
      const qs = new URLSearchParams()
      if (takerId && takerId !== '0') qs.set('takerId', takerId)
      qs.set('_ts', Date.now())

      const res = await fetch(`/api/nowcast?${qs.toString()}`)
      if (!res.ok) throw new Error(`Erro ao buscar nowcast (${res.status})`)
      const data = await res.json()
      setNowcast(data)
    } catch (e) {
      setError(String(e?.message || e))
    } finally {
      inFlight.current = false
      setLoading(false)
    }
  }, [takerId])

  useEffect(() => {
    fetchNowcast()
  }, [fetchNowcast])

  useEffect(() => {
    const id = setInterval(fetchNowcast, refreshIntervalMs)
    return () => clearInterval(id)
  }, [fetchNowcast, refreshIntervalMs])

  return { nowcast, loading, error, refetch: fetchNowcast }
}
