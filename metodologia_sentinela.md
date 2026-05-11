# Metodologia Técnica: Motor de Nowcast Sentinela (BLUEOCEAN)

Esta documentação descreve a arquitetura, algoritmos e lógica operacional do sistema **Sentinela**, responsável pelo rastreamento de tempestades e geração de alertas preditivos de raios.

---

## 1. Ingestão e Processamento de Dados (Camada GLM)
O sistema utiliza dados em tempo real do sensor **GLM (Geostationary Lightning Mapper)** a bordo do satélite GOES-16/19.

### 1.1 Unidades de Dado
*   **Events:** Ativações de pixels individuais no CCD do satélite (pixels de ~8km).
*   **Flashes:** Conjunto de eventos associados temporal e espacialmente, representando um raio completo.
*   **Processamento de Grade:** Para garantir a robustez, o sistema funde os dados de Flashes (para movimento) e Events (para geometria), criando uma grade de ocupação.

---

## 2. Identificação de Células de Tempestade (Clusterização)
O motor utiliza o algoritmo **DBSCAN (Density-Based Spatial Clustering of Applications with Noise)** com métrica de distância Haversine (esférica).

*   **EPS (Raio de Busca):** 60 km. Definido para capturar sistemas convectivos de mesoescala (tropicais) sem fragmentá-los.
*   **Min Samples:** 3 pontos. Permite identificar células em estágio inicial (nascimento da tempestade).
*   **Janela Temporal:** 10 minutos por quadro (sliding window), garantindo que a "massa" da tempestade tenha corpo suficiente para ser processada.

---

## 3. Definição da Geometria (Density Grid Polygons)
Diferente de polígonos orgânicos tradicionais (Concave Hull) que podem falhar ou ser instáveis, o Sentinela utiliza uma **Grade de Densidade Quadrada**:

1.  O espaço é discretizado em células de **0.05° x 0.05° (~5.5km)**.
2.  Toda célula da grade que contenha pelo menos um raio (Flash ou Event) é marcada como "Ativa".
3.  **Dilatação Espacial (Buffer):** Para cada célula ativa, o sistema adiciona automaticamente suas 8 vizinhas imediatas. Isso cria uma "Zona de Influência" de segurança e preenche falhas internas na detecção.
4.  O polígono final é a união destes quadrados, resultando em uma área de risco "pixelizada" e conservadora.

---

## 4. Rastreamento e Trajetória (Tracking)
O rastreamento temporal é feito comparando células entre quadros sucessivos (t e t-1) usando o **Algoritmo de Atribuição Húngaro (Hungarian Method)**:

*   **Custo de Associação:** Baseado na distância euclidiana entre centros de massa e similaridade de área.
*   **Cálculo de Vetor:** O deslocamento do centro de massa nos últimos 30 minutos é suavizado para calcular a **Velocidade (km/h)** e o **Azimute (Direção)** da tempestade.
*   **Projeção Linear:** A posição futura é projetada para os horizontes de **15, 30 e 60 minutos**, assumindo persistência de movimento.

---

## 5. Análise de Impacto e ETA
Para cada unidade de serviço (tomador), o sistema realiza uma varredura de intersecção:

1.  **Anéis de Alcance:** Monitora perímetros de 30km, 50km, 100km e 200km.
2.  **Cálculo de ETA (Nowcast):** O sistema simula o deslocamento do polígono da tempestade ao longo do vetor. O impacto é registrado quando a borda do polígono toca o anel de alcance da unidade.
3.  **Fallback de Proximidade:** Caso a tempestade esteja em rota incerta ou estacionária mas dentro de um raio de interesse (<100km), o sistema calcula um ETA conservador baseado na distância direta dividida pela velocidade da célula mais próxima, garantindo que o operador nunca fique sem uma estimativa de tempo.

---

## 6. Fluxo Humano de Alertas (Sentinela Operations)
O sistema opera em ciclos de **2 minutos**, garantindo alta responsividade:

1.  **Gatilho:** Se uma tempestade tem impacto previsto ou proximidade crítica, um alerta **Pendente** é gerado na Fila de Validação.
2.  **Validação & Controle Manual:** O meteorologista avalia a consistência no mapa, podendo inserir um **ETA Manual** verificado e ajustar a duração prevista.
3.  **Atualizações Automáticas:** Alertas ativos (Red/Yellow) recebem atualizações automáticas no WhatsApp a cada **30 minutos**, contendo o resumo de raios por anel e o horário da próxima mensagem programada.
4.  **Auto-Approve:** Tempestades com detecção de *Lightning Jump* (intensificação súbita > 2σ) e alta confiança de rastreamento são aprovadas automaticamente.
5.  **Ciclo de Vida:**
    *   **Ativo:** Monitoramento intensivo com atualizações periódicas.
    *   **Resolvido:** Envio de mensagem de normalização ("Green") após dissipação ou afastamento da ameaça.
    *   **Re-queuing:** Se as condições de risco retornarem após o encerramento, o sistema reabre o alerta para nova validação.

---

## 7. Infraestrutura de Mensageria
A comunicação é feita via **WhatsApp API (Z-API)**, utilizando templates focados em clareza operacional:
*   Contagem de raios segmentada por anéis (30/50/100/200km).
*   Estimativa de chegada (ETA) validada e velocidade de deslocamento.
*   Link direto para o mapa de monitoramento em tempo real.
