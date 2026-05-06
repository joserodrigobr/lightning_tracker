import './App.css'

import { useEffect, useMemo, useRef, useState } from 'react'

const DEFAULT_RENDER_HOURS = 3

const MODES = [
  { value: 1, label: 'Flashes (markers coloridos por tempo)' },
  { value: 2, label: 'Flashes (densidade)' },
  { value: 3, label: 'Eventos (espacialização cinza)' },
  { value: 4, label: 'Eventos (densidade)' },
]

function normalizeDateTimeLocal(value) {
  if (!value) return ''
  // datetime-local usually comes as YYYY-MM-DDTHH:MM
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

function formatWindowLabel(startLocal, endLocal) {
  const startLabel = startLocal || `Últimas ${DEFAULT_RENDER_HOURS}h (dinâmico)`
  const endLabel = endLocal || 'agora'
  return `${startLabel} → ${endLabel}`
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

function getRollingRenderWindow(hours = DEFAULT_RENDER_HOURS) {
  const safeHours = Math.min(3, Math.max(1, Number(hours) || DEFAULT_RENDER_HOURS))
  const end = new Date()
  const start = new Date(end.getTime() - safeHours * 60 * 60 * 1000)
  return {
    startLocal: formatLocalIso(start),
    endLocal: formatLocalIso(end),
    initialLoadHours: safeHours,
  }
}

function getModeLabel(mode) {
  return MODES.find((item) => item.value === mode)?.label || `Modo ${mode}`
}

function toIntOrDash(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? String(parsed) : '—'
}

function formatDataSourceLabel(value) {
  if (!value) return 'Origem indisponível'
  return value === 'Postgres' ? 'Postgres' : 'S3 fallback'
}

function formatSavedTableLabel(item) {
  if (!item) return ''
  const saved = item.savedAtLocal || item.lastWriteLocal || ''
  return saved ? `${saved} · ${item.fileName}` : item.fileName || item.relativePath || ''
}

function csvCell(value) {
  return String(value ?? '').replace(/"/g, '""')
}

function buildTableCsv(tableData) {
  const hourLabels = Array.isArray(tableData?.hourLabels) ? tableData.hourLabels : []
  const radiiLabels = Array.isArray(tableData?.radiiLabels) ? tableData.radiiLabels : []
  const values = Array.isArray(tableData?.values4x24) ? tableData.values4x24 : []

  const lines = []
  lines.push(['Anel \ Tempo', ...hourLabels].map((cell) => `"${csvCell(cell)}"`).join(';'))

  radiiLabels.forEach((label, rowIndex) => {
    const row = Array.isArray(values[rowIndex]) ? values[rowIndex] : []
    const cells = [label, ...hourLabels.map((_, colIndex) => row[colIndex] ?? 0)]
    lines.push(cells.map((cell) => `"${csvCell(cell)}"`).join(';'))
  })

  return `${lines.join('\r\n')}\r\n`
}

function App() {
  const [takers, setTakers] = useState([])
  const [takersError, setTakersError] = useState('')
  const isLoadingTakersRef = useRef(false)

  const [takerId, setTakerId] = useState('')
  const [mode, setMode] = useState(1)

  // Empty means use the rolling default window (last 3h -> now)
  const [startLocal, setStartLocal] = useState('')
  const [endLocal, setEndLocal] = useState('')
  const [initialLoadHours, setInitialLoadHours] = useState(DEFAULT_RENDER_HOURS)
  const [backgroundIr, setBackgroundIr] = useState(false)

  const [plotUrl, setPlotUrl] = useState('')
  const plotUrlRef = useRef('')
  const [statusText, setStatusText] = useState('')
  const [animating, setAnimating] = useState(false)
  const [frames, setFrames] = useState([]) // array of {ts, url}
  const [frameIndex, setFrameIndex] = useState(0)
  const [isPrefetching, setIsPrefetching] = useState(false)
  const [animHours, setAnimHours] = useState(1) // 1..3
  const [lastUpdateLocal, setLastUpdateLocal] = useState('')
  const [isRendering, setIsRendering] = useState(false)
  const [renderError, setRenderError] = useState('')
  const [renderMeta, setRenderMeta] = useState({})
  const [tableData, setTableData] = useState(null)
  const [tableStatus, setTableStatus] = useState('')
  const [tableError, setTableError] = useState('')
  const [isGeneratingTable, setIsGeneratingTable] = useState(false)
  const [savedTables, setSavedTables] = useState([])
  const [savedTablesError, setSavedTablesError] = useState('')
  const [savedTablesLoading, setSavedTablesLoading] = useState(false)
  const [selectedSavedTable, setSelectedSavedTable] = useState('')
  const [timeViewMode, setTimeViewMode] = useState('window')
  const autoSelectRequestedRef = useRef(false)
  const renderInFlightRef = useRef(false)

  const selectedTaker = useMemo(() => {
    if (!takerId) return null
    return takers.find((t) => String(t.id) === String(takerId)) || null
  }, [takers, takerId])

  const selectedTakerLabel = selectedTaker
    ? selectedTaker.name
    : takerId
      ? `Tomador ${takerId}`
      : 'Nenhum tomador selecionado'

  const renderWindowLabel = useMemo(
    () => formatWindowLabel(startLocal, endLocal),
    [startLocal, endLocal]
  )

  const modeLabel = useMemo(() => getModeLabel(mode), [mode])
  const effectiveWindowLabel = useMemo(() => {
    if (renderMeta.plotStartLocal || renderMeta.plotEndLocal) {
      const startLabel = renderMeta.plotStartLocal || renderWindowLabel.split(' → ')[0]
      const endLabel = renderMeta.plotEndLocal || renderWindowLabel.split(' → ')[1]
      return `${startLabel} → ${endLabel}`
    }
    return renderWindowLabel
  }, [renderMeta.plotEndLocal, renderMeta.plotStartLocal, renderWindowLabel])

  const headerTimeLabel = useMemo(() => {
    if (timeViewMode === 'update') {
      return lastUpdateLocal ? `Atualizado às ${lastUpdateLocal}` : 'Atualização indisponível'
    }

    return `Janela: ${effectiveWindowLabel}`
  }, [effectiveWindowLabel, lastUpdateLocal, timeViewMode])

  const sourceLabel = useMemo(() => formatDataSourceLabel(renderMeta.dataSource), [renderMeta.dataSource])
  const sourceClassName = renderMeta.dataSource === 'Postgres'
    ? 'sourceBadge sourceBadgeDb'
    : 'sourceBadge sourceBadgeFallback'

  function resetView() {
    setTimeViewMode('window')
  }

  function toggleTimeView() {
    setTimeViewMode((current) => (current === 'window' ? 'update' : 'window'))
  }

  function getEffectiveRenderParams() {
    const explicitStart = normalizeDateTimeLocal(startLocal)
    const explicitEnd = normalizeDateTimeLocal(endLocal)

    if (explicitStart && explicitEnd) {
      return {
        startLocal: explicitStart,
        endLocal: explicitEnd,
        initialLoadHours: Math.min(3, Math.max(1, Number(initialLoadHours) || DEFAULT_RENDER_HOURS)),
      }
    }

    return getRollingRenderWindow(DEFAULT_RENDER_HOURS)
  }

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
    if (autoSelectRequestedRef.current || takerId) return
    autoSelectRequestedRef.current = true
    try {
      const res = await fetch('/api/takers/active')
      if (!res.ok) throw new Error(`Falha ao calcular tomador ativo (${res.status})`)
      const data = await res.json()
      if (data?.takerId) {
        setTakerId(String(data.takerId))
      }
    } catch {
      if (takers.length > 0 && !takerId) {
        setTakerId(String(takers[0].id))
      }
    }
  }

  async function loadSavedTables() {
    if (!selectedTaker) return
    setSavedTablesLoading(true)
    setSavedTablesError('')
    try {
      const qs = buildQuery({
        takerId: selectedTaker.id,
        limit: 8,
        _ts: Date.now(),
      })
      const res = await fetch(`/api/tables/latest?${qs}`)
      if (!res.ok) throw new Error(`Falha ao listar tabelas salvas (${res.status})`)
      const data = await res.json()
      const next = Array.isArray(data) ? data : []
      setSavedTables(next)
      if (next.length > 0) {
        const currentPath = selectedSavedTable || ''
        const stillValid = currentPath && next.some((item) => item.relativePath === currentPath)
        if (!stillValid) {
          await loadSavedTable(next[0].relativePath, true)
        }
      } else {
        setSelectedSavedTable('')
        if (!tableData) {
          setTableStatus('Nenhuma tabela salva para este tomador.')
        }
      }
    } catch (e) {
      setSavedTablesError(String(e?.message || e))
    } finally {
      setSavedTablesLoading(false)
    }
  }

  async function loadSavedTable(relativePath, fromAutoLoad = false) {
    if (!relativePath) return
    setTableError('')
    if (!fromAutoLoad) setTableStatus('Carregando tabela salva...')
    try {
      const qs = buildQuery({
        relativePath,
        _ts: Date.now(),
      })
      const res = await fetch(`/api/tables/load?${qs}`)
      if (!res.ok) throw new Error(`Falha ao carregar tabela (${res.status})`)
      const data = await res.json()
      setTableData(data)
      setSelectedSavedTable(data?.relativePath || relativePath)
      setTableStatus(fromAutoLoad ? '' : `Tabela carregada: ${data?.fileName || relativePath}`)
    } catch (e) {
      const message = String(e?.message || e)
      setTableStatus(message)
      setTableError(message)
    }
  }

  async function generateTable() {
    if (!selectedTaker) return
    setIsGeneratingTable(true)
    setTableError('')
    setTableStatus('Gerando tabela 4x288...')
    try {
      const qs = buildQuery({
        takerId: selectedTaker.id,
        endLocal: normalizeDateTimeLocal(endLocal),
        _ts: Date.now(),
      })
      const res = await fetch(`/api/tables/generate?${qs}`)
      if (!res.ok) throw new Error(`Falha ao gerar tabela (${res.status})`)
      const data = await res.json()
      setTableData(data)
      setSelectedSavedTable(data?.csvRelativePath || '')
      setTableStatus(`Tabela gerada e salva: ${data?.csvPath || ''}`)
      await loadSavedTables()
    } catch (e) {
      const message = String(e?.message || e)
      setTableStatus(message)
      setTableError(message)
    } finally {
      setIsGeneratingTable(false)
    }
  }

  function setPlotBlob(blob) {
    const nextUrl = URL.createObjectURL(blob)
    if (plotUrlRef.current) {
      try {
        URL.revokeObjectURL(plotUrlRef.current)
      } catch {
        // ignore
      }
    }
    plotUrlRef.current = nextUrl
    setPlotUrl(nextUrl)
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

  async function refreshPlot() {
    if (!selectedTaker) return
    if (renderInFlightRef.current) return
    renderInFlightRef.current = true
    setIsRendering(true)
    setRenderError('')
    setStatusText('Atualizando...')
    const requestController = new AbortController()
    const requestTimeoutMs = 90000
    const requestTimeoutId = window.setTimeout(() => requestController.abort(), requestTimeoutMs)
    try {
      const effectiveRenderParams = getEffectiveRenderParams()
      const qs = buildQuery({
        takerId: selectedTaker.id,
        mode,
        startLocal: effectiveRenderParams.startLocal,
        endLocal: effectiveRenderParams.endLocal,
        initialLoadHours: effectiveRenderParams.initialLoadHours,
        background: backgroundIr ? 1 : 0,
        _ts: Date.now(),
      })

      const res = await fetch(`/api/render?${qs}`, { signal: requestController.signal })
      if (!res.ok) throw new Error(`Falha ao renderizar (${res.status})`)
      const blob = await res.blob()
      setPlotBlob(blob)

      const hdr = res.headers.get('X-Last-Update-Local')
      if (hdr) {
        setLastUpdateLocal(hdr)
      } else {
        setLastUpdateLocal(new Date().toLocaleTimeString())
      }

      setRenderMeta({
        plotStartLocal: res.headers.get('X-Plot-Start-Local') || '',
        plotEndLocal: res.headers.get('X-Plot-End-Local') || '',
        flashesCount: res.headers.get('X-Flashes-Count') || '',
        eventsCount: res.headers.get('X-Events-Count') || '',
        mode: res.headers.get('X-Mode') || '',
        dynamicStart: res.headers.get('X-Dynamic-Start') || '',
        dynamicEnd: res.headers.get('X-Dynamic-End') || '',
        initialLoadHours: res.headers.get('X-Initial-Load-Hours') || '',
        background: res.headers.get('X-Background') || '',
      })

      setStatusText('')
    } catch (e) {
      const message = e?.name === 'AbortError'
        ? `Render demorou mais que ${Math.floor(requestTimeoutMs / 1000)}s.`
        : String(e?.message || e)
      setStatusText(message)
      setRenderError(message)
    } finally {
      window.clearTimeout(requestTimeoutId)
      renderInFlightRef.current = false
      setIsRendering(false)
    }
  }

  function _buildFrameTimestamps(endLocalStr, hours) {
    // endLocalStr expected as 'YYYY-MM-DDTHH:MM:SS' or empty (use now)
    const end = endLocalStr ? new Date(endLocalStr) : new Date()
    const step = 5 // minutes
    const total = Math.min(3, Math.max(1, Number(hours) || 1)) * 60 // minutes
    const count = Math.floor(total / step) + 1
    const stamps = []
    const startMs = end.getTime() - (count - 1) * step * 60 * 1000
    for (let i = 0; i < count; i++) {
      const dt = new Date(startMs + i * step * 60 * 1000)
      stamps.push(formatLocalIso(dt))
    }
    return stamps
  }

  async function fetchFrameForTs(ts, { full = false, hours = animHours } = {}) {
    if (!selectedTaker) return null
    try {
      const end = new Date(ts)
      const start = new Date(end.getTime() - Math.min(3, Math.max(1, Number(hours) || 1)) * 60 * 60 * 1000)
      const qs = buildQuery({
        takerId: selectedTaker.id,
        mode,
        startLocal: formatLocalIso(start),
        endLocal: ts,
        background: backgroundIr ? 1 : 0,
        initialLoadHours,
        thumb: full ? 0 : 1,
        _ts: Date.now(),
      })
      const res = await fetch(`/api/render/frame?${qs}`)
      if (!res.ok) throw new Error(`Falha ao renderizar frame (${res.status})`)
      const blob = await res.blob()
      return blob
    } catch (e) {
      console.error('fetchFrameForTs error', e)
      return null
    }
  }

  async function prefetchFrames(endLocalStr, hours) {
    setIsPrefetching(true)
    try {
      const stamps = _buildFrameTimestamps(endLocalStr, hours)
      const nextFrames = []
      for (let i = 0; i < stamps.length; i++) {
        const ts = stamps[i]
        // If already cached, reuse
        const existing = frames.find((f) => f.ts === ts)
        if (existing) {
          nextFrames.push(existing)
          continue
        }
        const blob = await fetchFrameForTs(ts, { full: false, hours })
        if (!blob) {
          nextFrames.push({ ts, url: null })
          continue
        }
        const url = URL.createObjectURL(blob)
        nextFrames.push({ ts, url })
      }
      // revoke old frames
      frames.forEach((f) => {
        if (f && f.url) try { URL.revokeObjectURL(f.url) } catch {} 
      })
      setFrames(nextFrames)
      setFrameIndex(0)
    } finally {
      setIsPrefetching(false)
    }
  }

  function startAnimation() {
    if (!selectedTaker) return
    // build stamps based on current endLocal or now
    const endStr = normalizeDateTimeLocal(endLocal) || ''
    prefetchFrames(endStr || '', animHours)
    setAnimating(true)
  }

  function stopAnimation() {
    setAnimating(false)
    refreshPlot()
  }

  async function saveCurrentFrame() {
    const cur = frames[frameIndex]
    const ts = cur?.ts || normalizeDateTimeLocal(endLocal)
    if (!ts) return
    try {
      const blob = await fetchFrameForTs(ts, { full: true, hours: animHours })
      if (!blob) return
      const name = selectedTaker?.name ? String(selectedTaker.name) : 'taker'
      const safe = name.trim().replace(/[^A-Za-z0-9]+/g, '_').slice(0, 64)
      const tsSafe = ts.replace(/[:.]/g, '-')
      const filename = `${safe || 'taker'}_frame_${tsSafe}.png`
      triggerBrowserDownload(blob, filename)
    } catch (e) {
      console.error(e)
    }
  }

  async function downloadCurrentImage() {
    if (!selectedTaker) return
    const name = selectedTaker?.name ? String(selectedTaker.name) : 'taker'
    const safe = name
      .trim()
      .replace(/[^A-Za-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 64)
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const filename = `${safe || 'taker'}_mode${mode}_${ts}.png`

    try {
      let blob = null
      if (animating && frames.length > 0 && frames[frameIndex]?.ts) {
        blob = await fetchFrameForTs(frames[frameIndex].ts, { full: true, hours: animHours })
      } else {
        const effectiveRenderParams = getEffectiveRenderParams()
        const qs = buildQuery({
          takerId: selectedTaker.id,
          mode,
          startLocal: effectiveRenderParams.startLocal,
          endLocal: effectiveRenderParams.endLocal,
          initialLoadHours: effectiveRenderParams.initialLoadHours,
          background: backgroundIr ? 1 : 0,
          _ts: Date.now(),
        })
        const res = await fetch(`/api/render?${qs}`)
        if (!res.ok) throw new Error(`Falha ao renderizar para download (${res.status})`)
        blob = await res.blob()
      }
      if (blob) triggerBrowserDownload(blob, filename)
    } catch (e) {
      console.error(e)
    }
  }

  function downloadCurrentTableCsv() {
    if (!tableData?.values4x24?.length) return

    const csv = buildTableCsv(tableData)
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })

    const name = selectedTaker?.name ? String(selectedTaker.name) : 'taker'
    const safe = name
      .trim()
      .replace(/[^A-Za-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 64)
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const filename = `${safe || 'taker'}_table_${ts}.csv`

    triggerBrowserDownload(blob, filename)
  }

  useEffect(() => {
    loadTakers()
    // cleanup blob url
    return () => {
      if (plotUrlRef.current) {
        try {
          URL.revokeObjectURL(plotUrlRef.current)
        } catch {
          // ignore
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (takers.length > 0) return
    if (!takersError) return
    const id = window.setTimeout(() => {
      loadTakers()
    }, 5000)
    return () => window.clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takersError, takers.length])

  useEffect(() => {
    if (takers.length === 0 || takerId) return
    loadDefaultTaker()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takers, takerId])

  useEffect(() => {
    if (!selectedTaker) return
    refreshPlot()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takerId, mode, startLocal, endLocal, initialLoadHours, backgroundIr])

  // Animation playback loop
  useEffect(() => {
    if (!animating) return
    if (!frames || frames.length === 0) return
    const fps = 3
    const interval = 1000 / fps
    let idx = frameIndex
    const id = setInterval(() => {
      idx = (idx + 1) % frames.length
      setFrameIndex(idx)
      const f = frames[idx]
      if (f && f.url) {
        if (plotUrlRef.current) try { URL.revokeObjectURL(plotUrlRef.current) } catch {}
        plotUrlRef.current = f.url
        setPlotUrl(f.url)
      }
    }, interval)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [animating, frames])

  useEffect(() => {
    if (!selectedTaker) return
    setTableData(null)
    setTableStatus('')
    setTableError('')
    setSavedTables([])
    setSavedTablesError('')
    setSelectedSavedTable('')
    loadSavedTables()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takerId])

  useEffect(() => {
    if (!selectedTaker) return
    const id = window.setInterval(() => {
      refreshPlot()
    }, 5 * 60 * 1000)
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [takerId, mode, startLocal, endLocal, initialLoadHours, backgroundIr])

  return (
    <div className="appShell">
      <header className="topBar">
        <div className="topBarBrand">
          <img className="topBarLogo" src="/logo.png" alt="BlueOcean" />
          <div className="topBarBrandText">
            <span className="topBarEyebrow">BlueOcean</span>
            <strong>VISUALIZADOR DE RAIOS</strong>
          </div>
        </div>

        <div className="topBarActions" aria-label="Ações de visualização">
          <button type="button" className="topBarButton" onClick={resetView}>
            Redefinir
          </button>
          <button type="button" className="topBarButton" onClick={toggleTimeView}>
            Horário
            <span className="topBarButtonValue">{timeViewMode === 'window' ? 'Janela' : 'Atualização'}</span>
          </button>
        </div>
      </header>

      <main className="dashboard">
        <section className="primaryColumn" aria-label="Painel principal">
          <article className="panel panelHero">
            <div className="panelHeader panelHeaderSplit">
              <div>
                <span className="eyebrow">Visualização de Raios</span>
                <span className="panelSubline">{selectedTakerLabel} · {modeLabel}</span>
              </div>

              <div className="heroMetaPills">
                <span className="metaPill">{headerTimeLabel}</span>
              </div>
            </div>

            <div className="plotStage">
              {plotUrl ? <div className={sourceClassName}>{sourceLabel}</div> : null}
              {plotUrl ? (
                <img
                  className="plotImg"
                  src={plotUrl}
                  alt="Mapa de flashes e eventos"
                  draggable={false}
                />
              ) : (
                <div className={`plotPlaceholder ${isRendering ? 'plotPlaceholderLoading' : ''}`}>
                  <div className="plotPlaceholderCard">
                    <strong>
                      {renderError || takersError || (isRendering ? 'Renderizando...' : 'Aguardando render...')}
                    </strong>
                    <span>{selectedTakerLabel}</span>
                    <span>{renderWindowLabel}</span>
                  </div>
                </div>
              )}

              {isRendering && plotUrl ? <div className="plotOverlay">Atualizando imagem...</div> : null}
            </div>

            <div className="panelFooterControls">
              <button className="footerButton" type="button" onClick={() => (animating ? stopAnimation() : startAnimation())}>
                {animating ? 'Pausar animação' : 'Reproduzir animação'}
              </button>

              <label className="footerField footerFieldInline" htmlFor="animHours">
                <span>Duração (h)</span>
                <select id="animHours" value={animHours} onChange={(e) => setAnimHours(Number(e.target.value))}>
                  <option value={1}>1</option>
                  <option value={2}>2</option>
                  <option value={3}>3</option>
                </select>
              </label>

              <button className="footerButton footerButtonSecondary" type="button" onClick={saveCurrentFrame} disabled={!frames.length}>
                Salvar frame
              </button>

              <div className="animStatus compact">
                {isPrefetching ? 'Preparando frames...' : frames.length ? `${frameIndex + 1}/${frames.length} • ${frames[frameIndex]?.ts || ''}` : ''}
              </div>
            </div>
          </article>

          <section className="panel panelSummary" aria-label="Resumo do render">
            <div className="panelHeader">
              <span className="eyebrow">Detalhes do parâmetro</span>
              <strong>Resumo do render</strong>
            </div>

            <div className="summaryGrid">
              <div className="summaryItem">
                <span className="summaryLabel">Tomador</span>
                <strong>{selectedTakerLabel}</strong>
              </div>
              <div className="summaryItem">
                <span className="summaryLabel">Janela efetiva</span>
                <strong>{effectiveWindowLabel}</strong>
              </div>
              <div className="summaryItem">
                <span className="summaryLabel">Modo</span>
                <strong>{renderMeta.mode ? getModeLabel(Number(renderMeta.mode)) : modeLabel}</strong>
              </div>
              <div className="summaryItem">
                <span className="summaryLabel">Overlay IR</span>
                <strong>{renderMeta.background === '1' ? 'Ativo' : backgroundIr ? 'Ativo' : 'Desativado'}</strong>
              </div>
              <div className="summaryItem">
                <span className="summaryLabel">Origem dos dados</span>
                <strong>{sourceLabel}</strong>
              </div>
              <div className="summaryItem">
                <span className="summaryLabel">Flashes renderizados</span>
                <strong>{toIntOrDash(renderMeta.flashesCount)}</strong>
              </div>
              <div className="summaryItem">
                <span className="summaryLabel">Eventos renderizados</span>
                <strong>{toIntOrDash(renderMeta.eventsCount)}</strong>
              </div>
              <div className="summaryItem">
                <span className="summaryLabel">Carga inicial</span>
                <strong>{renderMeta.initialLoadHours ? `${renderMeta.initialLoadHours}h` : `${initialLoadHours}h`}</strong>
              </div>
              <div className="summaryItem">
                <span className="summaryLabel">Atualização dinâmica</span>
                <strong>{renderMeta.dynamicStart === '1' || renderMeta.dynamicEnd === '1' ? 'Sim' : 'Não'}</strong>
              </div>
            </div>
          </section>

          <section className="panel panelTable" aria-label="Tabela 4x288">
            <div className="panelHeader panelHeaderSplit">
              <div>
                <span className="eyebrow">Dados tabulares</span>
                <strong>Tabela 4x288 (5 min)</strong>
                <span className="panelSubline">{tableData?.fileName ? `${tableData.fileName}` : selectedTakerLabel}</span>
              </div>

              {tableData?.savedAtLocal ? <span className="panelBadge">Salva em {tableData.savedAtLocal}</span> : null}
            </div>

            {tableData?.values4x24?.length ? (
              <div className="tableScroll">
                <table className="tableGrid">
                  <thead>
                    <tr>
                      <th className="tableCorner">Anel \ Hora</th>
                      {(tableData.hourLabels || []).map((hour) => (
                        <th key={hour}>{hour}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(tableData.values4x24 || []).map((row, rowIndex) => (
                      <tr key={`${tableData.radiiLabels?.[rowIndex] || rowIndex}`}>
                        <th>{tableData.radiiLabels?.[rowIndex] || `Linha ${rowIndex + 1}`}</th>
                        {(tableData.hourLabels || []).map((hour, colIndex) => (
                          <td key={`${hour}-${colIndex}`}>{row?.[colIndex] ?? 0}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="tableEmpty">
                <span>Gere uma tabela ou selecione uma tabela salva para visualizar os valores 4x24.</span>
              </div>
            )}
          </section>
        </section>

        <aside className="sidebarColumn" aria-label="Controles">
          <section className="panel panelConfig">
            <div className="panelHeader">
              <span className="eyebrow">Configuração</span>
              <strong>CONFIGURAÇÃO DE CONSULTA</strong>
            </div>

            <div className="controlStack">
              <label className="fieldBlock" htmlFor="taker">
                <span>Tomador de Serviço</span>
                <div className="selectWrap">
                  <select id="taker" value={takerId} onChange={(e) => setTakerId(e.target.value)}>
                    {takers.map((t) => (
                      <option key={t.id} value={String(t.id)}>{t.name}</option>
                    ))}
                  </select>
                </div>
              </label>

              <label className="fieldBlock" htmlFor="mode">
                <span>Tipo de Imagem</span>
                <div className="selectWrap">
                  <select id="mode" value={mode} onChange={(e) => setMode(Number(e.target.value))}>
                    {MODES.map((m) => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </select>
                </div>
              </label>

              <div className="splitInputs">
                <label className="fieldBlock" htmlFor="start">
                  <span>Tempo inicial</span>
                  <input id="start" type="datetime-local" value={startLocal} onChange={(e) => setStartLocal(e.target.value)} />
                </label>

                <label className="fieldBlock" htmlFor="end">
                  <span>Tempo final</span>
                  <input id="end" type="datetime-local" value={endLocal} onChange={(e) => setEndLocal(e.target.value)} />
                </label>
              </div>

              <label className="fieldBlock fieldBlockToggle">
                <div className="toggleCopy">
                  <span>Overlay IR (ABI C13)</span>
                  <small>Camada infravermelha do fundo de satélite.</small>
                </div>
                <div className="toggleSwitchWrap">
                  <input type="checkbox" checked={backgroundIr} onChange={(e) => setBackgroundIr(e.target.checked)} />
                  <span className={`toggleSwitch ${backgroundIr ? 'toggleSwitchOn' : ''}`} aria-hidden="true">
                    <span className="toggleThumb" />
                  </span>
                </div>
              </label>

              <label className="fieldBlock" htmlFor="init">
                <span>Carga inicial (horas)</span>
                <input id="init" type="number" min="0" max="24" value={initialLoadHours} onChange={(e) => setInitialLoadHours(Number(e.target.value || 0))} />
              </label>

              {statusText ? <div className="statusCard statusCardInfo">{statusText}</div> : null}

              {tableStatus ? <div className="statusCard statusCardInfo">{tableStatus}</div> : null}

              <button className="primaryAction" type="button" onClick={generateTable} disabled={!selectedTaker || isGeneratingTable}>
                <span>{isGeneratingTable ? 'Gerando...' : 'Gerar Tabela'}</span>
                <span className={`spinner ${isGeneratingTable ? 'spinnerActive' : ''}`} aria-hidden="true" />
              </button>

              <button className="secondaryAction" type="button" onClick={loadSavedTables} disabled={!selectedTaker || savedTablesLoading}>
                {savedTablesLoading ? 'Atualizando...' : 'Carregar últimas tabelas salvas'}
              </button>
            </div>
          </section>

          <section className="panel panelHistory">
            <div className="panelHeader panelHeaderSplit">
              <div>
                <span className="eyebrow">Dados salvos</span>
                <strong>HISTÓRICO DE TABELAS</strong>
              </div>

              <button type="button" className="ghostAction" onClick={loadSavedTables} disabled={!selectedTaker || savedTablesLoading}>
                Atualizar
              </button>
            </div>

            {savedTablesError ? <div className="statusCard">{savedTablesError}</div> : null}

            {savedTables.length > 0 ? (
              <div className="savedTablesList">
                {savedTables.map((item) => {
                  const isActive = item.relativePath === selectedSavedTable
                  return (
                    <button
                      key={item.relativePath}
                      type="button"
                      className={`savedTableItem ${isActive ? 'savedTableItemActive' : ''}`}
                      onClick={() => loadSavedTable(item.relativePath)}
                    >
                      <span className="savedTableItemTitle">{formatSavedTableLabel(item)}</span>
                      <span className="savedTableItemPath">{item.relativePath}</span>
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="tableEmpty small">
                <span>{savedTablesLoading ? 'Buscando tabelas...' : 'Nenhuma tabela salva encontrada para este tomador.'}</span>
              </div>
            )}
          </section>

          <section className="panel panelDownloads">
            <div className="panelHeader">
              <span className="eyebrow">Exportação</span>
              <strong>DOWNLOAD DE DADOS</strong>
            </div>

            <div className="downloadCards">
              <article className="downloadCard">
                <div className="downloadCardIcon downloadCardIconPrimary" aria-hidden="true">
                  <svg viewBox="0 0 24 24">
                    <path d="M12 3a1 1 0 0 1 1 1v8.59l2.3-2.3a1 1 0 1 1 1.4 1.42l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.42L11 12.59V4a1 1 0 0 1 1-1Zm-7 14a1 1 0 0 1 1 1v2h12v-2a1 1 0 1 1 2 0v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1Z" fill="currentColor" />
                  </svg>
                </div>
                <div className="downloadCardBody">
                  <strong>Imagem PNG</strong>
                  <span>Baixe a visualização atual com o layout completo do render.</span>
                </div>
                <button className="downloadCardButton" type="button" onClick={downloadCurrentImage} disabled={!plotUrl}>
                  Baixar
                </button>
              </article>

              <article className="downloadCard">
                <div className="downloadCardIcon" aria-hidden="true">
                  <svg viewBox="0 0 24 24">
                    <path d="M5 4a2 2 0 0 1 2-2h6.59a2 2 0 0 1 1.41.59l4.41 4.41A2 2 0 0 1 20 8.41V20a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4Zm8 0v4h4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <div className="downloadCardBody">
                  <strong>Tabela CSV</strong>
                  <span>Exporte a tabela 4x288 gerada ou carregada no painel.</span>
                </div>
                <button className="downloadCardButton" type="button" onClick={downloadCurrentTableCsv} disabled={!tableData?.values4x24?.length}>
                  Baixar
                </button>
              </article>
            </div>
          </section>
        </aside>
      </main>
    </div>
  )
}

export default App
