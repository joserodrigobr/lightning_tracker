import './StatsPanel.css'

const RING_LABELS = ['30km', '50km', '100km', '200km']

export default function StatsPanel({ stats }) {
  return (
    <div className="lt-stats">

      {/* Lightning counts */}
      <div className="lt-stats__section-title">Relâmpagos</div>

      <div className="lt-stats__counts-row">
        <div className="lt-stats__count-card">
          <span className="lt-stats__count-value">{stats.total}</span>
          <span className="lt-stats__count-label">Total</span>
        </div>
        <div className="lt-stats__count-card">
          <span className="lt-stats__count-value">{stats.last5min}</span>
          <span className="lt-stats__count-label">Últimos 5 min</span>
        </div>
      </div>

      {/* Per-ring counts */}
      <div className="lt-stats__rings-row">
        {RING_LABELS.map((label, i) => (
          <div key={label} className="lt-stats__ring-card">
            <span className="lt-stats__ring-value">{stats.byRing[i]}</span>
            <span className="lt-stats__ring-label">{label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
