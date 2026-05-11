# 🔧 Backend — Lightning Tracker Web API

> API .NET 8 que orquestra processos Python, serve dados ao frontend e gerencia alertas em tempo real.

---

## Stack Tecnológico

| Tecnologia | Versão | Função |
|---|---|---|
| .NET | 8.0 | Runtime Web API |
| Npgsql | 8.0.8 | Driver PostgreSQL |
| Microsoft.Data.Sqlite | 8.0.8 | Driver SQLite |
| Python | 3.11+ | Subprocessos de renderização e sync |

---

## 📁 Estrutura

```
webapp/backend/
├── Program.cs                      # ⭐ Entry point — registra serviços e endpoints
├── LightningTracker.WebApi.csproj  # Projeto .NET 8
├── appsettings.json                # Configuração (paths, sync, python)
├── Endpoints/
│   ├── LightningTrackerEndpoints.cs # ⭐ Todos os endpoints HTTP (Minimal API)
│   └── RenderQuery.cs               # Record de normalização de parâmetros de render
├── Models/
│   ├── LightningEvent.cs            # Record: Id, Kind, EventTime, Lat, Lon, Intensity
│   ├── ServiceTaker.cs              # Record: Id, Name, Lat, Lon
│   └── TableResponses.cs            # Record: resposta de tabela gerada
├── Services/
│   ├── ConfigurationService.cs      # ⭐ Configuração centralizada (env vars + appsettings)
│   ├── GlmSyncHostedService.cs      # ⭐ Background worker — sync GLM→PostgreSQL
│   ├── LightningDataService.cs      # ⭐ Queries PostgreSQL com filtro Haversine
│   ├── PythonRenderService.cs       # Invoca web_render.py (PNG/MP4)
│   ├── PythonTableService.cs        # Invoca web_tables.py (tabelas de frequência)
│   ├── PythonBackgroundService.cs   # Invoca web_background.py (background IR local)
│   ├── PythonAbiService.cs          # Invoca web_abi_tile.py (tile ABI full-disk)
│   ├── PythonActivityService.cs     # Invoca web_auto_select.py (tomador ativo)
│   └── TableCatalogService.cs       # Catálogo de tabelas salvas (filesystem + PG)
├── Workers/
│   └── LightningAlertWorker.cs      # ⭐ Motor de alertas WhatsApp (Sentinel)
├── Data/
│   └── ServiceTakerRepository.cs    # Repositório de tomadores (SQLite + CSV fallback)
└── db/
    ├── init_schema_postgres.sql     # Schema completo PostgreSQL + PostGIS
    ├── schema.sql                   # Schema simplificado (service_takers)
    ├── service_takers.sqlite        # Banco SQLite de tomadores
    └── alert_contacts.json          # Lista de contatos para alertas WhatsApp
```

---

## 🌐 Endpoints da API

### Dados
| Método | Rota | Descrição | Params |
|--------|------|-----------|--------|
| GET | `/api/takers` | Lista todos os tomadores | — |
| GET | `/api/takers/active` | Tomador ativo por padrão | — |
| GET | `/api/events` | Eventos de relâmpagos (JSON) | `takerId`, `mode`, `startLocal`, `endLocal`, `initialLoadHours` |

### Renderização (Python subprocess)
| Método | Rota | Descrição | Params |
|--------|------|-----------|--------|
| GET | `/api/render` | Mapa PNG (Matplotlib) | `takerId`, `mode`, `startLocal`, `endLocal`, `background`, `binMinutes` |
| GET | `/api/render/frame` | Frame único PNG | Igual a render + `thumb` |
| GET | `/api/render/animation` | Animação MP4 | `takerId`, `mode`, `startLocal`, `endLocal`, `binMinutes` |

### Imagem Satélite
| Método | Rota | Descrição | Params |
|--------|------|-----------|--------|
| GET | `/api/background` | Background IR recortado (por tomador) | `takerId`, `endLocal` |
| GET | `/api/abi` | Tile ABI IR full-disk (reprojetado) | `utc`, `cmap` |

### Tabelas
| Método | Rota | Descrição | Params |
|--------|------|-----------|--------|
| GET | `/api/tables/generate` | Gera tabela de frequência | `takerId`, `endLocal`, `period`, `binSize` |
| GET | `/api/tables/latest` | Lista tabelas salvas | `takerId`, `limit` |
| GET | `/api/tables/load` | Carrega tabela salva | `relativePath` |

