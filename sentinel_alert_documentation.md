# 🌩️ Guia de Operação: Sistema Sentinel BlueOcean

O **Sentinel** é o motor de monitoramento proativo da BlueOcean, projetado para fornecer alertas de relâmpagos baseados em geofencing e análise de progressão de tempestades.

---

## 1. Níveis de Alerta e Gatilhos Espaciais

O sistema opera em quatro estados principais, definidos pela distância do relâmpago mais próximo em relação à unidade monitorada:

| Nível | Status | Gatilho (Distância) | Ação de Comunicação |
| :--- | :--- | :--- | :--- |
| **⚠️** | **OBSERVAÇÃO** | Raio detectado em **200km** | Aviso inicial de vigilância e intensificação. |
| **🟡** | **AMARELO** | Raio detectado em **50km** | Alerta de proximidade e previsão de chegada. |
| **🔴** | **VERMELHO** | Raio detectado em **30km** | Alerta crítico de segurança e perigo imediato. |
| **✅** | **VERDE** | Sem raios em **200km** | Aviso de normalização e encerramento. |

---

## 2. Catálogo de Mensagens (Outputs)

### ⚠️ Situação: Início do Monitoramento (Observação)
*Enviada uma única vez quando a atividade entra no raio de 200km.*

> ⚠️ **SENTINEL BLUEOCEAN** ⚠️
>
> Estamos observando uma intensificação de tempestade na região da unidade: **[Unidade]**.
>
> Nossa equipe está em vigilância. Caso o tempo mude ou a atividade se aproxime, enviaremos novos alertas imediatamente.
>
> 📍 Acompanhe ao vivo: http://nowcast.blueocean.com

---

### 🟡 Situação: Alerta Amarelo
*Gatilho: Proximidade < 50km.*

#### **Primeiro Disparo (Com Previsão):**
> 🟡 **ALERTA AMARELO**
>
> Olá **[Nome]**! 
> **Foram detectados raios a [KM] km de distância da unidade [Unidade].**
>
> 📊 **Informações de proximidade:**
> 🟠 Até 30km: [X] 
> 🟡 Até 50km: [Y] 
> 🟢 Até 100km: [Z] 
> 🔵 Até 200km: [W]
>
> ⛈️ **Total de raios:** [Total]
> 📍 **Raio mais próximo:** [KM] km
>
> 💡 **Previsão:** Existe a probabilidade de ocorrência de relâmpagos em **30 minutos** na região.
>
> 📍 Veja no mapa: http://nowcast.blueocean.com
>
> Continuaremos enviando atualizações conforme a proximidade dos eventos.

#### **Atualizações (Manutenção de Status):**
*Enviadas a cada 20 minutos enquanto o status for Amarelo.*
> (Mesmo corpo de dados acima)
> 
> 💡 **Status:** O alerta amarelo irá se manter por mais **30 minutos**, exceto que mude para alerta vermelho.

---

### 🔴 Situação: Alerta Vermelho
*Gatilho: Proximidade < 30km.*

#### **Primeiro Disparo (Crítico):**
> 🔴 **ALERTA VERMELHO**
>
> Olá **[Nome]**! 
> **Foram detectados raios a [KM] km de distância da unidade [Unidade].**
>
> 📊 **Informações de proximidade:**
> (Lista de alcances conforme acima)
>
> ⛈️ **Total de raios:** [Total]
> 📍 **Raio mais próximo:** [KM] km
>
> 💡 **Previsão:** Existe a probabilidade de ocorrência de relâmpagos em **15 minutos**.
>
> 📍 Veja no mapa: http://nowcast.blueocean.com
>
> **ATENÇÃO:** Procure abrigo seguro e evite áreas abertas.

#### **Atualizações em Tempo Real:**
*Enviadas a cada 2 minutos enquanto o status for Vermelho.*
*Nota: A seção de previsão é removida para focar apenas nos dados de contagem.*
> (Mesmo corpo de dados, sem a seção de previsão)

---

### ✅ Situação: Encerramento (Alerta Verde)
*Gatilho: 1 hora completa sem nenhuma atividade em 200km.*

> ✅ **ALERTA VERDE - BLUEOCEAN** ✅
>
> Condições normalizadas. Sem registro de relâmpagos na última hora para as proximidades da unidade **[Unidade]**.

---

## 3. Lógica de Temporização e Exceções

### Frequência de Atualização (Mesmo Nível)
*   **Nível Vermelho:** Tempo Real (Verificação a cada **2 minutos**).
*   **Nível Amarelo:** A cada **20 minutos**.
*   **Nível Observação:** A cada **1 hora**.

### Exceção de Escalação Imediata
Se os primeiros raios detectados já estiverem dentro do raio de **30km**:
1.  O sistema envia a mensagem de **OBSERVAÇÃO**.
2.  Após **2 segundos**, envia o **ALERTA VERMELHO**.

### Inatividade
O cronômetro de 1 hora para o **Alerta Verde** é resetado a cada novo raio detectado no raio de monitoramento (200km).
