import { useState } from 'react'
import './SideMenu.css'

export default function SideMenu({
  open,
  onClose,
  selectedTaker,
  tableData,
  savedTables,
  onGenerateTable,
  onLoadSavedTable,
  onDownloadCsv,
  isGeneratingTable,
  tableStatus,
}) {
  return (
    <>
      {/* Backdrop */}
      {open && <div className="lt-menu-backdrop" onClick={onClose} />}

      <div className={`lt-menu ${open ? 'lt-menu--open' : ''}`}>
        <div className="lt-menu__header">
          <span className="lt-menu__title">MENU</span>
          <button className="lt-menu__close" onClick={onClose}>✕</button>
        </div>

        <div className="lt-menu__section">
          <h3 className="lt-menu__section-title">Gerar & Download CSV</h3>
          <ul className="lt-menu__list">
            <li>
              <button 
                className="lt-menu__item" 
                onClick={() => onGenerateTable('yesterday')}
                disabled={!selectedTaker || isGeneratingTable}
              >
                {isGeneratingTable ? 'Gerando...' : 'Ontem'}
              </button>
            </li>
            <li>
              <button 
                className="lt-menu__item" 
                onClick={() => onGenerateTable('3h')}
                disabled={!selectedTaker || isGeneratingTable}
              >
                {isGeneratingTable ? 'Gerando...' : 'Últimas 3 horas'}
              </button>
            </li>
          </ul>
          {tableStatus && <div className="lt-menu__status" style={{marginTop: '10px'}}>{tableStatus}</div>}
        </div>

        <div className="lt-menu__section">
          <h3 className="lt-menu__section-title">Tabelas Salvas Anteriormente</h3>

          {savedTables.length > 0 ? (
            <ul className="lt-menu__list">
              {savedTables.map((item) => (
                <li key={item.relativePath}>
                  <button
                    className="lt-menu__item"
                    onClick={() => onLoadSavedTable(item.relativePath)}
                  >
                    {item.savedAtLocal || item.lastWriteLocal || item.fileName || item.relativePath}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="lt-menu__empty">Nenhuma tabela salva.</p>
          )}
        </div>
      </div>
    </>
  )
}
