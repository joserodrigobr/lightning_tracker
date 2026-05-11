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

1.  **Anéis de Alcance:** Monitora perímetros de 30km (Amarelo) e 50km (Vermelho).
2.  **Cálculo de ETA:** O sistema simula o deslocamento do polígono da tempestade ao longo do vetor. O impacto é registrado quando a borda do polígono (considerando sua expansão) toca o anel de alcance da unidade.

---

## 6. Fluxo Humano de Alertas (Sentinela Operations)
Para evitar alarmes falsos, o sistema implementa um workflow de **Human-in-the-loop**:

1.  **Gatilho:** Se uma tempestade tem ETA <= 30min para uma unidade, um alerta **Pendente** é gerado.
2.  **Validação:** O meteorologista avalia a consistência no mapa, ajusta a duração prevista e aprova o envio.
3.  **Ciclo de Vida:**
    *   **Ativo:** Após aprovação, o alerta é monitorado. O meteorologista pode atualizar o nível (ex: Amarelo -> Vermelho) se a situação piorar.
    *   **Resolvido:** Quando a tempestade se afasta ou dissipa, o meteorologista encerra o alerta, enviando a mensagem de normalização via WhatsApp.

---

## 7. Infraestrutura de Mensageria
A comunicação é feita via **WhatsApp API (Z-API)**, utilizando templates profissionais que incluem:
*   Contagem de raios e distância mínima.
*   Estimativa de chegada (ETA) e velocidade.
*   Recomendações de segurança baseadas no nível de risco.
