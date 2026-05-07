import { useEffect, useMemo, useRef } from 'react'
import { MapContainer, TileLayer, Circle, CircleMarker, Marker, ImageOverlay, Rectangle, useMap } from 'react-leaflet'
import L from 'leaflet'
import { jetColor } from '../utils/haversine'
import './LightningMap.css'

// Black X marker for taker center
const takerIcon = L.divIcon({
  className: 'lt-taker-icon',
  html: `<svg width="28" height="28" viewBox="0 0 28 28"><line x1="6" y1="6" x2="22" y2="22" stroke="black" stroke-width="3.5" stroke-linecap="round"/><line x1="22" y1="6" x2="6" y2="22" stroke="black" stroke-width="3.5" stroke-linecap="round"/></svg>`,
  iconSize: [28, 28],
  iconAnchor: [14, 14],
})

const RING_COLORS = ['#1f77b4', '#2ca02c', '#ff7f0e', '#d62728']
const RING_RADII = [30, 50, 100, 200]

function MapController({ center, zoom }) {
  const map = useMap()
  const prevCenter = useRef(center)
  useEffect(() => {
    if (
      center &&
      (prevCenter.current[0] !== center[0] || prevCenter.current[1] !== center[1])
    ) {
      map.setView(center, zoom, { animate: true })
      prevCenter.current = center
    }
  }, [center, zoom, map])
  return null
}

