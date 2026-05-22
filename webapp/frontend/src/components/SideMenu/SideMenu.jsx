import { useState } from 'react'
import './SideMenu.css'

const SHOW_ALERT_VALIDATION_BUTTON = false

export default function SideMenu({
  open,
  onClose,
  selectedTaker,
  //tableData,
  savedTables,
  onGenerateTable,
  onLoadSavedTable,
  //onDownloadCsv,
  onGenerateChart,
  onOpenDataRequest,
  isGeneratingTable,
  tableStatus,
  view,
  onViewChange,
}) {
  const [expandedSection, setExpandedSection] = useState(null);

  const toggleSection = (id) => {
    setExpandedSection(expandedSection === id ? null : id);
  };

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
          <h3 className="lt-menu__section-title">Sentinela</h3>
          <ul className="lt-menu__list">
            <li>
              <button 
                className={`lt-menu__item ${view === 'map' ? 'lt-menu__item--active' : ''}`}
                onClick={() => { onViewChange('map'); onClose(); }}
              >
                Mapa de Monitoramento
              </button>
            </li>
            {SHOW_ALERT_VALIDATION_BUTTON && (
              <li>
                <button 
                  className={`lt-menu__item ${view === 'alerts' ? 'lt-menu__item--active' : ''}`}
                  onClick={() => { onViewChange('alerts'); onClose(); }}
                >
                  Validação de Alertas
                </button>
              </li>
            )}
          </ul>
        </div>

        <div className="lt-menu__section">
          <h3 className="lt-menu__section-title">Tabelas</h3>
          <ul className="lt-menu__list">
            {/* Yesterday Section */}
            <li className="lt-menu__expandable">
              <button 
                className={`lt-menu__item ${expandedSection === 'yesterday' ? 'lt-menu__item--active' : ''}`}
                onClick={() => toggleSection('yesterday')}
                disabled={!selectedTaker || isGeneratingTable}
              >
                {isGeneratingTable && expandedSection === 'yesterday' ? 'Processando...' : 'Ontem (24h - 5min)'}
                <span className="lt-menu__arrow">{expandedSection === 'yesterday' ? '▼' : '▶'}</span>
              </button>
              
              {expandedSection === 'yesterday' && (
                <div className="lt-menu__sub">
                  <button className="lt-menu__sub-item" onClick={() => onGenerateTable('yesterday', 5)}>
                    Visualizar Web
                  </button>
                  <button className="lt-menu__sub-item" onClick={() => onGenerateTable('yesterday', 5, true)}>
                    Baixar CSV
                  </button>
                </div>
              )}
            </li>

            {/* 24h Now Section */}
            <li className="lt-menu__expandable">
              <button 
                className={`lt-menu__item ${expandedSection === '24h_now' ? 'lt-menu__item--active' : ''}`}
                onClick={() => toggleSection('24h_now')}
                disabled={!selectedTaker || isGeneratingTable}
              >
                {isGeneratingTable && expandedSection === '24h_now' ? 'Processando...' : 'Últimas 24 horas (5min)'}
                <span className="lt-menu__arrow">{expandedSection === '24h_now' ? '▼' : '▶'}</span>
              </button>
              
              {expandedSection === '24h_now' && (
                <div className="lt-menu__sub">
                  <button className="lt-menu__sub-item" onClick={() => onGenerateTable('24h_now', 5)}>
                    Visualizar Web
                  </button>
                  <button className="lt-menu__sub-item" onClick={() => onGenerateTable('24h_now', 5, true)}>
                    Baixar CSV
                  </button>
                </div>
              )}
            </li>

            {/* 3h Section */}
            <li className="lt-menu__expandable">
              <button 
                className={`lt-menu__item ${expandedSection === '3h' ? 'lt-menu__item--active' : ''}`}
                onClick={() => toggleSection('3h')}
                disabled={!selectedTaker || isGeneratingTable}
              >
                {isGeneratingTable && expandedSection === '3h' ? 'Processando...' : 'Últimas 3 horas (5min)'}
                <span className="lt-menu__arrow">{expandedSection === '3h' ? '▼' : '▶'}</span>
              </button>
              
              {expandedSection === '3h' && (
                <div className="lt-menu__sub">
                  <button className="lt-menu__sub-item" onClick={() => onGenerateTable('3h', 5)}>
                    Visualizar Web
                  </button>
                  <button className="lt-menu__sub-item" onClick={() => onGenerateTable('3h', 5, true)}>
                    Baixar CSV
                  </button>
                </div>
              )}
            </li>
          </ul>
          
          <p className="lt-menu__note">
            * Solicitação de dados de mais de 1 dia atrás deve ser feita via <b>Serviços Adicionais</b>.
          </p>

          {tableStatus && <div className="lt-menu__status" style={{marginTop: '10px'}}>{tableStatus}</div>}
        </div>

        <div className="lt-menu__section">
          <h3 className="lt-menu__section-title">Gráficos</h3>
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
                onClick={() => onGenerateChart('3h', 5)}
                disabled={!selectedTaker || isGeneratingTable}
              >
                Últimas 3 horas (5min)
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
          <h3 className="lt-menu__section-title">Tabelas Recentes</h3>

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
