# 🗄️ Banco de Dados — Lightning Tracker

> Dual-database: PostgreSQL + PostGIS (produção) e SQLite (fallback/tomadores).

---

## Visão Geral

```
┌─────────────────────────────────────────────────────┐
│                   PostgreSQL + PostGIS               │
│  ┌──────────────┐  ┌──────────────────┐             │
│  │  raw_files   │  │ lightning_events │             │
│  │  (metadados  │──│  (flashes +      │             │
│  │   + blobs)   │  │   events norm.)  │             │
│  └──────────────┘  └──────────────────┘             │
│  ┌──────────────┐  ┌──────────────────┐             │
│  │ daily_tables │  │  table_catalog   │             │
│  │  (CSV/JSON   │──│  (catálogo de    │             │
│  │   por dia)   │  │   tabelas)       │             │
│  └──────────────┘  └──────────────────┘             │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                    SQLite (Local)                     │
│  ┌────────────────────┐                              │
│  │ tomadores_servico  │  ← service_takers.sqlite     │
│  │ (id, nome, lat,    │                              │
│  │  lon)              │                              │
│  └────────────────────┘                              │
└─────────────────────────────────────────────────────┘
```

---

## 📋 Schema PostgreSQL

### `raw_files` — Metadados dos arquivos NetCDF ingeridos

```sql
CREATE TABLE raw_files (
  id              bigserial PRIMARY KEY,
  source_url      text,                          -- ex: s3://noaa-goes19/GLM-L2-LCFA/...
  source_time     timestamptz,                   -- timestamp extraído do nome do arquivo
  downloaded_at   timestamptz DEFAULT now(),
  file_format     text,                          -- 'NetCDF4'
  checksum        text,
  uncompressed_size bigint,
  compressed_size bigint,
  bbox            geometry(Polygon,4326),        -- bounding box PostGIS
  min_lat/max_lat double precision,
  min_lon/max_lon double precision,
  compressed_blob bytea,                         -- blob comprimido (vazio no sync rápido)
  metadata        jsonb,
  created_at      timestamptz DEFAULT now(),
  UNIQUE (source_url, source_time)
);
```

**Índices**:
- `idx_raw_files_source_time` — busca temporal
- `idx_raw_files_bbox_gist` — busca espacial PostGIS

### `lightning_events` — Eventos normalizados (tabela principal)

```sql
CREATE TABLE lightning_events (
  id           bigserial PRIMARY KEY,
  raw_file_id  bigint REFERENCES raw_files(id) ON DELETE SET NULL,
  kind         text NOT NULL DEFAULT 'flash',    -- 'flash' ou 'event'
  event_time   timestamptz NOT NULL,             -- momento do relâmpago (UTC)
  geom         geometry(Point,4326) NOT NULL,    -- ponto PostGIS
  latitude     double precision NOT NULL,
  longitude    double precision NOT NULL,
  intensity    double precision,                 -- intensidade (quando disponível)
  attributes   jsonb,                            -- metadados extras
  created_at   timestamptz DEFAULT now()
);
```

**Índices**:
- `idx_lightning_events_kind` — filtro por tipo (flash/event)
- `idx_lightning_events_event_time` — busca temporal (B-tree)
- `brin_lightning_events_event_time` — busca temporal (BRIN, para partições)
- `idx_lightning_events_geom_gist` — busca espacial PostGIS
- `idx_lightning_events_rawfile` — join com raw_files

### `daily_tables` — Tabelas diárias geradas

```sql
CREATE TABLE daily_tables (
  id           bigserial PRIMARY KEY,
  taker_id     integer NOT NULL,
  taker_name   text,
  date         date NOT NULL,
  generated_at timestamptz DEFAULT now(),
  csv_blob     bytea,          -- CSV completo em bytes
  csv_text     text,           -- CSV como texto
  metadata     jsonb,          -- { hourLabels, radiiLabels, values4x24 }
  filesize     bigint,
  UNIQUE (taker_id, date)
);
```

### `table_catalog` — Catálogo rápido de tabelas

