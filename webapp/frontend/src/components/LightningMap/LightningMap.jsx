import { useEffect, useMemo, useRef, Fragment } from 'react'
import { MapContainer, TileLayer, Circle, CircleMarker, Marker, ImageOverlay, Rectangle, Polygon, Polyline, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import { jetColor } from '../../utils/haversine'
import './LightningMap.css'

const TILE_LAYERS = {
  dark: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  light: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
}

function createTakerIcon(theme) {
  const stroke = theme === 'light' ? '#0f172a' : '#ffffff'
  const shadow = theme === 'light' ? 'rgba(255,255,255,0.9)' : 'rgba(0,0,0,0.7)'

  return L.divIcon({
    className: 'lt-taker-icon',
    html: `<svg width="28" height="28" viewBox="0 0 28 28" style="filter: drop-shadow(0 0 2px ${shadow});"><line x1="6" y1="6" x2="22" y2="22" stroke="${stroke}" stroke-width="3.5" stroke-linecap="round"/><line x1="22" y1="6" x2="6" y2="22" stroke="${stroke}" stroke-width="3.5" stroke-linecap="round"/></svg>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  })
}

// Custom X icons for nowcast projections
const PROJECTION_COLORS = {
  15: '#ff3d00', // Red
  30: '#ffea00', // Yellow
  60: '#00e676', // Green
}

const getProjectionIcon = (minutes) => {
  const color = PROJECTION_COLORS[minutes] || '#ffffff'
  return L.divIcon({
    className: 'lt-projection-icon',
    html: `<svg width="24" height="24" viewBox="0 0 24 24"><line x1="4" y1="4" x2="20" y2="20" stroke="${color}" stroke-width="5" stroke-linecap="round"/><line x1="20" y1="4" x2="4" y2="20" stroke="${color}" stroke-width="5" stroke-linecap="round"/></svg>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  })
}

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
  playbackTime,
  accumulatedMode,
  onPlay,
  onPause,
  onStepBack,
  onStepForward,
  onDownloadImage,
  onDownloadAnim,
  lastUpdateAt,
  refreshIntervalMs = 60_000,
  initialLoadHours,
  markerInterval,
  visMode,
  nowcast,
  showNowcast,
  theme = 'dark',
  onTakerSelect,
}) {
  const now = new Date()
  const isSouthAmerica = taker && taker.id === 0
  const center = taker ? [taker.lat, taker.lon] : [-14.0, -52.0]
  const zoom = isSouthAmerica ? 4 : (taker ? 7 : 4)

  // Time range for coloring
  const effectivePlaybackTime = (animating && playbackTime) ? playbackTime : now.getTime()
  
  const filteredEvents = useMemo(() => {
    if (!animating || !playbackTime) return events
    
    const intervalMs = (markerInterval || 10) * 60000
    return events.filter(ev => {
      const evMs = new Date(ev.eventTime).getTime()
      if (evMs > playbackTime) return false
      if (!accumulatedMode && evMs < playbackTime - intervalMs) return false
      return true
    })
  }, [events, animating, playbackTime, accumulatedMode, markerInterval])

  // ABI overlay: use props from useAbiOverlay hook
  // abiBounds comes from the hook (South America by default)
  const leafletAbiBounds = abiBounds || null

  // Format metadata
  const effectiveStart = startLocal
    ? new Date(startLocal)
    : new Date(now.getTime() - (initialLoadHours || 4) * 3600000)
  const startLabel = effectiveStart.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  const endLabel = endLocal
    ? new Date(endLocal).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    : 'Agora'
  const lastUpdateDate = lastUpdateAt ? new Date(lastUpdateAt) : null
  const updateLabel = lastUpdateDate
    ? lastUpdateDate.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : '--:--:--'

  const nextUpdateDate = lastUpdateDate
    ? new Date(lastUpdateDate.getTime() + refreshIntervalMs)
    : new Date(now.getTime() + refreshIntervalMs)
  const nextUpdateLabel = nextUpdateDate.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })

  const clockLabel = (animating && playbackTime)
    ? new Date(playbackTime).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    : now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })

  // Define South America bounds to prevent panning away
  const southAmericaBounds = [
    [-56, -95], // Southwest
    [15, -30]   // Northeast
  ];

  const mapTileUrl = TILE_LAYERS[theme] || TILE_LAYERS.dark
  const takerIcon = useMemo(() => createTakerIcon(theme), [theme])
  const nowcastVectorColor = theme === 'light' ? '#0f172a' : '#ffffff'

  return (
    <div className={`lt-map-container lt-map-container--${theme}`}>
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
          key={theme}
          url={mapTileUrl}
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
          subdomains='abcd'
          maxZoom={20}
          className="lt-map-base-tile"
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
            <Marker
              key={`marker-${t.id}`}
              position={[t.lat, t.lon]}
              icon={takerIcon}
              eventHandlers={{
                click: () => onTakerSelect?.(String(t.id)),
              }}
            >
              <Tooltip direction="top" offset={[0, -12]} opacity={1} sticky>
                <span className="lt-taker-tooltip">{t.name}</span>
              </Tooltip>
            </Marker>
          ))}

        {/* Lightning events - Point Mode */}
        {visMode === 'points' && filteredEvents.map((ev) => {
          const eventMs = new Date(ev.eventTime).getTime()
          const ageMin = Math.max(0, (effectivePlaybackTime - eventMs) / 60000)
          
          // Use jetColor based on age relative to a 60-minute window (or similar)
          // Newest (0 min) -> t=1 (Yellow/Red), Oldest (60+ min) -> t=0 (Blue)
          const maxAge = 60 
          const t = Math.max(0, 1 - (ageMin / maxAge))

          return (
            <CircleMarker
              key={ev.id}
              center={[ev.latitude, ev.longitude]}
              radius={5}
              pathOptions={{
                // Only blink if it's new AND high intensity (red/orange)
                className: (ageMin < 5 && t > 0.8) ? 'lt-new-flash' : '',
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

          // Aggregate filtered events into spatial cells
          filteredEvents.forEach(ev => {
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

        {/* Nowcast Visualization — Cells, Hulls, and Vectors */}
        {showNowcast && nowcast && nowcast.cells && nowcast.cells.map((cell) => {
          const hullPoints = cell.hullLat && cell.hullLat.length >= 3
            ? cell.hullLat.map((lat, i) => [lat, cell.hullLon[i]])
            : null;
          
          const projections = cell.projections || [];
          
          return (
            <Fragment key={`nowcast-${cell.cellId}`}>
              {/* Storm Cell Hull */}
              {hullPoints && (
                <Polygon
                  positions={hullPoints}
                  pathOptions={{
                    color: '#ff3d00',
                    weight: 2,
                    fillColor: '#ff3d00',
                    fillOpacity: 0.2,
                  }}
                >
                  <Tooltip sticky>
                    <div className="lt-nowcast-tooltip">
                      <strong>Célula {cell.cellId.split('_')[1]}</strong><br/>
                      ⚡ {cell.flashCount} raios<br/>
                      📏 {cell.areaKm2} km²<br/>
                      🚀 {cell.velocityKmh} km/h ({cell.bearingLabel})
                    </div>
                  </Tooltip>
                </Polygon>
              )}

              {/* Displacement Vector (Seta) - goes until 60 min */}
              {projections.length > 0 && (
                <Polyline
                  positions={[
                    [cell.centroidLat, cell.centroidLon],
                    [projections[projections.length - 1].lat, projections[projections.length - 1].lon]
                  ]}
                  pathOptions={{
                    color: nowcastVectorColor,
                    weight: 2.5,
                    dashArray: '8, 8',
                    opacity: 0.7,
                  }}
                />
              )}
              
              {/* Future Projections (15, 30, 60 min) as thick X markers */}
              {projections.map((proj) => (
                <Marker
                  key={`proj-${cell.cellId}-${proj.minutes}`}
                  position={[proj.lat, proj.lon]}
                  icon={getProjectionIcon(proj.minutes)}
                >
                  <Tooltip>Impacto em {proj.minutes} min</Tooltip>
                </Marker>
              ))}
            </Fragment>
          );
        })}
      </MapContainer>

      {/* Metadata overlay (top center) */}
      <div className="lt-map-meta">
        <span>Última atualização: {updateLabel} BRT</span>
        <span>Hora Inicial: {startLabel} BRT</span>
        <span>Hora final: {endLabel === 'Agora' ? endLabel : endLabel + ' BRT'}</span>
        <span>Próxima atualização: {nextUpdateLabel} BRT</span>
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
