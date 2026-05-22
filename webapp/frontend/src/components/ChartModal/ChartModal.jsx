import React, { useMemo, useRef } from 'react';
import './ChartModal.css';

const LINE_COLORS = ['#ff00ff', '#00e5ff', '#ffff00', '#00ff00', '#ff4d4d'];

export default function ChartModal({ isOpen, onClose, data, title }) {
  const svgRef = useRef(null);

  // data structure: { hourLabels: [], radiiLabels: [], values4x24: [][] }
  const hourLabels = useMemo(() => data?.hourLabels || [], [data]);
  const radiiLabels = useMemo(() => data?.radiiLabels || [], [data]);
  const series = useMemo(() => data?.values4x24 || [], [data]);

  const maxVal = useMemo(() => {
    let max = 0;
    series.forEach(row => {
      row.forEach(val => { if (val > max) max = val; });
    });
    return max || 10;
  }, [series]);

  // Chart dimensions
  const width = 800;
  const height = 460; // Increased to fit legend
  const padding = 40;
  const chartWidth = width - padding * 2;
  const chartHeight = 320; // Fixed chart area height

  const points = useMemo(() => {
    if (!hourLabels.length) return [];
    const stepX = chartWidth / (hourLabels.length - 1 || 1);
    
    return series.map((row) => {
      return row.map((val, i) => {
        const x = padding + i * stepX;
        const y = padding + chartHeight - (val / maxVal) * chartHeight;
        return { x, y };
      }).filter(p => !isNaN(p.y));
    });
  }, [series, hourLabels, maxVal, chartWidth, chartHeight]);

  const downloadPng = () => {
    if (!svgRef.current) return;
    try {
      const svg = svgRef.current;
      
      // Clone SVG to modify colors for white background export
      const clonedSvg = svg.cloneNode(true);
      clonedSvg.setAttribute('width', width);
      clonedSvg.setAttribute('height', height);
      
      // Update text and line colors for white background
      const textElements = clonedSvg.querySelectorAll('text');
      textElements.forEach(t => t.setAttribute('fill', '#333'));
      
      const gridLines = clonedSvg.querySelectorAll('line');
      gridLines.forEach(l => l.setAttribute('stroke', '#ddd'));
      
      const rectBg = clonedSvg.querySelector('rect');
      if (rectBg) rectBg.setAttribute('fill', '#ffffff');

      // Adjust series colors for better contrast on white (Darker versions)
      const EXPORT_COLORS = ['#d600d6', '#00acc1', '#fbc02d', '#2e7d32', '#c62828'];
      const polylines = clonedSvg.querySelectorAll('polyline');
      polylines.forEach((p, i) => {
        p.setAttribute('stroke', EXPORT_COLORS[i % EXPORT_COLORS.length]);
      });
      
      const legendRects = clonedSvg.querySelectorAll('g rect');
      legendRects.forEach((r, i) => {
        r.setAttribute('fill', EXPORT_COLORS[i % EXPORT_COLORS.length]);
      });
      
      const legendTexts = clonedSvg.querySelectorAll('g text');
      legendTexts.forEach(t => t.setAttribute('fill', '#444'));

      const svgData = new XMLSerializer().serializeToString(clonedSvg);
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      const img = new Image();
      const logoImg = new Image();
      
      const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(svgBlob);
      
      let imagesLoaded = 0;
      const onImageLoad = () => {
        imagesLoaded++;
        if (imagesLoaded === 2) {
          // High-DPI Scaling (3x)
          const scale = 3;
          canvas.width = width * scale;
          canvas.height = height * scale;
          
          if (ctx) {
            ctx.scale(scale, scale);
            // White background
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, width, height);
            
            // Draw chart
            ctx.drawImage(img, 0, 0, width, height);
            
            // Draw logo (top right) - Fix aspect ratio
            const logoH = 45;
            const logoW = (logoImg.naturalWidth / logoImg.naturalHeight) * logoH;
            ctx.drawImage(logoImg, width - logoW - 25, 15, logoW, logoH);
            
            canvas.toBlob((blob) => {
              if (!blob) return;
              const downloadUrl = URL.createObjectURL(blob);
              const a = document.createElement('a');
              const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
              a.download = `grafico_blueocean_hd_${ts}.png`;
              a.href = downloadUrl;
              a.click();
              URL.revokeObjectURL(downloadUrl);
            }, 'image/png', 1.0);
          }
          URL.revokeObjectURL(url);
        }
      };

      img.onload = onImageLoad;
      logoImg.onload = onImageLoad;
      img.src = url;
      logoImg.src = '/logo.png'; 
    } catch (e) {
      console.error('Erro ao baixar PNG:', e);
    }
  };

  // Calculate X offset to center the legend
  const legendXOffset = useMemo(() => {
    const itemWidth = 140;
    const totalLegendWidth = radiiLabels.length * itemWidth;
    return (width - totalLegendWidth) / 2 + 10;
  }, [radiiLabels, width]);

  if (!isOpen) return null;

  return (
    <div className="lt-modal-overlay">
      <div className="lt-modal lt-modal--large">
        <div className="lt-modal__header">
          <div className="lt-modal__header-left">
            <h2 className="lt-modal__title">{title || 'Gráfico de Relâmpagos'}</h2>
          </div>
          <div className="lt-modal__header-actions">
            {series.length > 0 && (
              <button className="lt-download-btn" onClick={downloadPng}>
                Baixar PNG
              </button>
            )}
            <button className="lt-modal__close" onClick={onClose} style={{ marginLeft: 15 }}>✕</button>
          </div>
        </div>
        
        <div className="lt-chart-content">
          {series.length > 0 ? (
            <svg 
              ref={svgRef}
              viewBox={`0 0 ${width} ${height}`} 
              width={width}
              height={height}
              className="lt-svg-chart"
              xmlns="http://www.w3.org/2000/svg"
            >
              {/* Background for export */}
              <rect width={width} height={height} fill="#111" />
              
              {/* Grid Lines */}
              {[0, 0.25, 0.5, 0.75, 1].map(tick => {
                const y = padding + chartHeight * (1 - tick);
                return (
                  <React.Fragment key={tick}>
                    <line x1={padding} y1={y} x2={width - padding} y2={y} stroke="#333" strokeDasharray="4" />
                    <text x={padding - 5} y={y + 4} textAnchor="end" fill="#888" fontSize="10" fontFamily="sans-serif">
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
                  <text key={i} x={x} y={padding + chartHeight + 20} textAnchor="middle" fill="#888" fontSize="10" fontFamily="sans-serif">
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
                />
              ))}

              {/* Legend inside SVG */}
              {radiiLabels.map((label, i) => {
                const x = legendXOffset + i * 140;
                const y = height - 25;
                return (
                  <g key={i}>
                    <rect x={x} y={y - 8} width={12} height={12} fill={LINE_COLORS[i % LINE_COLORS.length]} rx="2" />
                    <text x={x + 18} y={y + 2} fill="#ccc" fontSize="11" fontFamily="sans-serif">{label}</text>
                  </g>
                );
              })}
            </svg>
          ) : (
            <div className="lt-chart-empty">Nenhum dado disponível para o período selecionado.</div>
          )}
        </div>
      </div>
    </div>
  );
}