```sql
CREATE TABLE table_catalog (
  id              bigserial PRIMARY KEY,
  daily_table_id  bigint REFERENCES daily_tables(id) ON DELETE CASCADE,
  taker_id        integer NOT NULL,
  date            date NOT NULL,
  preview_json    jsonb,       -- preview para listagem
  created_at      timestamptz DEFAULT now()
);
```

---

## 📋 Schema SQLite — Tomadores de Serviço

```sql
-- Arquivo: webapp/backend/db/service_takers.sqlite
CREATE TABLE tomadores_servico (
  id              integer PRIMARY KEY,
  nome_plataforma text NOT NULL,
  latitude        real NOT NULL,
  longitude       real NOT NULL
);
CREATE UNIQUE INDEX ux_tomadores_servico_nome ON tomadores_servico(nome_plataforma);
```

**Fonte de dados**: CSV `config/service_takers.csv` (separador `;`).
**Script de criação**: `python scripts/create_service_takers_db.py`

---

## 🔄 Fluxo de Ingestão

```
1. sync_recent_glm_to_postgres.py (a cada 5min)
   │
   ├── GLMDownloader.download_range()
   │   └── Baixa .nc do S3 para data/raw/glm_20s_goes/
   │
   ├── Para cada arquivo .nc:
   │   ├── Verifica duplicata (source_url + source_time)
   │   ├── extract_points_from_lcfa(kind='flash')
   │   ├── extract_points_from_lcfa(kind='event')
   │   ├── db.store_raw_file() → INSERT INTO raw_files
   │   └── db.insert_events()  → INSERT INTO lightning_events
   │
   └── db.delete_raw_files_older_than(retention_cutoff)
       └── DELETE FROM raw_files WHERE source_time < cutoff
```

---

## 📊 Queries Principais

### Eventos por tomador (com filtro espacial)
```sql
SELECT id, kind, event_time, latitude, longitude, intensity
FROM lightning_events
WHERE event_time >= @startUtc AND event_time <= @endUtc
  AND kind = @kind
  AND latitude BETWEEN @minLat AND @maxLat
  AND longitude BETWEEN @minLon AND @maxLon
ORDER BY event_time DESC
LIMIT @limit
```
→ Seguido de filtro Haversine em C# para precisão circular.

### Eventos América do Sul (sem filtro de tomador)
```sql
-- Bounding box fixo: lat [-60, 15], lon [-90, -30]
SELECT ... FROM lightning_events
WHERE event_time BETWEEN @start AND @end
  AND latitude BETWEEN -60 AND 15
  AND longitude BETWEEN -90 AND -30
```

---

## 🛠️ Setup Inicial

### 1. Criar banco PostgreSQL
```bash
createdb lightning
psql -d lightning -f webapp/backend/db/init_schema_postgres.sql
```

### 2. Configurar DSN
```bash
# PowerShell
$env:LIGHTNING_TRACKER_PG_DSN = "host=127.0.0.1 port=5432 dbname=lightning user=postgres password=..."
```

### 3. Criar SQLite de tomadores
```bash
python scripts/create_service_takers_db.py \
  --csv-path config/service_takers.csv \
  --db-path webapp/backend/db/service_takers.sqlite
```

### 4. Backfill histórico (opcional)
```bash
python scripts/backfill_glm_to_postgres.py \
  --dsn "host=127.0.0.1 port=5432 dbname=lightning user=postgres password=..." \
  --data-path data/raw/glm_20s_goes \
  --limit 1000
```

---

## ⚠️ Notas de Produção

1. **Particionamento**: Para datasets grandes, particionar `lightning_events` por `RANGE(event_time)`.
2. **Blob storage**: Em produção, considerar object storage (S3) para blobs NetCDF ao invés de `compressed_blob` no Postgres.
3. **Retenção**: O sync purga blobs de `raw_files` após `retention_hours` (default: 3h). Eventos em `lightning_events` são mantidos indefinidamente.
4. **Projeção de crescimento**: ~2880 arquivos/dia × ~200 eventos/arquivo = ~576K eventos/dia.
5. **Dual-driver**: Python usa `pg8000`, C# usa `Npgsql`. Ambos suportam o mesmo formato de DSN.
