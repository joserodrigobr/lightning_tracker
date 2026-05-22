import { useState, useEffect } from 'react';
import './AlertDashboard.css';
import {
  approveAlert,
  closeAlert,
  getAlertQueues,
  rejectAlert,
  updateAlert,
} from '../../services/alertsService';

const AlertDashboard = () => {
  const [pendingAlerts, setPendingAlerts] = useState([]);
  const [activeAlerts, setActiveAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [durations, setDurations] = useState({});
  const [customEtas, setCustomEtas] = useState({});

  const fetchAll = async () => {
    try {
      let { pending, active } = await getAlertQueues();

      // Sort pending by priority: Red > Yellow > Observing
      const priorityMap = { 'Red': 1, 'Yellow': 2, 'Observing': 3 };
      pending.sort((a, b) => (priorityMap[a.alertLevel] || 99) - (priorityMap[b.alertLevel] || 99));

      setPendingAlerts(pending);
      setActiveAlerts(active);
    } catch (err) {
      console.error('Error fetching alerts:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleDurationChange = (id, val) => {
    setDurations(prev => ({ ...prev, [id]: val }));
  };

  const handleEtaChange = (id, val) => {
    setCustomEtas(prev => ({ ...prev, [id]: val }));
  };

  const handleApprove = async (id) => {
    const duration = durations[id] || 60;
    const eta = customEtas[id];

    try {
      const response = await approveAlert(id, { duration, eta });
      if (response.ok) {
        fetchAll();
      }
    } catch {
      alert('Erro ao aprovar alerta.');
    }
  };

  const handleUpdate = async (id, level, duration) => {
    try {
      const response = await updateAlert(id, { level, duration });
      if (response.ok) {
        fetchAll();
      }
    } catch {
      alert('Erro ao atualizar alerta.');
    }
  };

  const handleClose = async (id) => {
    if (!window.confirm('Deseja realmente encerrar este monitoramento?')) return;
    try {
      const response = await closeAlert(id);
      if (response.ok) {
        fetchAll();
      }
    } catch {
      alert('Erro ao encerrar alerta.');
    }
  };

  const handleReject = async (id) => {
    try {
      const response = await rejectAlert(id);
      if (response.ok) {
        fetchAll();
      }
    } catch {
      alert('Erro ao rejeitar alerta.');
    }
  };

  const getMessagePreview = (alert, duration, customEta) => {
    const level = alert.alertLevel.toUpperCase();
    const payload = JSON.parse(alert.messagePayloadJson);
    const dur = duration || alert.durationMinutes || 60;
    
    // Support both PascalCase and camelCase for safety
    const impact = payload.Impact ?? payload.impact;
    const eta = customEta !== undefined ? customEta : (impact?.EtaMinutes ?? impact?.etaMinutes ?? '--');
    
    return `[WHATSAPP PREVIEW]\n${level === 'RED' ? '🔴 ALERTA VERMELHO' : '🟡 ALERTA AMARELO'} - SENTINELA\nUnidade: ${alert.takerName}\nForam detectados raios nas proximidades.\nDuração: ${dur} min\nETA: ${eta} min`;
  };

  if (loading) return <div className="alert-dashboard"><div className="empty-state">Carregando centro de comando...</div></div>;

  return (
    <div className="alert-dashboard">
      <div className="alert-header">
        <h1>Centro de Operações Sentinela</h1>
        <div className="status-indicator">
          {pendingAlerts.length} Pendentes | {activeAlerts.length} Ativos
        </div>
      </div>

      <div className="ops-grid">
        {/* LEFT COLUMN: PENDING QUEUE */}
        <div className="ops-column">
          <h2 className="column-title">Fila de Validação 📥</h2>
          {pendingAlerts.length === 0 ? (
            <div className="empty-state">Nenhum alerta pendente.</div>
          ) : (
            <div className="alert-list">
              {pendingAlerts.map(alert => {
                const payload = JSON.parse(alert.messagePayloadJson);
                const levelClass = alert.alertLevel.toLowerCase();
                const currentDuration = durations[alert.id] || 60;
                const currentEta = customEtas[alert.id];
                
                const dist = payload.MinDistance ?? payload.minDistance ?? 0;
                const impact = payload.Impact ?? payload.impact;
                const eta = currentEta !== undefined ? currentEta : (impact?.EtaMinutes ?? impact?.etaMinutes ?? '--');
                const lightningJump = impact?.LightningJump ?? impact?.lightning_jump;

                return (
                  <div key={alert.id} className={`alert-card ${levelClass}`}>
                    <div className="alert-card-header">
                      <div className="taker-name">{alert.takerName}</div>
                      <div className={`alert-badge ${levelClass}`}>{alert.alertLevel}</div>
                    </div>

                    {lightningJump && (
                      <div className="jump-indicator">⚡ LIGHTNING JUMP DETECTADO</div>
                    )}

                    <div className="alert-details">
                      <div className="detail-item">
                        <span className="detail-label">ETA Impacto</span>
                        <span className="detail-value highlight">{eta} min</span>
                      </div>
                      <div className="detail-item">
                        <span className="detail-label">Distância</span>
                        <span className="detail-value">{dist.toFixed(1)} km</span>
                      </div>
                    </div>

                    <div className="message-preview-box">
                      <pre>{getMessagePreview(alert, currentDuration, currentEta)}</pre>
                    </div>

                    <div className="alert-form">
                      <div className="form-row">
                        <label>ETA Impacto (min):</label>
                        <input 
                          type="number" 
                          placeholder={impact?.EtaMinutes ?? "--"}
                          value={currentEta !== undefined ? currentEta : ''} 
                          onChange={(e) => handleEtaChange(alert.id, parseInt(e.target.value))}
                        />
                      </div>
                      <div className="form-row">
                        <label>Duração do Alerta (min):</label>
                        <input 
                          type="number" 
                          value={currentDuration} 
                          onChange={(e) => handleDurationChange(alert.id, parseInt(e.target.value))}
                        />
                      </div>
                    </div>

                    <div className="alert-actions">
                      <button className="btn-approve" onClick={() => handleApprove(alert.id)}>
                        APROVAR E DISPARAR
                      </button>
                      <button className="btn-reject" onClick={() => handleReject(alert.id)}>
                        REJEITAR
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: ACTIVE ALERTS */}
        <div className="ops-column active-column">
          <h2 className="column-title">Monitoramento Ativo 🛰️</h2>
          {activeAlerts.length === 0 ? (
            <div className="empty-state">Nenhum alerta ativo no momento.</div>
          ) : (
            <div className="alert-list">
              {activeAlerts.map(alert => {
                const levelClass = alert.alertLevel.toLowerCase();
                const sentAt = new Date(alert.sentAt).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

                return (
                  <div key={alert.id} className={`alert-card active-card ${levelClass}`}>
                    <div className="alert-card-header">
                      <div className="taker-name">{alert.takerName}</div>
                      <div className="sent-badge">
                        {alert.sentAt ? `Ativo desde ${sentAt}` : "Pendente de envio"}
                        {alert.status === "Active" && alert.sentAt && <span className="auto-badge"> SISTEMA (Auto)</span>}
                      </div>
                    </div>

                    <div className="active-controls">
                      <div className="control-group">
                        <label>Alterar Nível:</label>
                        <div className="level-buttons">
                          <button 
                            className={alert.alertLevel === 'Yellow' ? 'active yellow' : ''}
                            onClick={() => handleUpdate(alert.id, 'Yellow', alert.durationMinutes)}
                          >AMARELO</button>
                          <button 
                            className={alert.alertLevel === 'Red' ? 'active red' : ''}
                            onClick={() => handleUpdate(alert.id, 'Red', alert.durationMinutes)}
                          >VERMELHO</button>
                        </div>
                      </div>

                      <div className="control-group">
                        <label>Duração Restante (min):</label>
                        <input 
                          type="number" 
                          defaultValue={alert.durationMinutes}
                          onBlur={(e) => handleUpdate(alert.id, alert.alertLevel, parseInt(e.target.value))}
                        />
                      </div>
                    </div>

                    <div className="alert-actions">
                      <button className="btn-close" onClick={() => handleClose(alert.id)}>
                        ENCERRAR MONITORAMENTO ✅
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default AlertDashboard;
