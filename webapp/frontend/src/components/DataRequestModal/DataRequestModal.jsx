import { useEffect, useState } from 'react';
import { submitDataRequest } from '../../services/lightningService';
import './DataRequestModal.css';

function buildInitialFormData(selectedTaker) {
  return {
    name: '',
    email: '',
    takerId: selectedTaker?.id ?? '',
    takerName: selectedTaker?.name || '',
    startTime: '',
    endTime: '',
    interval: '5',
    type: 'flashes',
  };
}

function validateForm(formData) {
  const errors = [];
  if (!formData.name.trim()) errors.push('Informe seu nome completo.');
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email.trim())) errors.push('Informe um e-mail valido.');
  if (formData.takerId === '' || formData.takerId === null || formData.takerId === undefined) errors.push('Selecione um tomador de servico.');
  if (!formData.takerName.trim()) errors.push('Selecione um tomador de servico.');
  if (!formData.startTime) errors.push('Informe o tempo inicial.');
  if (!formData.endTime) errors.push('Informe o tempo final.');

  if (formData.startTime && formData.endTime) {
    const start = new Date(formData.startTime);
    const end = new Date(formData.endTime);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
      errors.push('Informe um periodo valido.');
    } else if (end <= start) {
      errors.push('O tempo final deve ser posterior ao tempo inicial.');
    }
  }

  return errors;
}

async function readErrorMessage(response) {
  try {
    const data = await response.json();
    if (Array.isArray(data?.errors) && data.errors.length > 0) return data.errors.join(' ');
    if (data?.message) return data.message;
    if (data?.detail) return data.detail;
  } catch {
    // The response may not contain JSON.
  }

  return `Falha ao enviar solicitacao (${response.status}).`;
}

export default function DataRequestModal({ isOpen, onClose, selectedTaker, takerOptions = [] }) {
  const [formData, setFormData] = useState(() => buildInitialFormData(selectedTaker));
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedback, setFeedback] = useState(null);

  useEffect(() => {
    if (!isOpen) return;
    setFormData(buildInitialFormData(selectedTaker));
    setFeedback(null);
    setIsSubmitting(false);
  }, [isOpen, selectedTaker]);

  if (!isOpen) return null;

  const updateField = (field, value) => {
    setFormData((current) => ({ ...current, [field]: value }));
    if (feedback?.type === 'error') setFeedback(null);
  };

  const updateTaker = (value) => {
    const taker = takerOptions.find((item) => String(item.id) === String(value));
    setFormData((current) => ({
      ...current,
      takerId: value,
      takerName: taker?.name || '',
    }));
    if (feedback?.type === 'error') setFeedback(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (isSubmitting) return;

    const errors = validateForm(formData);
    if (errors.length > 0) {
      setFeedback({ type: 'error', message: errors.join(' ') });
      return;
    }

    setIsSubmitting(true);
    setFeedback(null);

    try {
      const response = await submitDataRequest({
        name: formData.name.trim(),
        email: formData.email.trim(),
        takerId: Number(formData.takerId),
        takerName: formData.takerName.trim(),
        startTime: formData.startTime,
        endTime: formData.endTime,
        intervalMinutes: Number(formData.interval),
        dataType: formData.type,
      });

      if (!response.ok) {
        throw new Error(await readErrorMessage(response));
      }

      const data = await response.json().catch(() => ({}));
      setFeedback({
        type: 'success',
        message: data?.message || 'Solicitacao enviada com sucesso. O retorno sera feito por e-mail.',
      });
    } catch (error) {
      setFeedback({
        type: 'error',
        message: error?.message || 'Nao foi possivel enviar a solicitacao no momento.',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="lt-modal-overlay">
      <div className="lt-modal">
        <div className="lt-modal__header">
          <div>
            <h2 className="lt-modal__title">Solicitar Historico de Dados</h2>
            <p className="lt-modal__description">
              Esta opcao e para a requisicao de dados de longo periodo com prazo de 24h para o retorno em seu e-mail.
            </p>
          </div>
          <button className="lt-modal__close" type="button" onClick={onClose} disabled={isSubmitting}>x</button>
        </div>
        
        <form className="lt-modal__form" onSubmit={handleSubmit}>
          <div className="lt-form-group">
            <label>Nome Completo</label>
            <input 
              type="text" 
              required 
              value={formData.name} 
              onChange={(e) => updateField('name', e.target.value)} 
              disabled={isSubmitting}
            />
          </div>
          
          <div className="lt-form-group">
            <label>E-mail para Recebimento</label>
            <input 
              type="email" 
              required 
              value={formData.email} 
              onChange={(e) => updateField('email', e.target.value)} 
              disabled={isSubmitting}
            />
          </div>

          <div className="lt-form-group">
            <label>Tomador de Servico</label>
            <select
              required
              value={formData.takerId}
              onChange={(e) => updateTaker(e.target.value)}
              disabled={isSubmitting}
            >
              {takerOptions.length === 0 && (
                <option value="">Nenhuma unidade carregada</option>
              )}
              {takerOptions.map((taker) => (
                <option key={taker.id} value={taker.id}>
                  {taker.name}
                </option>
              ))}
            </select>
          </div>

          <div className="lt-form-row">
            <div className="lt-form-group">
              <label>Tempo Inicial</label>
              <input 
                type="datetime-local" 
                required 
                value={formData.startTime} 
                onChange={(e) => updateField('startTime', e.target.value)} 
                disabled={isSubmitting}
              />
            </div>
            <div className="lt-form-group">
              <label>Tempo Final</label>
              <input 
                type="datetime-local" 
                required 
                value={formData.endTime} 
                onChange={(e) => updateField('endTime', e.target.value)} 
                disabled={isSubmitting}
              />
            </div>
          </div>

          <div className="lt-form-row">
            <div className="lt-form-group">
              <label>Intervalo (Acumulado)</label>
              <select 
                value={formData.interval} 
                onChange={(e) => updateField('interval', e.target.value)}
                disabled={isSubmitting}
              >
                <option value="1">1 minuto</option>
                <option value="5">5 minutos</option>
                <option value="15">15 minutos</option>
                <option value="60">1 hora</option>
              </select>
            </div>
            <div className="lt-form-group">
              <label>Tipo de Dado</label>
              <div className="lt-form-radio-group">
                <label>
                  <input 
                    type="radio" 
                    name="type" 
                    value="flashes" 
                    checked={formData.type === 'flashes'} 
                    onChange={() => updateField('type', 'flashes')}
                    disabled={isSubmitting}
                  /> Flashes
                </label>
                <label>
                  <input 
                    type="radio" 
                    name="type" 
                    value="eventos" 
                    checked={formData.type === 'eventos'} 
                    onChange={() => updateField('type', 'eventos')}
                    disabled={isSubmitting}
                  /> Eventos
                </label>
              </div>
            </div>
          </div>

          {feedback && (
            <div className={`lt-modal__feedback lt-modal__feedback--${feedback.type}`} role="status">
              {feedback.message}
            </div>
          )}

          <button type="submit" className="lt-modal__submit" disabled={isSubmitting}>
            {isSubmitting ? 'Enviando...' : 'Enviar Solicitacao'}
          </button>
        </form>
      </div>
    </div>
  );
}
