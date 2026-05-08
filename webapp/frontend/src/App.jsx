import './App.css'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Header from './components/Header'
import LightningMap from './components/LightningMap'
import ControlPanel from './components/ControlPanel'
import StatsPanel from './components/StatsPanel'
import SideMenu from './components/SideMenu'
import { useEvents } from './hooks/useEvents'
import { useAbiOverlay } from './hooks/useAbiOverlay'
import DataRequestModal from './components/DataRequestModal'
import ChartModal from './components/ChartModal'


const DEFAULT_RENDER_HOURS = 4

// Virtual taker for "all of South America" view
const SOUTH_AMERICA_TAKER = { id: 0, name: 'América do Sul', lat: -14.0, lon: -52.0 }

function normalizeDateTimeLocal(value) {
  if (!value) return ''
  if (value.length === 16) return `${value}:00`
  return value
}

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

function formatLocalIso(dt) {
  const y = dt.getFullYear()
  const m = String(dt.getMonth() + 1).padStart(2, '0')
  const d = String(dt.getDate()).padStart(2, '0')
  const hh = String(dt.getHours()).padStart(2, '0')
  const mm = String(dt.getMinutes()).padStart(2, '0')
  const ss = String(dt.getSeconds()).padStart(2, '0')
  return `${y}-${m}-${d}T${hh}:${mm}:${ss}`
}

function csvCell(value) {
  return String(value ?? '').replace(/"/g, '""')
}

function buildTableCsv(tableData) {
  const hourLabels = Array.isArray(tableData?.hourLabels) ? tableData.hourLabels : []
  const radiiLabels = Array.isArray(tableData?.radiiLabels) ? tableData.radiiLabels : []
  const values = Array.isArray(tableData?.values4x24) ? tableData.values4x24 : []
  const lines = []
  lines.push(['Anel \\ Tempo', ...hourLabels].map((cell) => `"${csvCell(cell)}"`).join(';'))
  radiiLabels.forEach((label, rowIndex) => {
    const row = Array.isArray(values[rowIndex]) ? values[rowIndex] : []
    const cells = [label, ...hourLabels.map((_, colIndex) => row[colIndex] ?? 0)]
    lines.push(cells.map((cell) => `"${csvCell(cell)}"`).join(';'))
  })
  return `${lines.join('\r\n')}\r\n`
}

function triggerBrowserDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 2000)
}