export default function LightningMap({
  taker,
  allTakers,
  showAllTakers,
  showRings,
  events,
  backgroundIr,
  abiUrl,
  abiBounds,
  abiUtc,
  abiLoading,
  abiError,
  startLocal,
  endLocal,
  animating,
  animFrameTime,
  onPlay,
  onPause,
  onStepBack,
  onStepForward,
  onDownloadImage,
  onDownloadAnim,
  lastUpdateLocal,
  initialLoadHours,
  markerInterval,
  visMode,
}) {
  const isSouthAmerica = taker && taker.id === 0
  const center = taker ? [taker.lat, taker.lon] : [-14.0, -52.0]
  const zoom = isSouthAmerica ? 4 : (taker ? 7 : 4)

  // Time range for coloring
  const timeRange = useMemo(() => {
    if (!events || events.length === 0) return { min: 0, max: 1 }
    const times = events.map((e) => new Date(e.eventTime).getTime())
    const min = Math.min(...times)
    const max = Math.max(...times)
    return { min, max: max === min ? max + 1 : max }
  }, [events])

  // ABI overlay: use props from useAbiOverlay hook
  // abiBounds comes from the hook (South America by default)
  const leafletAbiBounds = abiBounds || null

  // Format metadata
  const now = new Date()
  const effectiveStart = startLocal
    ? new Date(startLocal)
    : new Date(now.getTime() - (initialLoadHours || 4) * 3600000)
  const startLabel = effectiveStart.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  const endLabel = endLocal
    ? new Date(endLocal).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    : 'Agora'
  const updateLabel = lastUpdateLocal || now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  const intervalLabel = initialLoadHours ? `${String(initialLoadHours).padStart(2, '0')}:00` : '04:00'
  const clockLabel = animFrameTime
    ? new Date(animFrameTime).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    : now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })

  // Define South America bounds to prevent panning away
  const southAmericaBounds = [
    [-56, -95], // Southwest
    [15, -30]   // Northeast
  ];

  return (
    <div className="lt-map-container">
      <MapContainer
        center={center}
        zoom={zoom}
        minZoom={5}
        maxBounds={southAmericaBounds}
        maxBoundsViscosity={1.0}
        className="lt-map"
        zoomControl={false}
        attributionControl={false}
      >
        <MapController center={center} zoom={zoom} />

        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
          subdomains='abcd'
          maxZoom={20}
        />

        {/* ABI IR CH13 background overlay */}
        {backgroundIr && abiUrl && leafletAbiBounds && (
          <ImageOverlay
            key={abiUrl}
            url={abiUrl}
            bounds={leafletAbiBounds}
            opacity={1.0}
            zIndex={1}
          />
        )}

        {/* Distance rings */}
        {showRings && (showAllTakers && allTakers ? allTakers : (taker ? [taker] : []))
          .filter(t => t.id !== 0)
          .map((t) =>
            RING_RADII.map((r, i) => (
              <Circle
                key={`ring-${t.id}-${r}`}
                center={[t.lat, t.lon]}
                radius={r * 1000}
                pathOptions={{
                  color: RING_COLORS[i],
                  weight: 2,
                  fillOpacity: 0,
                  dashArray: i === 0 ? undefined : '8 4',
                }}
              />
            ))
          )}

        {/* Taker center markers */}
        {showRings && (showAllTakers && allTakers ? allTakers : (taker ? [taker] : []))
          .filter(t => t.id !== 0)
          .map((t) => (
            <Marker key={`marker-${t.id}`} position={[t.lat, t.lon]} icon={takerIcon} />
          ))}

        {/* Lightning events - Point Mode */}
        {visMode === 'points' && events.map((ev) => {
          const eventMs = new Date(ev.eventTime).getTime()
          const ageMin = Math.max(0, (timeRange.max - eventMs) / 60000)
          const step = Math.floor(ageMin / (markerInterval || 10))
          const totalSteps = Math.max(1, (timeRange.max - timeRange.min) / (60000 * (markerInterval || 10)))
          const t = Math.max(0, 1 - step / totalSteps)

          return (
            <CircleMarker
              key={ev.id}
              center={[ev.latitude, ev.longitude]}
              radius={5}
              pathOptions={{
                color: 'transparent',
                fillColor: jetColor(t),
                fillOpacity: 0.85,
              }}
            />
          )
        })}

        {/* Lightning Density - Grid Mode (Flash/km²) */}
        {visMode === 'density' && (() => {
          const GRID_SIZE = 0.15; // Degrees (~16km cells)
          const grid = {};
          let maxCount = 0;

          // Aggregate events into spatial cells
          events.forEach(ev => {
            const latIdx = Math.floor(ev.latitude / GRID_SIZE);
            const lonIdx = Math.floor(ev.longitude / GRID_SIZE);
            const key = `${latIdx},${lonIdx}`;
            
            if (!grid[key]) {
              grid[key] = { count: 0, lat: latIdx * GRID_SIZE, lon: lonIdx * GRID_SIZE };
            }
            grid[key].count++;
            if (grid[key].count > maxCount) maxCount = grid[key].count;
          });

          return Object.values(grid).map(cell => {
            const t = maxCount > 0 ? cell.count / maxCount : 0;
            const bounds = [
              [cell.lat, cell.lon],
              [cell.lat + GRID_SIZE, cell.lon + GRID_SIZE]
            ];
            return (
              <Rectangle
                key={`grid-${cell.lat}-${cell.lon}`}
                bounds={bounds}
                pathOptions={{
                  color: 'transparent',
                  fillColor: jetColor(t),
                  fillOpacity: 0.7
                }}
              />
            );
          });
        })()}
      </MapContainer>

      {/* Metadata overlay (top center) */}
      <div className="lt-map-meta">
        <span>Última atualização: {updateLabel} BRT</span>
        <span>Hora Inicial: {startLabel} BRT</span>
        <span>Hora final: {endLabel === 'Agora' ? endLabel : endLabel + ' BRT'}</span>
        <span>Intervalo: {intervalLabel}</span>
        {backgroundIr && abiUtc && (
          <span className="lt-map-meta__abi">
            🛰 ABI: {new Date(abiUtc).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })} UTC
          </span>
        )}
        {backgroundIr && abiLoading && (
          <span className="lt-map-meta__abi lt-map-meta__abi--loading">🛰 Carregando ABI...</span>
        )}
        {backgroundIr && abiError && (
          <span className="lt-map-meta__abi lt-map-meta__abi--error">🛰 Erro ABI: {abiError}</span>
        )}
      </div>

      {/* Animation clock (top right) */}
      <div className="lt-map-clock">{clockLabel}</div>

      {/* Animation controls (bottom left) */}
      <div className="lt-map-controls">
        <div className="lt-map-controls__buttons">
          <button onClick={onStepBack} title="Frame anterior" className="lt-map-ctrl-btn">⏮</button>
          {animating ? (
            <button onClick={onPause} title="Pausar" className="lt-map-ctrl-btn">⏸</button>
          ) : (
            <button onClick={onPlay} title="Reproduzir" className="lt-map-ctrl-btn">▶</button>
          )}
          <button onClick={onStepForward} title="Próximo frame" className="lt-map-ctrl-btn">⏭</button>
        </div>
        <div className="lt-map-controls__downloads">
          <button onClick={onDownloadImage} className="lt-map-dl-btn">
            Fazer o Download da Imagem Atual
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3a1 1 0 0 1 1 1v8.59l2.3-2.3a1 1 0 1 1 1.4 1.42l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.42L11 12.59V4a1 1 0 0 1 1-1Zm-7 14a1 1 0 0 1 1 1v2h12v-2a1 1 0 1 1 2 0v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1Z" /></svg>
          </button>
          <button onClick={onDownloadAnim} className="lt-map-dl-btn">
            Fazer o Download da Animação
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3a1 1 0 0 1 1 1v8.59l2.3-2.3a1 1 0 1 1 1.4 1.42l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 1 1 1.4-1.42L11 12.59V4a1 1 0 0 1 1-1Zm-7 14a1 1 0 0 1 1 1v2h12v-2a1 1 0 1 1 2 0v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1Z" /></svg>
          </button>
        </div>
      </div>
    </div>
  )
}
