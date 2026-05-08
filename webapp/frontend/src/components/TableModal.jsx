import React, { useRef } from 'react';
import './TableModal.css';

export default function TableModal({ isOpen, onClose, data, title }) {
  const tableRef = useRef(null);

  if (!isOpen || !data) return null;

  const { hourLabels = [], radiiLabels = [], values4x24 = [] } = data;

  // Transpose data for a standard vertical table (Time in rows, Rings in columns)
  const rows = hourLabels.map((label, timeIdx) => {
    const rowValues = values4x24.map(series => series[timeIdx] || 0);
    const total = rowValues.reduce((a, b) => a + b, 0);
    return { label, values: rowValues, total };
  });

  return (
    <div className="lt-modal-overlay">
      <div className="lt-modal lt-modal--large lt-table-modal">
        <div className="lt-modal__header">
          <div className="lt-modal__header-left">
            <h2 className="lt-modal__title">{title || 'Dados da Tabela'}</h2>
          </div>
          <button className="lt-modal__close" onClick={onClose}>✕</button>
        </div>

        <div className="lt-table-container" ref={tableRef}>
          <table className="lt-data-table">
            <thead>
              <tr>
                <th>Hora</th>
                {radiiLabels.map((label, i) => <th key={i}>{label}</th>)}
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <td className="lt-col-time">{row.label}</td>
                  {row.values.map((v, j) => (
                    <td key={j} className={v > 0 ? 'lt-val-active' : 'lt-val-zero'}>{v}</td>
                  ))}
                  <td className="lt-col-total">{row.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