---

## ⚡ Serviços Críticos

### `GlmSyncHostedService`
Background worker que executa `sync_recent_glm_to_postgres.py` periodicamente.

```
Ciclo: a cada 300s (configurável)
  1. Executa Python com --lookback-minutes e --retention-hours
  2. Python baixa GLM recentes do S3 → insere no PostgreSQL
  3. Purga blobs antigos além da janela de retenção
  4. Limpa arquivos .nc locais se cleanup_enabled=true
```

**Configuração** (`appsettings.json`):
```json
{
  "Sync": {
    "Enabled": true,
    "IntervalSeconds": 300,
    "LookbackMinutes": 5,
    "RetentionHours": 3,
    "KeepRawFiles": false
  }
}
```

### `LightningAlertWorker` (Sentinel)
Motor de alertas em tempo real via WhatsApp (Z-API).

```
Ciclo: a cada 2 minutos
  1. Para cada tomador com contatos em alert_contacts.json:
  2. Busca eventos dos últimos 10 min (raio 500km)
  3. Calcula distância mínima via Haversine
  4. Determina nível de alerta:
     🔴 Red:       ≤ 100km  → atualização em tempo real
     🟡 Yellow:    100-200km → atualização a cada 20min
     ⚠️ Observing: 200-500km → atualização a cada 60min
     ✅ Green:     20min sem atividade → encerramento
  5. Envia mensagem formatada via Z-API WhatsApp
```

**Templates de mensagem**:
- **Observing**: Notificação de tempestade na região
- **Yellow**: Dados de proximidade + previsão 30min
- **Red**: Alerta urgente + previsão 15min + instrução de abrigo
- **Green**: Condições normalizadas

### `LightningDataService`
Acesso direto ao PostgreSQL com filtragem espacial.

```
Estratégia de query:
  1. Bounding box SQL (filtro rápido aproximado)
  2. Haversine em C# (filtro preciso circular)
  3. takerId=0 → busca América do Sul inteira (bbox: -60/15 lat, -90/-30 lon)
```

### `ServiceTakerRepository`
```
Prioridade de fonte de dados:
  1. SQLite (db/service_takers.sqlite) — tabela tomadores_servico
  2. CSV fallback (config/service_takers.csv) — separador ";"
  3. ID=0 → virtual "América do Sul" (lat=-14, lon=-52)
```

---

## ⚙️ Configuração

### `appsettings.json`
```json
{
  "Data": {
    "ServiceTakersDbPath": "db/service_takers.sqlite",
    "TablesRootPath": "..\\..\\output\\tables"
  },
  "Python": {
    "Command": "python",
    "WorkingDirectory": "..\\.."
  }
}
```

### Variáveis de Ambiente (override)
Todas as configs de `ConfigurationService` podem ser sobrescritas por env vars:

| Env Var | appsettings Key | Default |
|---|---|---|
| `LIGHTNING_TRACKER_PG_DSN` | `Data:PostgresDsn` | — |
| `LIGHTNING_TRACKER_PYTHON_CMD` | `Python:Command` | `python` |
| `LIGHTNING_TRACKER_SYNC_ENABLED` | `Sync:Enabled` | `true` |
| `LIGHTNING_TRACKER_SYNC_INTERVAL_SECONDS` | `Sync:IntervalSeconds` | `300` |

---

## 🔌 Integração com Python

O backend C# invoca scripts Python via `System.Diagnostics.Process`:

```
Python Working Directory: ../../  (raiz do lightning_tracker)

Scripts invocados:
  - scripts/sync_recent_glm_to_postgres.py  → GlmSyncHostedService
  - scripts/web_abi_tile.py                 → PythonAbiService
  - src/web_render.py                       → PythonRenderService (via -m)
  - src/web_tables.py                       → PythonTableService (via -m)
  - src/web_background.py                   → PythonBackgroundService (via -m)
  - src/web_auto_select.py                  → PythonActivityService (via -m)
```

Protocolo de comunicação: **stdout** (bytes PNG/JSON) + **stderr** (logs).
Headers de metadados são passados via linhas prefixadas (ex: `BOUNDS:lat,lon,lat,lon`).

---

## 🚀 Execução

```bash
cd webapp/backend
dotnet run                           # Dev (porta 5080)
dotnet run --urls http://0.0.0.0:5080  # Produção
```
