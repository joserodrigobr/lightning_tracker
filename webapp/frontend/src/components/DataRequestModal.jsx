import { useState } from 'react';
import './DataRequestModal.css';

export default function DataRequestModal({ isOpen, onClose, selectedTaker }) {
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    takerName: selectedTaker?.name || '',
    startTime: '',
    endTime: '',
    interval: '5',
    type: 'flashes'
  });

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    // In a real app, this would send an email or call an API
    alert(`Solicitação enviada com sucesso!\n\nPara: ${formData.email}\nPeríodo: ${formData.startTime} até ${formData.endTime}`);
    onClose();
  };

  return (
    <div className="lt-modal-overlay">
      <div className="lt-modal">
        <div className="lt-modal__header">
          <div>
            <h2 className="lt-modal__title">Solicitar Histórico de Dados</h2>
            <p className="lt-modal__description">
              Esta opção é para a requisição de dados de longo período com prazo de 24h para o retorno em seu e-mail.
            </p>
          </div>
          <button className="lt-modal__close" onClick={onClose}>✕</button>
        </div>
        
        <form className="lt-modal__form" onSubmit={handleSubmit}>
          <div className="lt-form-group">
            <label>Nome Completo</label>
            <input 
              type="text" 
              required 
              value={formData.name} 
              onChange={e => setFormData({...formData, name: e.target.value})} 
            />
          </div>
          
          <div className="lt-form-group">
            <label>E-mail para Recebimento</label>
            <input 
              type="email" 
              required 
              value={formData.email} 
              onChange={e => setFormData({...formData, email: e.target.value})} 
            />
          </div>

          <div className="lt-form-group">
            <label>Tomador de Serviço</label>
            <input 
              type="text" 
              value={formData.takerName} 
              readOnly 
            />
          </div>

          <div className="lt-form-row">
            <div className="lt-form-group">
              <label>Tempo Inicial</label>
              <input 
                type="datetime-local" 
                required 
                value={formData.startTime} 
                onChange={e => setFormData({...formData, startTime: e.target.value})} 
              />
            </div>
            <div className="lt-form-group">
              <label>Tempo Final</label>
              <input 
                type="datetime-local" 
                required 
                value={formData.endTime} 
                onChange={e => setFormData({...formData, endTime: e.target.value})} 
              />
            </div>
          </div>

          <div className="lt-form-row">
            <div className="lt-form-group">
              <label>Intervalo (Acumulado)</label>
              <select 
                value={formData.interval} 
                onChange={e => setFormData({...formData, interval: e.target.value})}
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
                    onChange={() => setFormData({...formData, type: 'flashes'})}
                  /> Flashes
                </label>
                <label>
                  <input 
                    type="radio" 
                    name="type" 
                    value="eventos" 
                    checked={formData.type === 'eventos'} 
                    onChange={() => setFormData({...formData, type: 'eventos'})}
                  /> Eventos
                </label>
              </div>
            </div>
          </div>

          <button type="submit" className="lt-modal__submit">Enviar Solicitação</button>
        </form>
      </div>
    </div>
  );
}