function App() {
  // ─── State ───
  const [takers, setTakers] = useState([])
  const [takersError, setTakersError] = useState('')
  const isLoadingTakersRef = useRef(false)

  const [takerId, setTakerId] = useState('0')
  const [mode, setMode] = useState(1)
  const [startLocal, setStartLocal] = useState('')
  const [endLocal, setEndLocal] = useState('')
  const [initialLoadHours, setInitialLoadHours] = useState(DEFAULT_RENDER_HOURS)
  const [backgroundIr, setBackgroundIr] = useState(false)
  const [showMap, setShowMap] = useState(true)
  const [showRings, setShowRings] = useState(true)
  const [showAllTakers, setShowAllTakers] = useState(true)

  const [animating, setAnimating] = useState(false)
  const [frames, setFrames] = useState([])
  const [frameIndex, setFrameIndex] = useState(0)
  const [isPrefetching, setIsPrefetching] = useState(false)
  const [markerInterval, setMarkerInterval] = useState(10)
  const [visMode, setVisMode] = useState('points')
  const [lastUpdateLocal, setLastUpdateLocal] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)

  // Table state (preserved from original)
  const [tableData, setTableData] = useState(null)
  const [tableStatus, setTableStatus] = useState('')
  const [tableError, setTableError] = useState('')
  const [isGeneratingTable, setIsGeneratingTable] = useState(false)
  const [savedTables, setSavedTables] = useState([])

  const [dataRequestOpen, setDataRequestOpen] = useState(false)
  const [chartModalOpen, setChartModalOpen] = useState(false)
  const [chartData, setChartData] = useState(null)
  const [chartTitle, setChartTitle] = useState('')

  const autoSelectRequestedRef = useRef(false)

  const selectedTaker = useMemo(() => {
    if (!takerId && takerId !== '0' && takerId !== 0) return null
    if (String(takerId) === '0') return SOUTH_AMERICA_TAKER
    return takers.find((t) => String(t.id) === String(takerId)) || null
  }, [takers, takerId])

  // Build the dropdown list: América do Sul first, then real takers
  const takerOptions = useMemo(() => {
    return [SOUTH_AMERICA_TAKER, ...takers]
  }, [takers])

  // ─── Events hook (new JSON API) ───
  const { events, loading: eventsLoading, stats } = useEvents({
    takerId,
    taker: selectedTaker,
    mode,
    startLocal: normalizeDateTimeLocal(startLocal),
    endLocal: normalizeDateTimeLocal(endLocal),
    initialLoadHours,
    refreshIntervalMs: 60_000,
  })

  // ─── ABI overlay hook ───
  // Compute UTC reference from endLocal (BRT = UTC-3) or fall back to now
  const abiUtcIso = useMemo(() => {
    if (endLocal) {
      // endLocal is a local datetime string (BRT, UTC-3); add 3h to get UTC
      const d = new Date(endLocal)
      d.setHours(d.getHours() + 3)
      return d.toISOString()
    }
    return new Date().toISOString()
  }, [endLocal])

  const { abiUrl, abiBounds, abiUtc, abiLoading, abiError } = useAbiOverlay({
    enabled: backgroundIr,
    utcIso: abiUtcIso,
    cmap: 'gray_r',
  })

  // ─── Load takers ───
  async function loadTakers() {
    if (isLoadingTakersRef.current) return
    isLoadingTakersRef.current = true
    setTakersError('')
    try {
      const res = await fetch('/api/takers')
      if (!res.ok) throw new Error(`Falha ao carregar tomadores (${res.status})`)
      const data = await res.json()
      setTakers(Array.isArray(data) ? data : [])
    } catch (e) {
      setTakersError(String(e?.message || e))
    } finally {
      isLoadingTakersRef.current = false
    }
  }

  async function loadDefaultTaker() {
    if (autoSelectRequestedRef.current || (takerId && takerId !== '0')) return
    autoSelectRequestedRef.current = true

    try {
      // 1. Try to get user location for proximity auto-selection with 5s timeout
      if ("geolocation" in navigator) {
        const geoTimeout = setTimeout(() => {
          console.warn("Geolocalização excedeu 5s. Usando padrão.");
          loadFallbackTaker();
        }, 5000);

        navigator.geolocation.getCurrentPosition(async (position) => {
          clearTimeout(geoTimeout);
          const { latitude, longitude } = position.coords;
          
          let closest = null;
          let minDistance = Infinity;

          takers.forEach(t => {
            const dist = Math.sqrt(Math.pow(t.lat - latitude, 2) + Math.pow(t.lon - longitude, 2));
            if (dist < minDistance) {
              minDistance = dist;
              closest = t;
            }
          });

          if (closest) {
            console.log(`Auto-selecionado por proximidade: ${closest.name}`);
            setTakerId(String(closest.id));
            return;
          }
        }, () => {
          console.warn("Geolocalização negada ou falhou. Usando padrão.");
          loadFallbackTaker();
        });
      } else {
        loadFallbackTaker();
      }
    } catch (err) {
      console.error('Falha ao carregar geolocalização:', err)
    }
  }

  async function loadFallbackTaker() {
    const res = await fetch('/api/active-taker')
    if (res.ok) {
      const data = await res.json()
      if (data?.takerId) setTakerId(String(data.takerId))
    } else if (takers.length > 0) {
      setTakerId(String(takers[0].id))
    }
  }

  // ─── Tables (preserved) ───
  async function loadSavedTables() {
    if (!selectedTaker) return
    try {
      const qs = buildQuery({ takerId: selectedTaker.id, limit: 8, _ts: Date.now() })
      const res = await fetch(`/api/tables/latest?${qs}`)
      if (!res.ok) throw new Error(`Falha ao listar tabelas (${res.status})`)
      const data = await res.json()
      setSavedTables(Array.isArray(data) ? data : [])
    } catch (e) {
      console.error(e)
    }
  }

  async function loadSavedTable(relativePath) {
    if (!relativePath) return
    try {
      const qs = buildQuery({ relativePath, _ts: Date.now() })
      const res = await fetch(`/api/tables/load?${qs}`)
      if (!res.ok) throw new Error(`Falha ao carregar tabela (${res.status})`)
      const data = await res.json()
      setTableData(data)
      setTableStatus(`Tabela carregada: ${data?.fileName || relativePath}`)
    } catch (e) {
      setTableStatus(String(e?.message || e))
    }
  }

  async function generateTable(period = '24h', binSize = 5) {
    if (!selectedTaker) return
    setIsGeneratingTable(true)
    setTableStatus('Gerando tabela...')
    try {
      const qs = buildQuery({ 
        takerId: selectedTaker.id, 
        endLocal: normalizeDateTimeLocal(endLocal), 
        period, 
        binSize,
        _ts: Date.now() 
      })
      const res = await fetch(`/api/tables/generate?${qs}`)
      if (!res.ok) throw new Error(`Falha ao gerar tabela (${res.status})`)
      const data = await res.json()
      setTableData(data)
      setTableStatus(`Tabela gerada com sucesso e download iniciado!`)
      await loadSavedTables()

      const csv = buildTableCsv(data)
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
      const name = selectedTaker?.name || 'taker'
      const safe = name.trim().replace(/[^A-Za-z0-9]+/g, '_').slice(0, 64)
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
      triggerBrowserDownload(blob, `${safe}_table_${period}_${ts}.csv`)
    } catch (e) {
      setTableStatus(String(e?.message || e))
    } finally {
      setIsGeneratingTable(false)
    }
  }

  async function generateChart(period = '24h', binSize = 5) {
    if (!selectedTaker) return
    setIsGeneratingTable(true)
    setTableStatus('Processando gráfico...')
    try {
      const qs = buildQuery({ 
        takerId: selectedTaker.id, 
        endLocal: normalizeDateTimeLocal(endLocal), 
        period, 
        binSize,
        _ts: Date.now() 
      })
      const res = await fetch(`/api/tables/generate?${qs}`)
      if (!res.ok) throw new Error(`Falha ao obter dados do gráfico (${res.status})`)
      const data = await res.json()
      
      let title = 'Gráfico de Relâmpagos'
      if (period === 'yesterday') title = 'Relâmpagos - Ontem (24h)'
      if (period === '3h') title = 'Relâmpagos - Últimas 3 Horas'
      if (period === '24h_now') title = 'Relâmpagos - Últimas 24 Horas'

      setChartData(data)
      setChartTitle(title)
      setChartModalOpen(true)
      setTableStatus('')
    } catch (e) {
      setTableStatus(String(e?.message || e))
    } finally {
      setIsGeneratingTable(false)
    }
  }

  function downloadCurrentTableCsv(type) {
    // If tableData exists, download it; otherwise just close menu
    if (!tableData?.values4x24?.length) return
    const csv = buildTableCsv(tableData)
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const name = selectedTaker?.name || 'taker'
    const safe = name.trim().replace(/[^A-Za-z0-9]+/g, '_').slice(0, 64)
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    triggerBrowserDownload(blob, `${safe}_table_${ts}.csv`)
  }

  // ─── Animation (preserved logic, adapted) ───
  function _buildFrameTimestamps(endLocalStr, hours) {
    const end = endLocalStr ? new Date(endLocalStr) : new Date()
    const step = 5
    const total = Math.min(3, Math.max(1, Number(hours) || 1)) * 60
    const count = Math.floor(total / step) + 1
    const stamps = []
    const startMs = end.getTime() - (count - 1) * step * 60 * 1000
    for (let i = 0; i < count; i++) {
      stamps.push(formatLocalIso(new Date(startMs + i * step * 60 * 1000)))
    }
    return stamps
  }

  async function fetchFrameForTs(ts, { full = false, hours = animHours } = {}) {
    if (!selectedTaker) return null
    try {
      const end = new Date(ts)
      const start = new Date(end.getTime() - Math.min(3, Math.max(1, Number(hours) || 1)) * 60 * 60 * 1000)
      const qs = buildQuery({
        takerId: selectedTaker.id, mode,
        startLocal: formatLocalIso(start), endLocal: ts,
        background: backgroundIr ? 1 : 0, initialLoadHours,
        thumb: full ? 0 : 1, _ts: Date.now(),
      })
      const res = await fetch(`/api/render/frame?${qs}`)
      if (!res.ok) return null
      return await res.blob()
    } catch { return null }
  }

  async function prefetchFrames(endLocalStr, hours) {
    setIsPrefetching(true)
    try {
      const stamps = _buildFrameTimestamps(endLocalStr, hours)
      const nextFrames = []
      for (const ts of stamps) {
        const existing = frames.find((f) => f.ts === ts)
        if (existing) { nextFrames.push(existing); continue }
        const blob = await fetchFrameForTs(ts, { full: false, hours })
        nextFrames.push({ ts, url: blob ? URL.createObjectURL(blob) : null })
      }
      frames.forEach((f) => { if (f?.url) try { URL.revokeObjectURL(f.url) } catch {} })
      setFrames(nextFrames)
      setFrameIndex(0)
    } finally {
      setIsPrefetching(false)
    }
  }

  function startAnimation() {
    if (!selectedTaker) return
    const endStr = normalizeDateTimeLocal(endLocal) || ''
    prefetchFrames(endStr, animHours)
    setAnimating(true)
  }

  function stopAnimation() { setAnimating(false) }

  function stepBack() {
    if (frames.length === 0) return
    setFrameIndex((i) => (i - 1 + frames.length) % frames.length)
  }

  function stepForward() {
    if (frames.length === 0) return
    setFrameIndex((i) => (i + 1) % frames.length)
  }

  async function downloadCurrentImage() {
    if (!selectedTaker) return
    const name = selectedTaker.name || 'taker'
    const safe = name.trim().replace(/[^A-Za-z0-9]+/g, '_').slice(0, 64)
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const filename = `${safe}_mode${mode}_${ts}.png`
    try {
      const effectiveStart = normalizeDateTimeLocal(startLocal) || formatLocalIso(new Date(Date.now() - DEFAULT_RENDER_HOURS * 3600000))
      const effectiveEnd = normalizeDateTimeLocal(endLocal) || formatLocalIso(new Date())
      const qs = buildQuery({
        takerId: selectedTaker.id, mode,
        startLocal: effectiveStart, endLocal: effectiveEnd,
        initialLoadHours, background: backgroundIr ? 1 : 0, _ts: Date.now(),
      })
      const res = await fetch(`/api/render?${qs}`)
      if (!res.ok) return
      const blob = await res.blob()
      triggerBrowserDownload(blob, filename)
    } catch (e) { console.error(e) }
  }

  // ─── Animation playback loop ───
  useEffect(() => {
    if (!animating || !frames.length) return
    const id = setInterval(() => {
      setFrameIndex((i) => (i + 1) % frames.length)
    }, 333) // ~3 fps
    return () => clearInterval(id)
  }, [animating, frames])

  // ─── Initial load ───
  useEffect(() => { loadTakers() }, [])

  useEffect(() => {
    if (takers.length === 0 || takerId) return
    loadDefaultTaker()
  }, [takers, takerId])

  useEffect(() => {
    if (!selectedTaker) return
    loadSavedTables()
    setLastUpdateLocal(new Date().toLocaleTimeString('pt-BR'))
  }, [takerId])

  // Current frame time for animation clock
  const animFrameTime = frames.length > 0 && frames[frameIndex]?.ts
    ? frames[frameIndex].ts
    : null

  return (
    <div className="lt-app">
      <Header onMenuToggle={() => setMenuOpen((v) => !v)} />

      <SideMenu
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        selectedTaker={selectedTaker}
        tableData={tableData}
        savedTables={savedTables}
        onGenerateTable={generateTable}
        onGenerateChart={generateChart}
        onOpenDataRequest={() => setDataRequestOpen(true)}
        onLoadSavedTable={loadSavedTable}
        onDownloadCsv={downloadCurrentTableCsv}
        isGeneratingTable={isGeneratingTable}
        tableStatus={tableStatus}
      />

      <DataRequestModal
        isOpen={dataRequestOpen}
        onClose={() => setDataRequestOpen(false)}
        selectedTaker={selectedTaker}
      />

      <ChartModal
        isOpen={chartModalOpen}
        onClose={() => setChartModalOpen(false)}
        data={chartData}
        title={chartTitle}
      />

      <main className="lt-main">
        {/* Map column */}
        <div className="lt-map-col">
          {showMap && (selectedTaker || String(takerId) === '0') ? (
            <LightningMap
              taker={selectedTaker}
              allTakers={takers}
              showAllTakers={String(takerId) === '0'}
              showRings={showRings}
              events={events}
              backgroundIr={backgroundIr}
              abiUrl={abiUrl}
              abiBounds={abiBounds}
              abiUtc={abiUtc}
              abiLoading={abiLoading}
              abiError={abiError}
              startLocal={startLocal}
              endLocal={endLocal}
              markerInterval={markerInterval}
              visMode={visMode}
              animating={animating}
              animFrameTime={animFrameTime}
              onPlay={startAnimation}
              onPause={stopAnimation}
              onStepBack={stepBack}
              onStepForward={stepForward}
              onDownloadImage={downloadCurrentImage}
              onDownloadAnim={() => {}}
              lastUpdateLocal={lastUpdateLocal}
              initialLoadHours={initialLoadHours}
            />
          ) : (
            <div className="lt-info-badge">
              {takersError || (takers.length === 0 ? 'Carregando tomadores...' : 'Selecione um tomador de serviço')}
            </div>
          )}

          {eventsLoading && selectedTaker && (
            <div className="lt-info-badge" style={{ top: '60%' }}>
              Carregando eventos...
            </div>
          )}

          {!eventsLoading && selectedTaker && events.length === 0 && (
            <div className="lt-info-badge lt-info-badge--warn" style={{ top: '60%' }}>
              Nenhum relâmpago encontrado no período selecionado
              <small style={{ display: 'block', marginTop: 6, opacity: 0.8, fontSize: 12 }}>
                Tente aumentar o intervalo de tempo
              </small>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <aside className="lt-sidebar">
          <ControlPanel
            takers={takerOptions}
            takerId={takerId}
            onTakerChange={(id) => setTakerId(id)}
            markerInterval={markerInterval}
            onMarkerIntervalChange={setMarkerInterval}
            visMode={visMode}
            onVisModeChange={setVisMode}
            startLocal={startLocal}
            onStartLocalChange={setStartLocal}
            endLocal={endLocal}
            onEndLocalChange={setEndLocal}
            backgroundIr={backgroundIr}
            onBackgroundIrChange={setBackgroundIr}
            showMap={showMap}
            onShowMapChange={setShowMap}
            showRings={showRings}
            onShowRingsChange={setShowRings}
          />

          {selectedTaker && selectedTaker.id !== 0 && (
            <StatsPanel
              stats={stats}
              startLocal={startLocal}
              endLocal={endLocal}
            />
          )}
        </aside>
      </main>
    </div>
  )
}

export default App
