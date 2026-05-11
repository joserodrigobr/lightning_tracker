# 🖥️ Frontend — Lightning Tracker

> Interface web React + Leaflet para visualização de relâmpagos em tempo real.

---

## Stack Tecnológico

| Tecnologia | Versão | Função |
|---|---|---|
| React | 19.x | Framework UI |
| Vite | 8.x | Build tool + dev server |
| Leaflet | 1.9.x | Mapas interativos |
| react-leaflet | 5.x | Bindings React para Leaflet |

---

## 📁 Estrutura

```
webapp/frontend/
├── package.json
├── vite.config.js              # Proxy /api → backend :5080
├── index.html
├── public/
│   └── alert.mp3               # Som de alerta para novos relâmpagos
├── src/
│   ├── App.jsx                 # ⭐ Componente principal (state manager)
│   ├── App.css                 # Estilos globais
│   ├── main.jsx                # Entry point React
│   ├── components/
│   │   ├── Header.jsx/.css         # Barra superior com menu hamburger
│   │   ├── LightningMap.jsx/.css   # ⭐ Mapa Leaflet com markers e overlays
│   │   ├── ControlPanel.jsx/.css   # Painel de controle (filtros, tomador, modo)
│   │   ├── StatsPanel.jsx/.css     # Painel de estatísticas (contadores por anel)
│   │   ├── SideMenu.jsx/.css       # Menu lateral (tabelas, gráficos, download)
│   │   ├── ChartModal.jsx/.css     # Modal de gráficos de barras
│   │   ├── TableModal.jsx/.css     # Modal de visualização de tabelas
│   │   ├── DataRequestModal.jsx/.css # Modal de requisição de dados
│   │   └── AlertDashboard.jsx/.css  # ⭐ Centro de Operações Sentinel (Aprovação de Alertas)
│   ├── hooks/
│   │   ├── useEvents.js            # ⭐ Hook de fetch de eventos (polling 60s)
│   │   └── useAbiOverlay.js        # Hook de overlay ABI IR (polling 10min)
│   └── utils/
│       └── haversine.js            # Haversine + jetColor para coloração temporal
```

---

## 🔄 Fluxo de Dados

```
App.jsx (State Manager)
  │
  ├── useEvents()          → GET /api/events?takerId=&mode=&startLocal=&endLocal=
  │   └── Retorna: events[], stats { total, last5min, byRing[4] }
  │
  ├── useAbiOverlay()      → GET /api/abi?utc=&cmap=
  │   └── Retorna: abiUrl (blob), abiBounds [[lat,lon],[lat,lon]]
  │
  ├── loadTakers()         → GET /api/takers
  │   └── Retorna: [{id, name, lat, lon}]
  │
  ├── generateTable()      → GET /api/tables/generate?takerId=&period=&binSize=
  │   └── Retorna: { hourLabels[], radiiLabels[], values4x24[][] }
  │
  └── downloadCurrentImage() → GET /api/render?takerId=&mode=&startLocal=&endLocal=
      └── Retorna: image/png (Matplotlib render)
```

---

## 🗺️ Componentes Principais

### `App.jsx`
- **Gerenciador de estado central** — controla todos os filtros, modais e dados
- Mantém estado de: `takerId`, `mode`, `startLocal/endLocal`, `backgroundIr`, `animating`, `playbackTime`
- Coordena fetch de eventos, tabelas, gráficos e downloads
- **Tomador especial**: `id=0` → "América do Sul" (visão continental sem filtro espacial)

### `LightningMap.jsx`
- Renderiza mapa Leaflet com:
  - **Markers**: Círculos coloridos por tempo (jet colormap: azul=antigo → vermelho=recente)
  - **Anéis de proximidade**: 30/50/100/200 km ao redor do tomador
  - **ABI IR overlay**: Imagem de satélite infravermelha como ImageOverlay
  - **Animação**: Playback temporal com controles play/pause/step
### `AlertDashboard.jsx`
- **Centro de Operações Sentinel** — Interface para meteorologistas.
- **Fila de Validação**: Exibe alertas pendentes com métricas de impacto, ETA e botões de aprovação/rejeição.
- **Monitoramento Ativo**: Lista alertas em curso, permitindo estender a duração, alterar o nível ou encerrar manualmente.
- **Badges de Intensidade**: Sinaliza visualmente ocorrências de **Lightning Jump** e alertas **Auto-Aprovados**.
- **Polling**: Atualiza automaticamente a cada 10 segundos.

### `useEvents.js`
- Polling automático a cada 60s
- Calcula estatísticas por anel (30/50/100/200 km)
- **Alerta sonoro**: Toca `alert.mp3` quando novos flashes são detectados (burst de até 5 sons)
- Suporta modo continental (takerId=0) sem cálculo de distância

### `useAbiOverlay.js`
- Fetch de tile ABI IR via blob URL
- Lê bounds geográficos do header `X-Abi-Bounds`
- Auto-refresh a cada 10 minutos
- Cleanup de blob URLs no unmount

---

## ⚙️ Configuração

### `vite.config.js`
```js
server: {
  proxy: {
    '/api': {
      target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:5080',
      changeOrigin: true,
    },
  },
}
```

### Variáveis de Ambiente
| Variável | Default | Descrição |
|---|---|---|
| `VITE_API_PROXY_TARGET` | `http://127.0.0.1:5080` | URL do backend C# |

---

## 🎨 Padrões de Design

1. **Timezone**: Todas as datas são tratadas como BRT (UTC-3). O frontend envia `startLocal`/`endLocal` em hora local.
2. **Auto-seleção**: Na primeira carga, tenta geolocalização do browser para selecionar o tomador mais próximo. Fallback: `/api/active-taker`.
3. **CSV Export**: Tabelas são convertidas localmente para CSV com separador `;` e encoding UTF-8.
4. **Animation**: Playback client-side filtrando eventos por janela temporal. Velocidade configurável.

---

## 🚀 Desenvolvimento

```bash
cd webapp/frontend
npm install
npm run dev          # Dev server com HMR
npm run build        # Build de produção
npm run preview      # Preview do build
```
