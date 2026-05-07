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
  onGenerateChart,
  onOpenDataRequest,
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
                onClick={() => onGenerateTable('yesterday', 5)}
                disabled={!selectedTaker || isGeneratingTable}
              >
                {isGeneratingTable ? 'Gerando...' : 'Ontem (24h - 5min)'}
              </button>
            </li>
            <li>
              <button 
                className="lt-menu__item" 
                onClick={() => onGenerateTable('3h', 5)}
                disabled={!selectedTaker || isGeneratingTable}
              >
                {isGeneratingTable ? 'Gerando...' : 'Últimas 3 horas (5min)'}
              </button>
            </li>
          </ul>
          {tableStatus && <div className="lt-menu__status" style={{marginTop: '10px'}}>{tableStatus}</div>}
        </div>

        <div className="lt-menu__section">
          <h3 className="lt-menu__section-title">Gerar Gráficos</h3>
          <ul className="lt-menu__list">
            <li>
              <button 
                className="lt-menu__item" 
                onClick={() => onGenerateChart('yesterday', 5)}
                disabled={!selectedTaker || isGeneratingTable}
              >
                Ontem (5min)
              </button>
            </li>
            <li>
              <button 
                className="lt-menu__item" 
                onClick={() => onGenerateChart('24h_now', 5)}
                disabled={!selectedTaker || isGeneratingTable}
              >
                Últimas 24 horas (5min)
              </button>
            </li>
            <li>
              <button 
                className="lt-menu__item" 
                onClick={() => onGenerateChart('3h', 1)}
                disabled={!selectedTaker || isGeneratingTable}
              >
                Últimas 3 horas (1min)
              </button>
            </li>
          </ul>
        </div>

        <div className="lt-menu__section">
          <h3 className="lt-menu__section-title">Serviços Adicionais</h3>
          <ul className="lt-menu__list">
            <li>
              <button 
                className="lt-menu__item" 
                onClick={() => onOpenDataRequest()}
              >
                Requisição de Dados (E-mail)
              </button>
            </li>
          </ul>
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
