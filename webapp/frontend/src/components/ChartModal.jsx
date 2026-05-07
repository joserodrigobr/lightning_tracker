import React, { useMemo } from 'react';
import './ChartModal.css';

const LINE_COLORS = ['#ff00ff', '#00e5ff', '#ffff00', '#00ff00', '#ff4d4d'];

export default function ChartModal({ isOpen, onClose, data, title }) {
  if (!isOpen) return null;

  // data structure: { hourLabels: [], radiiLabels: [], values4x24: [][] }
  const hourLabels = data?.hourLabels || [];
  const radiiLabels = data?.radiiLabels || [];
  const series = data?.values4x24 || [];

  const maxVal = useMemo(() => {
    let max = 0;
    series.forEach(row => {
      row.forEach(val => { if (val > max) max = val; });
    });
    return max || 10;
  }, [series]);

  // Chart dimensions
  const width = 800;
  const height = 400;
  const padding = 40;
  const chartWidth = width - padding * 2;
  const chartHeight = height - padding * 2;

  const points = useMemo(() => {
    if (!hourLabels.length) return [];
    const stepX = chartWidth / (hourLabels.length - 1 || 1);
    
    return series.map((row, sIdx) => {
      return row.map((val, i) => {
        const x = padding + i * stepX;
        const y = padding + chartHeight - (val / maxVal) * chartHeight;
        return { x, y };
      }).filter(p => !isNaN(p.y));
    });
  }, [series, hourLabels, maxVal, chartWidth, chartHeight]);

  return (
    <div className="lt-modal-overlay">
      <div className="lt-modal lt-modal--large">
        <div className="lt-modal__header">
          <h2 className="lt-modal__title">{title || 'Gráfico de Relâmpagos'}</h2>
          <button className="lt-modal__close" onClick={onClose}>✕</button>
        </div>
        
        <div className="lt-chart-content">
          {series.length > 0 ? (
            <>
              <svg viewBox={`0 0 ${width} ${height}`} className="lt-svg-chart">
                {/* Grid Lines */}
                {[0, 0.25, 0.5, 0.75, 1].map(tick => {
                  const y = padding + chartHeight * (1 - tick);
                  return (
                    <React.Fragment key={tick}>
                      <line x1={padding} y1={y} x2={width - padding} y2={y} stroke="#333" strokeDasharray="4" />
                      <text x={padding - 5} y={y + 4} textAnchor="end" fill="#888" fontSize="10">
                        {Math.round(tick * maxVal)}
                      </text>
                    </React.Fragment>
                  );
                })}

                {/* X Axis Ticks */}
                {hourLabels.map((label, i) => {
                  if (hourLabels.length > 20 && i % Math.floor(hourLabels.length / 8) !== 0) return null;
                  const x = padding + (i * chartWidth) / (hourLabels.length - 1 || 1);
                  return (
                    <text key={i} x={x} y={height - padding + 20} textAnchor="middle" fill="#888" fontSize="10">
                      {label}
                    </text>
                  );
                })}

                {/* Lines */}
                {points.map((linePoints, sIdx) => (
                  <polyline
                    key={sIdx}
                    fill="none"
                    stroke={LINE_COLORS[sIdx % LINE_COLORS.length]}
                    strokeWidth="2"
                    points={linePoints.map(p => `${p.x},${p.y}`).join(' ')}
                    className="lt-chart-line"
                  />
                ))}
              </svg>
              
              <div className="lt-chart-legend">
                {radiiLabels.map((label, i) => (
                  <div key={i} className="lt-legend-item">
                    <span className="lt-legend-color" style={{ background: LINE_COLORS[i % LINE_COLORS.length] }}></span>
                    {label}
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="lt-chart-empty">Nenhum dado disponível para o período selecionado.</div>
          )}
        </div>
      </div>
    </div>
  );
}
