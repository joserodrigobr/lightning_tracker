import './Header.css'

export default function Header({ onMenuToggle, theme, onThemeToggle }) {
  const isLight = theme === 'light'

  return (
    <header className="lt-header">
      <div className="lt-header__left">
        <button className="lt-header__menu-btn" onClick={onMenuToggle} aria-label="Menu">
          <svg width="22" height="18" viewBox="0 0 22 18" fill="none">
            <rect y="0" width="22" height="2.5" rx="1.25" fill="currentColor" />
            <rect y="7.5" width="22" height="2.5" rx="1.25" fill="currentColor" />
            <rect y="15" width="22" height="2.5" rx="1.25" fill="currentColor" />
          </svg>
        </button>
        <img className="lt-header__logo" src="/logo.png" alt="BlueOcean" />
        <h1 className="lt-header__title">Monitoramento de Raios</h1>
      </div>
      <div className="lt-header__right">
        <button
          type="button"
          className="lt-theme-toggle"
          onClick={onThemeToggle}
          aria-label={`Alternar para modo ${isLight ? 'escuro' : 'claro'}`}
          aria-pressed={isLight}
          title={`Modo ${isLight ? 'claro' : 'escuro'}`}
        >
          <span className="lt-theme-toggle__label">{isLight ? 'Claro' : 'Escuro'}</span>
          <span className="lt-theme-toggle__track">
            <span className="lt-theme-toggle__thumb" />
          </span>
        </button>
        <span className="lt-header__version">Versão: 1.0.0 ({new Date().toLocaleDateString('pt-BR')})</span>
      </div>
    </header>
  )
}
