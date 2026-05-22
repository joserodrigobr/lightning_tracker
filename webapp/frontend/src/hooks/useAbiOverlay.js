import { useCallback, useEffect, useRef, useState } from 'react'
import { getAbiOverlay } from '../services/lightningService'

/**
 * Hook to fetch and auto-refresh the ABI IR CH13 full-disk overlay tile from /api/abi.
 * The geographic bounds are read from the X-Abi-Bounds response header (real disk extent).
 *
 * @param {Object} params
 * @param {boolean} params.enabled    Whether ABI overlay is active
 * @param {string}  params.utcIso    UTC ISO8601 string for the desired image time
 * @param {number}  params.refreshMs Poll interval (default 10 min)
 * @param {string}  params.cmap      "gray_r" | "ir_enhanced"
 * @returns {{ abiUrl, abiBounds, abiUtc, abiLoading, abiError }}
 */
export function useAbiOverlay({
  enabled = false,
  utcIso = null,
  refreshMs = 10 * 60 * 1000,
  cmap = 'gray_r',
}) {
  const [abiUrl, setAbiUrl] = useState(null)
  const [abiBounds, setAbiBounds] = useState(null)   // [[latMin,lonMin],[latMax,lonMax]] from server
  const [abiUtc, setAbiUtc] = useState(null)
  const [abiLoading, setAbiLoading] = useState(false)
  const [abiError, setAbiError] = useState('')
  const inFlight = useRef(false)
  const blobUrlRef = useRef(null)

  const fetchTile = useCallback(async () => {
    if (!enabled) return
    if (inFlight.current) return
    inFlight.current = true
    setAbiLoading(true)
    setAbiError('')

    try {
      const qs = new URLSearchParams({ cmap, _ts: Date.now() })
      if (utcIso) qs.set('utc', utcIso)

      const res = await getAbiOverlay(qs)
      console.log(`[ABI] Fetch response: ${res.status} ${res.ok ? 'OK' : 'Error'}`)
      if (!res.ok) throw new Error(`ABI tile error (${res.status})`)

      // Bounds come from the reprojected full disk (URL-encoded by ASP.NET)
      const boundsHeader = res.headers.get('x-abi-bounds')
      console.log(`[ABI] Bounds header:`, boundsHeader)
      if (boundsHeader) {
        const decoded = decodeURIComponent(boundsHeader)
        const [latMin, lonMin, latMax, lonMax] = decoded.split(',').map(Number)
        console.log(`[ABI] Decoded bounds:`, { latMin, lonMin, latMax, lonMax })
        if ([latMin, lonMin, latMax, lonMax].every(isFinite)) {
          setAbiBounds([[latMin, lonMin], [latMax, lonMax]])
        }
      }

      const utcHeader = res.headers.get('x-abi-utc')
      if (utcHeader) setAbiUtc(decodeURIComponent(utcHeader))

      // Convert body to blob URL for Leaflet ImageOverlay
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)

      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current)
      blobUrlRef.current = url
      setAbiUrl(url)
    } catch (e) {
      setAbiError(String(e?.message || e))
    } finally {
      inFlight.current = false
      setAbiLoading(false)
    }
  }, [enabled, utcIso, cmap])

  // Fetch immediately on enable / param change
  useEffect(() => {
    if (!enabled) {
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current)
        blobUrlRef.current = null
      }
      setAbiUrl(null)
      setAbiBounds(null)
      setAbiUtc(null)
      setAbiError('')
      return
    }
    fetchTile()
  }, [enabled, fetchTile])

  // Auto-refresh
  useEffect(() => {
    if (!enabled) return
    const id = setInterval(fetchTile, refreshMs)
    return () => clearInterval(id)
  }, [enabled, fetchTile, refreshMs])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current)
    }
  }, [])

  return { abiUrl, abiBounds, abiUtc, abiLoading, abiError }
}
