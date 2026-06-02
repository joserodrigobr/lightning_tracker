import './styles/layout.css'

import { useEffect, useMemo, useRef, useState } from 'react'
import Header from './components/Header/Header'
import LightningMap from './components/LightningMap/LightningMap'
import ControlPanel from './components/ControlPanel/ControlPanel'
import StatsPanel from './components/StatsPanel/StatsPanel'
import SideMenu from './components/SideMenu/SideMenu'
import { useEvents } from './hooks/useEvents'
import { useNowcast } from './hooks/useNowcast'
import { useAbiOverlay } from './hooks/useAbiOverlay'
import DataRequestModal from './components/DataRequestModal/DataRequestModal'
import ChartModal from './components/ChartModal/ChartModal'
import TableModal from './components/TableModal/TableModal'
import AlertDashboard from './pages/AlertDashboard/AlertDashboard'
import {
  generateTableData,
  getActiveTaker,
  getLatestTables,
  getSavedTable,
  getTakers,
  renderAnimation,
  renderCurrentImage,
} from './services/lightningService'


const DEFAULT_RENDER_HOURS = 4
const DEFAULT_RENDER_MODE = 2
const DEFAULT_VIS_MODE = 'density'
const EVENTS_REFRESH_INTERVAL_MS = 60_000
const THEME_STORAGE_KEY = 'lightning-tracker-theme'

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
  const [mode, setMode] = useState(DEFAULT_RENDER_MODE)
  const [startLocal, setStartLocal] = useState('')
  const [endLocal, setEndLocal] = useState('')
  const [initialLoadHours] = useState(DEFAULT_RENDER_HOURS)
  const [backgroundIr, setBackgroundIr] = useState(false)
  const [showMap, setShowMap] = useState(true)
  const [showRings, setShowRings] = useState(true)
  const [showNowcast, setShowNowcast] = useState(false)

  const [markerInterval, setMarkerInterval] = useState(10)
  const [visMode, setVisMode] = useState(DEFAULT_VIS_MODE)
  const [menuOpen, setMenuOpen] = useState(false)
  const [mapSidebarOpen, setMapSidebarOpen] = useState(true)
  const [view, setView] = useState('map') // 'map' or 'alerts'
  const [theme, setTheme] = useState(() => {
    try {
      const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)
      return storedTheme === 'light' ? 'light' : 'dark'
    } catch {
      return 'dark'
    }
  })

  // Table state (preserved from original)
  const [tableData, setTableData] = useState(null)
  const [tableStatus, setTableStatus] = useState('')
  const [isGeneratingTable, setIsGeneratingTable] = useState(false)
  const [savedTables, setSavedTables] = useState([])

  const [dataRequestOpen, setDataRequestOpen] = useState(false)
  const [chartModalOpen, setChartModalOpen] = useState(false)
  const [chartData, setChartData] = useState(null)
  const [chartTitle, setChartTitle] = useState('')

  const [tableModalOpen, setTableModalOpen] = useState(false)
  const [tableTitle, setTableTitle] = useState('')
  const [animating, setAnimating] = useState(false)
  const [playbackTime, setPlaybackTime] = useState(null)
  const [accumulatedMode, setAccumulatedMode] = useState(false)
  const [playbackSpeed] = useState(1000) // ms per frame

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
  const { events, loading: eventsLoading, stats, lastFetchedAt } = useEvents({
    takerId,
    taker: selectedTaker,
    mode,
    startLocal: normalizeDateTimeLocal(startLocal),
    endLocal: normalizeDateTimeLocal(endLocal),
    initialLoadHours,
    refreshIntervalMs: EVENTS_REFRESH_INTERVAL_MS,
  })

  // ─── Nowcast hook ───
  const { nowcast } = useNowcast({
    takerId,
    refreshIntervalMs: 120_000, // Nowcast is heavier, update every 2 min
  })

  // ─── ABI overlay hook ───
  // Compute UTC reference from endLocal (BRT = UTC-3) or fall back to now
  const abiUtcIso = useMemo(() => {
    const refTime = (animating && playbackTime) ? new Date(playbackTime) : (endLocal ? new Date(endLocal) : new Date())
    // refTime is local (BRT, UTC-3); add 3h to get UTC
    const d = new Date(refTime)
    d.setHours(d.getHours() + 3)
    return d.toISOString()
  }, [endLocal, animating, playbackTime])

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
      const res = await getTakers()
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
    const res = await getActiveTaker()
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
      const res = await getLatestTables(qs)
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
      const res = await getSavedTable(qs)
      if (!res.ok) throw new Error(`Falha ao carregar tabela (${res.status})`)
      const data = await res.json()
      setTableData(data)
      setTableTitle(`Tabela: ${data?.fileName || relativePath}`)
      setTableModalOpen(true)
      setTableStatus(`Tabela carregada: ${data?.fileName || relativePath}`)
    } catch (e) {
      setTableStatus(String(e?.message || e))
    }
  }

  async function generateTable(period = '24h', binSize = 5, isDownload = false) {
    if (!selectedTaker) return
    setIsGeneratingTable(true)
    setTableStatus(isDownload ? 'Preparando download...' : 'Gerando tabela...')
    try {
      const qs = buildQuery({ 
        takerId: selectedTaker.id, 
        endLocal: normalizeDateTimeLocal(endLocal), 
        period, 
        binSize,
        _ts: Date.now() 
      })
      const res = await generateTableData(qs)
      if (!res.ok) throw new Error(`Falha ao gerar tabela (${res.status})`)
      const data = await res.json()
      
      setTableData(data)
      await loadSavedTables()

      if (isDownload) {
        const csv = buildTableCsv(data)
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
        const name = selectedTaker?.name || 'taker'
        const safe = name.trim().replace(/[^A-Za-z0-9]+/g, '_').slice(0, 64)
        const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
        triggerBrowserDownload(blob, `${safe}_table_${period}_${ts}.csv`)
        setTableStatus('Download concluído!')
      } else {
        let title = 'Tabela de Dados'
        if (period === 'yesterday') title = 'Relatório - Ontem (24h)'
        if (period === '3h') title = 'Relatório - Últimas 3 Horas'
        
        setTableTitle(title)
        setTableModalOpen(true)
        setTableStatus('Tabela carregada na visualização web!')
      }
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
      const res = await generateTableData(qs)
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

  function downloadCurrentTableCsv() {
    // If tableData exists, download it; otherwise just close menu
    if (!tableData?.values4x24?.length) return
    const csv = buildTableCsv(tableData)
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const name = selectedTaker?.name || 'taker'
    const safe = name.trim().replace(/[^A-Za-z0-9]+/g, '_').slice(0, 64)
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    triggerBrowserDownload(blob, `${safe}_table_${ts}.csv`)
  }

  // ─── Animation (Dynamic Playback) ───

  function startAnimation() {
    if (!selectedTaker) return
    const start = startLocal ? new Date(startLocal).getTime() : Date.now() - (initialLoadHours || 4) * 3600000
    setPlaybackTime(start)
    setAnimating(true)
  }

  function stopAnimation() { setAnimating(false) }

  function stepBack() {
    const intervalMs = (markerInterval || 10) * 60000
    setPlaybackTime((prev) => (prev || Date.now()) - intervalMs)
  }

  function stepForward() {
    const intervalMs = (markerInterval || 10) * 60000
    setPlaybackTime((prev) => (prev || Date.now()) + intervalMs)
  }

  function resetFilters() {
    setAnimating(false)
    setPlaybackTime(null)
    setStartLocal('')
    setEndLocal('')
    setMode(DEFAULT_RENDER_MODE)
    setVisMode(DEFAULT_VIS_MODE)
    setMarkerInterval(10)
    setAccumulatedMode(true)
    setBackgroundIr(false)
    setShowNowcast(false)
  }

  function changeVisMode(nextVisMode) {
    setVisMode(nextVisMode)
    setMode(nextVisMode === 'density' ? 2 : 1)
  }

  function toggleTheme() {
    setTheme((currentTheme) => (currentTheme === 'dark' ? 'light' : 'dark'))
  }

  function changeTaker(nextTakerId) {
    setTakerId(nextTakerId)
  }

  async function downloadCurrentImage() {
    if (!selectedTaker) return
    const name = selectedTaker.name || 'taker'
    const safe = name.trim().replace(/[^A-Za-z0-9]+/g, '_').slice(0, 64)
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const filename = `${safe}_mapa_${ts}.png`
    try {
      const effectiveStart = normalizeDateTimeLocal(startLocal) || formatLocalIso(new Date(Date.now() - DEFAULT_RENDER_HOURS * 3600000))
      const effectiveEnd = normalizeDateTimeLocal(endLocal) || formatLocalIso(new Date())
      const qs = buildQuery({
        takerId: selectedTaker.id, 
        mode,
        startLocal: effectiveStart, 
        endLocal: effectiveEnd,
        initialLoadHours, 
        background: backgroundIr ? 1 : 0, 
        binMinutes: markerInterval || 10,
        showPolygon: 0, // Clean look as requested
        _ts: Date.now(),
      })
      const res = await renderCurrentImage(qs)
      if (!res.ok) return
      const blob = await res.blob()
      triggerBrowserDownload(blob, filename)
    } catch (e) { console.error(e) }
  }

  async function downloadAnimation() {
    if (!selectedTaker) return
    const name = selectedTaker.name || 'taker'
    const safe = name.trim().replace(/[^A-Za-z0-9]+/g, '_').slice(0, 64)
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const filename = `${safe}_animacao_${ts}.mp4`
    
    // Notify user - animation takes time
    const originalText = 'Processando animação...'
    console.log(originalText)
    
    try {
      const effectiveStart = normalizeDateTimeLocal(startLocal) || formatLocalIso(new Date(Date.now() - DEFAULT_RENDER_HOURS * 3600000))
      const effectiveEnd = normalizeDateTimeLocal(endLocal) || formatLocalIso(new Date())
      
      const qs = buildQuery({
        takerId: selectedTaker.id, 
        mode,
        startLocal: effectiveStart, 
        endLocal: effectiveEnd,
        binMinutes: markerInterval || 10,
        showPolygon: 0,
        _ts: Date.now(),
      })
      
      const res = await renderAnimation(qs)
      if (!res.ok) {
        alert('Erro ao gerar animação. Verifique se o período não é muito longo.')
        return
      }
      const blob = await res.blob()
      triggerBrowserDownload(blob, filename)
    } catch (e) { 
      console.error(e)
      alert('Falha na conexão ao gerar animação.')
    }
  }

  // ─── Animation playback loop ───
  useEffect(() => {
    if (!animating) return
    
    const intervalMin = markerInterval || 10
    const startMs = startLocal ? new Date(startLocal).getTime() : Date.now() - (initialLoadHours || 4) * 3600000
    const endMs = endLocal ? new Date(endLocal).getTime() : Date.now()

    const id = setInterval(() => {
      setPlaybackTime(prev => {
        const next = (prev || startMs) + intervalMin * 60000
        return next > endMs ? startMs : next
      })
    }, playbackSpeed)

    return () => clearInterval(id)
  }, [animating, markerInterval, startLocal, endLocal, initialLoadHours, playbackSpeed])

  // ─── Initial load ───
  useEffect(() => { loadTakers() }, [])

  useEffect(() => {
    if (takers.length === 0 || takerId) return
    loadDefaultTaker()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takers, takerId])

  useEffect(() => {
    if (!selectedTaker) return
    loadSavedTables()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takerId])

  useEffect(() => {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
      // Ignore storage errors; theme still works for the current session.
    }
  }, [theme])



  return (
    <div className={`lt-app lt-theme-${theme}`}>
      <Header
        onMenuToggle={() => setMenuOpen((v) => !v)}
        theme={theme}
        onThemeToggle={toggleTheme}
      />

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
        view={view}
        onViewChange={setView}
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

      <TableModal
        isOpen={tableModalOpen}
        onClose={() => setTableModalOpen(false)}
        data={tableData}
        title={tableTitle}
      />

      <main className="lt-main">
        {view === 'alerts' ? (
          <AlertDashboard />
        ) : (
          <>
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
                  playbackTime={playbackTime}
                  accumulatedMode={accumulatedMode}
                  onPlay={startAnimation}
                  onPause={stopAnimation}
                  onStepBack={stepBack}
                  onStepForward={stepForward}
                  onDownloadImage={downloadCurrentImage}
                  onDownloadAnim={downloadAnimation}
                  lastUpdateAt={lastFetchedAt}
                  refreshIntervalMs={EVENTS_REFRESH_INTERVAL_MS}
                  initialLoadHours={initialLoadHours}
                  nowcast={nowcast}
                  showNowcast={showNowcast}
                  theme={theme}
                  onTakerSelect={changeTaker}
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
            <button
              type="button"
              className={`lt-sidebar-toggle ${mapSidebarOpen ? 'lt-sidebar-toggle--open' : 'lt-sidebar-toggle--closed'}`}
              onClick={() => setMapSidebarOpen((open) => !open)}
              aria-expanded={mapSidebarOpen}
              aria-controls="lt-map-sidebar"
              title={mapSidebarOpen ? 'Recolher painel' : 'Abrir painel'}
            >
              <span aria-hidden="true">{mapSidebarOpen ? '›' : '‹'}</span>
            </button>

            <aside
              id="lt-map-sidebar"
              className={`lt-sidebar ${mapSidebarOpen ? 'lt-sidebar--open' : 'lt-sidebar--closed'}`}
              aria-hidden={!mapSidebarOpen}
            >
              <ControlPanel
                takers={takerOptions}
                takerId={takerId}
                onTakerChange={changeTaker}
                markerInterval={markerInterval}
                onMarkerIntervalChange={setMarkerInterval}
                visMode={visMode}
                onVisModeChange={changeVisMode}
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
                accumulatedMode={accumulatedMode}
                onAccumulatedModeChange={setAccumulatedMode}
                showNowcast={showNowcast}
                onShowNowcastChange={setShowNowcast}
                onReset={resetFilters}
                animating={animating}
              />

              {selectedTaker && selectedTaker.id !== 0 && (
                <StatsPanel
                  stats={stats}
                  startLocal={startLocal}
                  endLocal={endLocal}
                />
              )}
            </aside>
          </>
        )}
      </main>
    </div>
  )
}

export default App
