import './App.css'

import { useEffect, useMemo, useRef, useState } from 'react'

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
  const startLabel = startLocal || '00:00 (dinâmico)'
  const endLabel = endLocal || 'agora'
  return `${startLabel} → ${endLabel}`
}

function getModeLabel(mode) {
  return MODES.find((item) => item.value === mode)?.label || `Modo ${mode}`
}

function toIntOrDash(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? String(parsed) : '—'
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
  lines.push(['Anel \ Hora', ...hourLabels].map((cell) => `"${csvCell(cell)}"`).join(';'))

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

  // Empty means dynamic default (00:00 -> now)
  const [startLocal, setStartLocal] = useState('')
  const [endLocal, setEndLocal] = useState('')
  const [initialLoadHours, setInitialLoadHours] = useState(0)
  const [backgroundIr, setBackgroundIr] = useState(true)

  const [plotUrl, setPlotUrl] = useState('')
  const plotUrlRef = useRef('')
  const [statusText, setStatusText] = useState('')
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
  const autoSelectRequestedRef = useRef(false)

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
    setTableStatus('Gerando tabela 4x24...')
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

  async function refreshPlot() {
    if (!selectedTaker) return
    setIsRendering(true)
    setRenderError('')
    setStatusText('Atualizando...')
    try {
      const qs = buildQuery({
        takerId: selectedTaker.id,
        mode,
        startLocal: normalizeDateTimeLocal(startLocal),
        endLocal: normalizeDateTimeLocal(endLocal),
        initialLoadHours,
        background: backgroundIr ? 1 : 0,
        _ts: Date.now(),
      })

      const res = await fetch(`/api/render?${qs}`)
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
      const message = String(e?.message || e)
      setStatusText(message)
      setRenderError(message)
    } finally {
      setIsRendering(false)
    }
  }

  function downloadCurrentImage() {
    if (!plotUrl) return
    const name = selectedTaker?.name ? String(selectedTaker.name) : 'taker'
    const safe = name
      .trim()
      .replace(/[^A-Za-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 64)
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const filename = `${safe || 'taker'}_mode${mode}_${ts}.png`

    const a = document.createElement('a')
    a.href = plotUrl
    a.download = filename
    a.click()
  }

  function downloadCurrentTableCsv() {
    if (!tableData?.values4x24?.length) return

    const csv = buildTableCsv(tableData)
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)

    const name = selectedTaker?.name ? String(selectedTaker.name) : 'taker'
    const safe = name
      .trim()
      .replace(/[^A-Za-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 64)
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const filename = `${safe || 'taker'}_table_${ts}.csv`

    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()

    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
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
    <div className="app">
      <header className="topbar">
        <div className="topbarTitle">
          <span>Visualizador de Raios</span>
        </div>
      </header>

      <main className="layout">
        <section className="plotPane" aria-label="Mapa">
          <div className="plotHeader">
            <div className="plotHeaderText">
              Última atualização:{' '}
              <strong>{lastUpdateLocal ? `${lastUpdateLocal} horas local` : '—'}</strong>
            </div>
          </div>

          <div className="plotFrame">
            {plotUrl ? (
              <img className="plotImg" src={plotUrl} alt="Mapa de flashes/eventos" draggable={false} />
            ) : (
              <div className={`plotPlaceholder ${isRendering ? 'plotPlaceholderLoading' : ''}`}>
                <div className="plotPlaceholderCard">
                  <strong>
                    {renderError ||
                      takersError ||
                      (isRendering ? 'Renderizando...' : 'Aguardando render...')}
                  </strong>
                  <span>{selectedTakerLabel}</span>
                  <span>{renderWindowLabel}</span>
                </div>
              </div>
            )}
            {isRendering && plotUrl ? <div className="plotOverlay">Atualizando imagem...</div> : null}
            <img className="watermark" src="/logo.png" alt="BLUEOCEAN" />
          </div>

          <div className="plotSummary" aria-label="Resumo do render">
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
              <strong>
                {renderMeta.dynamicStart === '1' || renderMeta.dynamicEnd === '1'
                  ? 'Sim'
                  : 'Não'}
              </strong>
            </div>
          </div>
        </section>

        <aside className="controlsPane" aria-label="Controles">
          <div className="brand">
            <img className="brandLogo" src="/logo.png" alt="BLUEOCEAN" />
          </div>

          <div className="controls">
            <div className="row">
              <label htmlFor="taker">Tomador de Serviço:</label>
              <select
                id="taker"
                value={takerId}
                onChange={(e) => setTakerId(e.target.value)}
                className="field"
              >
                {takers.map((t) => (
                  <option key={t.id} value={String(t.id)}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="row">
              <label htmlFor="start">Tempo inicial:</label>
              <input
                id="start"
                type="datetime-local"
                value={startLocal}
                onChange={(e) => setStartLocal(e.target.value)}
                className="field"
              />
            </div>

            <div className="row">
              <label htmlFor="end">Tempo final:</label>
              <input
                id="end"
                type="datetime-local"
                value={endLocal}
                onChange={(e) => setEndLocal(e.target.value)}
                className="field"
              />
            </div>

            <div className="row">
              <label htmlFor="mode">Tipo de Imagem:</label>
              <select
                id="mode"
                value={mode}
                onChange={(e) => setMode(Number(e.target.value))}
                className="field"
              >
                {MODES.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="row">
              <label htmlFor="init">Carga inicial (horas):</label>
              <input
                id="init"
                type="number"
                min="0"
                max="24"
                value={initialLoadHours}
                onChange={(e) => setInitialLoadHours(Number(e.target.value || 0))}
                className="field"
              />
            </div>

            <div className="row rowTight">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={backgroundIr}
                  onChange={(e) => setBackgroundIr(e.target.checked)}
                />
                <span>Overlay IR (ABI C13)</span>
              </label>
            </div>

            {statusText ? <div className="status statusInfo">{statusText}</div> : null}

            {tableStatus ? <div className="status statusInfo">{tableStatus}</div> : null}

            <div className="tableActions">
              <button className="tableBtn" type="button" onClick={generateTable} disabled={!selectedTaker || isGeneratingTable}>
                {isGeneratingTable ? 'Gerando...' : 'Gerar tabela 4x24'}
              </button>
              <button className="tableBtn tableBtnSecondary" type="button" onClick={loadSavedTables} disabled={!selectedTaker || savedTablesLoading}>
                {savedTablesLoading ? 'Atualizando...' : 'Carregar últimas tabelas salvas'}
              </button>
              <button className="tableBtn tableBtnSecondary" type="button" onClick={downloadCurrentTableCsv} disabled={!tableData?.values4x24?.length}>
                Baixar tabela em CSV
              </button>
            </div>

            {savedTablesError ? <div className="status">{savedTablesError}</div> : null}

            <div className="tablePanel" aria-label="Tabela 4x24">
              <div className="tablePanelHeader">
                <div>
                  <strong>Tabela 4x24</strong>
                  <span>
                    {tableData?.fileName
                      ? `${tableData.fileName}`
                      : selectedTakerLabel}
                  </span>
                </div>
                {tableData?.savedAtLocal ? <span className="tablePanelMeta">Salva em {tableData.savedAtLocal}</span> : null}
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
            </div>

            <div className="savedTablesPanel" aria-label="Últimas tabelas salvas">
              <div className="savedTablesHeader">
                <strong>Últimas tabelas salvas</strong>
                <button type="button" className="savedTablesRefresh" onClick={loadSavedTables} disabled={!selectedTaker || savedTablesLoading}>
                  Atualizar
                </button>
              </div>

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
            </div>

            <div className="downloadRow">
              <button className="downloadBtn" type="button" onClick={downloadCurrentImage} disabled={!plotUrl}>
                <span>Fazer o Download da Imagem</span>
                <svg viewBox="0 0 24 24" className="downloadIcon" aria-hidden="true">
                  <path
                    d="M12 3a1 1 0 0 1 1 1v8.59l2.3-2.3a1 1 0 1 1 1.4 1.42l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.42L11 12.59V4a1 1 0 0 1 1-1Zm-7 14a1 1 0 0 1 1 1v2h12v-2a1 1 0 1 1 2 0v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1Z"
                    fill="currentColor"
                  />
                </svg>
              </button>
            </div>
          </div>
        </aside>
      </main>
    </div>
  )
}

export default App
