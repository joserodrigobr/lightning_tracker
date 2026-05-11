# 🌩️ Guia de Operação: Sistema Sentinel BlueOcean

O **Sentinel** é o motor de monitoramento proativo da BlueOcean, projetado para fornecer alertas de relâmpagos baseados em geofencing e análise de progressão de tempestades (Nowcast).

---

## 1. Níveis de Alerta e Gatilhos Espaciais

O sistema opera em quatro estados principais, definidos pela distância do relâmpago mais próximo em relação à unidade monitorada:

| Nível | Status | Gatilho (Distância) | Ação de Comunicação |
| :--- | :--- | :--- | :--- |
| **⚠️** | **OBSERVAÇÃO** | Raio detectado em **500km** | Aviso inicial de vigilância. |
| **🟡** | **AMARELO** | Raio detectado em **200km** | Alerta de proximidade e previsão de chegada. |
| **🔴** | **VERMELHO** | Raio detectado em **100km** | Alerta crítico de segurança e perigo imediato. |
| **✅** | **VERDE** | Sem raios em **500km** | Aviso de normalização e encerramento. |

---

## 2. Fluxo de Validação (Human-in-the-Loop)

Para garantir precisão, os alertas passam por uma triagem:
1. **Detecção Automática**: O Sentinel identifica a ameaça e gera um card na **Fila de Validação**.
2. **Ação do Meteorologista**: O operador avalia o mapa, ajusta o **ETA Manual** se necessário, e clica em **Aprovar e Disparar**.
3. **Auto-Approve**: Alertas com *Lightning Jump* (intensificação rápida) e alta confiança são enviados automaticamente.

---

## 3. Catálogo de Mensagens (Outputs)

### ⚠️ Situação: Início do Monitoramento (Observação)
*Enviada quando a atividade entra no raio de 500km.*

> ⚠️ **SENTINEL BLUEOCEAN** ⚠️
>
> Olá **[Nome]**! Sou o **Sentinel**, sistema de monitoramento da BLUEOCEAN.
> Estamos observando uma intensificação de tempestade na região da unidade: **[Unidade]**.

---

### 🟡 Situação: Alerta Amarelo
*Gatilho: Proximidade < 200km.*

> 🟡 **ALERTA AMARELO - SENTINELA**
>
> Olá **[Nome]**! 
> **Foram detectados raios nas proximidades da unidade [Unidade].**
>
> 📊 **Informações de proximidade:**
> 🟠 Até 30km: [X] 
> 🟡 Até 50km: [Y] 
> 🟢 Até 100km: [Z] 
> 🔵 Até 200km: [W]
>
> ⛈️ **Total de raios:** [Total]
> 💡 **Previsão:** Chegada estimada em **[ETA] minutos**.
>
> 📍 Veja no mapa: http://nowcast.blueocean.com

---

### 🔴 Situação: Alerta Vermelho
*Gatilho: Proximidade < 100km.*

> 🔴 **ALERTA VERMELHO - SENTINELA**
>
> Olá **[Nome]**! 
> **Foram detectados raios nas proximidades da unidade [Unidade].**
>
> 📊 **Informações de proximidade:** (Lista de alcances)
>
> ⛈️ **Total de raios:** [Total]
> 💡 **Previsão:** Impacto iminente. ETA: **[ETA] minutos**.
>
> 📍 Veja no mapa: http://nowcast.blueocean.com
>
> **ATENÇÃO:** Procure abrigo seguro e evite áreas abertas.

---

### 🔄 Atualizações Automáticas (Active Monitoring)
*Enviadas a cada **30 minutos** para alertas ativos (Amarelo/Vermelho).*

> 🔴 **ATUALIZAÇÃO PERIÓDICA - SENTINELA**
>
> Olá **[Nome]**! Seguem as informações atualizadas para a unidade **[Unidade]**:
>
> 📊 **Resumo de Proximidade (Últimos 10 min):** (Lista de alcances)
> ⛈️ **Total de raios na região:** [Total]
>
> A próxima atualização automática será enviada às aproximadamente **[HH:MM]**.

---

## 4. Lógica de Temporização

*   **Ciclo de Varredura**: O sistema verifica novas condições a cada **2 minutos**.
*   **Frequência de Atualização**: Automática a cada **30 minutos**.
*   **Encerramento**: O meteorologista deve encerrar o alerta manualmente no Dashboard quando a ameaça passar, disparando a mensagem "Green".
*   **Re-queuing**: Se o meteorologista encerrar um alerta mas raios persistirem no raio de risco, o sistema criará um novo alerta para validação após o próximo ciclo.
