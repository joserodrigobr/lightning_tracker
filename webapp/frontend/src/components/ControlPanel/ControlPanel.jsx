import './ControlPanel.css'

const MARKER_INTERVALS = [
  { value: 1, label: '1 minuto' },
  { value: 5, label: '5 minutos' },
  { value: 10, label: '10 minutos' },
  { value: 20, label: '20 minutos' },
  { value: 30, label: '30 minutos' },
  { value: 60, label: '60 minutos' },
]

const VIS_MODES = [
  { value: 'points', label: 'Pontos (Flashes)' },
  { value: 'density', label: 'Densidade (Flash/km²)' },
]

export default function ControlPanel({
  takers,
  takerId,
  onTakerChange,
  markerInterval,
  onMarkerIntervalChange,
  visMode,
  onVisModeChange,
  startLocal,
  onStartLocalChange,
  endLocal,
  onEndLocalChange,
  backgroundIr,
  onBackgroundIrChange,
  showRings,
  onShowRingsChange,
  accumulatedMode,
  onAccumulatedModeChange,
  showNowcast,
  onShowNowcastChange,
  onReset,
  animating,
}) {
  const takerOptions = takers

  return (
    <div className="lt-ctrl">
      {/* Tomador de Serviço */}
      <div className="lt-ctrl__row">
        <label className="lt-ctrl__label">Tomador de Serviço</label>
        <select
          className="lt-ctrl__select"
          value={takerId}
          onChange={(e) => onTakerChange(e.target.value)}
        >
          {takerOptions.map((t) => (
            <option key={t.id} value={String(t.id)}>
              {t.name}
            </option>
          ))}
        </select>
      </div>

      {/* Intervalo de Marcadores */}
      <div className="lt-ctrl__row">
        <label className="lt-ctrl__label">Intervalo de Marcadores</label>
        <select
          className="lt-ctrl__select"
          value={markerInterval}
          onChange={(e) => onMarkerIntervalChange(Number(e.target.value))}
        >
          {MARKER_INTERVALS.map((i) => (
            <option key={i.value} value={i.value}>
              {i.label}
            </option>
          ))}
        </select>
      </div>

      {/* Modo de Visualização */}
      <div className="lt-ctrl__row">
        <label className="lt-ctrl__label">Modo de Visualização</label>
        <select
          className="lt-ctrl__select"
          value={visMode}
          onChange={(e) => onVisModeChange(e.target.value)}
        >
          {VIS_MODES.map((v) => (
            <option key={v.value} value={v.value}>
              {v.label}
            </option>
          ))}
        </select>
      </div>

      {/* Tempo Inicial */}
      <div className="lt-ctrl__row">
        <label className="lt-ctrl__label">Tempo Inicial</label>
        <input
          type="datetime-local"
          className="lt-ctrl__input"
          value={startLocal}
          onChange={(e) => onStartLocalChange(e.target.value)}
        />
      </div>

      {/* Tempo Final */}
      <div className="lt-ctrl__row">
        <label className="lt-ctrl__label">Tempo Final</label>
        {endLocal ? (
          <input
            type="datetime-local"
            className="lt-ctrl__input"
            value={endLocal}
            onChange={(e) => onEndLocalChange(e.target.value)}
          />
        ) : (
          <div className="lt-ctrl__live-badge" onClick={onReset} title="Clique para voltar ao tempo real">
            Ao Vivo
          </div>
        )}
      </div>

      <div className="lt-ctrl__toggles">
        <label className="lt-ctrl__toggle">
          <span>Ativar IR (CH 13)</span>
          <input
            type="checkbox"
            checked={backgroundIr}
            onChange={(e) => onBackgroundIrChange(e.target.checked)}
          />
          <span className={`lt-ctrl__check ${backgroundIr ? 'lt-ctrl__check--on' : ''}`}>
            {backgroundIr ? '✓' : ''}
          </span>
        </label>

        {animating && (
          <label className="lt-ctrl__toggle">
            <span>Modo Acumulado</span>
            <input
              type="checkbox"
              checked={accumulatedMode}
              onChange={(e) => onAccumulatedModeChange(e.target.checked)}
            />
            <span className={`lt-ctrl__check ${accumulatedMode ? 'lt-ctrl__check--on' : ''}`}>
              {accumulatedMode ? '✓' : ''}
            </span>
          </label>
        )}

        <label className="lt-ctrl__toggle">
          <span>Previsão de Deslocamento</span>
          <input
            type="checkbox"
            checked={showNowcast}
            onChange={(e) => onShowNowcastChange(e.target.checked)}
          />
          <span className={`lt-ctrl__check ${showNowcast ? 'lt-ctrl__check--on' : ''}`}>
            {showNowcast ? '✓' : ''}
          </span>
        </label>

        <label className="lt-ctrl__toggle">
          <span>Raios de Alcance</span>
          <input
            type="checkbox"
            checked={showRings}
            onChange={(e) => onShowRingsChange(e.target.checked)}
          />
          <span className={`lt-ctrl__check ${showRings ? 'lt-ctrl__check--on' : ''}`}>
            {showRings ? '✓' : ''}
          </span>
        </label>
      </div>

      <button className="lt-ctrl__reset-btn" onClick={onReset}>
        Voltar às Configurações Iniciais
      </button>
    </div>
  )
}
