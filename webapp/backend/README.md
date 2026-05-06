# Lightning Tracker Backend API

## Overview

The backend is an ASP.NET Core 8 REST API (`LightningTracker.WebApi`) that serves as the bridge between the React frontend and Python data processing services.

**Key Responsibilities:**
- HTTP API endpoints for rendering lightning visualizations
- Service taker (tomador de serviço) management
- Integration with PostgreSQL for data storage and retrieval
- Orchestration of Python subprocesses for render operations
- Table generation and data aggregation

## Endpoints

### Taker Management
- `GET /api/takers` - List all service takers (tomadores de serviço)
- `GET /api/takers/active` - Get the current default/active taker

### Rendering
- `GET /api/render` - Render full visualization (lightning points + optional background)
  - Query params: `takerId`, `mode` (1-5), `startLocal`, `endLocal`, `initialLoadHours`, `background` (0/1)
  - Returns: PNG image with metadata headers

- `GET /api/render/frame` - Render frame/snapshot (faster, no cache)
  - Query params: Same as `/api/render` + `thumb` (0/1 for thumbnail mode)
  - Returns: PNG image (thumbnail variant if requested)

### Tables
- `GET /api/tables/generate` - Generate aggregated data tables
  - Query params: `takerId`, `endLocal`
  - Returns: JSON table data

## Architecture

### Two Workflows: Legacy vs Modern

#### Legacy Workflow (Deprecated)
- **Entry Point:** `core.py` CLI
- **Flow:** Local file → matplotlib visualization → GUI display
- **Storage:** Minimal PostgreSQL usage; mostly in-memory
- **Use Case:** Development, single-user analysis
- **Status:** ⚠️ Not recommended for production

#### Modern Workflow (Recommended)
- **Entry Point:** Web API (`Program.cs` / `LightningTrackerEndpoints.cs`)
- **Flow:**
  1. `Program.cs` starts the automatic GLM sync hosted service
  2. `sync_recent_glm_to_postgres.py` downloads GLM files from AWS S3
  3. `extract_points_from_lcfa()` parses NetCDF → lat/lon/time
  4. `db.insert_events()` stores raw blob + normalized events in PostgreSQL
  5. API `/api/render` request → `PythonRenderService`
  6. Python subprocess loads points from PostgreSQL → renders with matplotlib
  7. PNG returned to frontend

- **Storage:** PostgreSQL (raw_files table stores compressed NetCDF blobs; lightning_events table stores normalized points)
- **Use Case:** Production, multi-user, web-based
- **Status:** ✅ Production-ready

### Data Lifecycle

```
[AWS S3 NOAA] 
    ↓ (boto3 download)
[data/raw/glm_20s_goes/*.nc files]
    ↓ (sync_recent_glm_to_postgres.py)
[netCDF4 parsing]
    ↓ (extract_points_from_lcfa)
[PostgreSQL: raw_files + lightning_events]
    ↓ (API /api/render)
[Python subprocess: web_render.py]
    ↓ (matplotlib render)
[PNG image] → Frontend
    ↓ (optional cleanup)
[deleted if older than cleanup_days_old]
```

### Services

#### `PythonRenderService` (`Services/PythonRenderService.cs`)
- Spawns Python subprocess running `web_render.py`
- Passes parameters: `takerId`, `mode`, `startLocal`, `endLocal`, background flag, thumbnail flag
- Loads lightning points from PostgreSQL
- Returns PNG + metadata (render time, point count, etc.)

#### `ConfigurationService` (`Services/ConfigurationService.cs`)
- Loads `appsettings.json` at startup
- Exposes configuration to other services
- Handles environment variable overrides

#### `ServiceTakerRepository` (`Data/ServiceTakerRepository.cs`)
- Database access for tomadores_de_servico table
- Caches service taker list in memory for fast lookups

#### `PythonActivityService` (`Services/PythonActivityService.cs`)
- Monitors active Python renders (process tracking)
- Allows selection of default taker based on current activity

#### `PythonTableService` (`Services/PythonTableService.cs`)
- Spawns Python for table generation
- Aggregates lightning events by geographic regions/time windows

#### `TableCatalogService` (`Services/TableCatalogService.cs`)
- Maintains index of generated tables
- Serves pre-generated table metadata

## Configuration

### `appsettings.json`
```json
{
  "Logging": {
    "LogLevel": { "Default": "Information" }
  },
  "PythonSettings": {
    "ScriptsDir": "../../src",
    "RenderScript": "web_render.py",
    "TableScript": "web_tables.py",
    "Timeout": "00:02:00"
  },
  "DatabaseSettings": {
    "ConnectionString": "Host=localhost;Port=5432;Database=lightning_tracker;..."
  }
}
```

### Environment Variables
- `LIGHTNING_TRACKER_PG_DSN` - PostgreSQL connection string (overrides appsettings)
- `LIGHTNING_TRACKER_PYTHON_TIMEOUT` - Render timeout in seconds (default: 120)
- `LIGHTNING_TRACKER_SYNC_ENABLED` - Enables or disables the automatic GLM sync hosted service
- `LIGHTNING_TRACKER_SYNC_INTERVAL_SECONDS` - Delay between sync iterations
- `LIGHTNING_TRACKER_SYNC_LOOKBACK_MINUTES` - Window refreshed by each sync iteration
- `LIGHTNING_TRACKER_SYNC_RETENTION_HOURS` - Retention window for raw blobs in PostgreSQL
- `LIGHTNING_TRACKER_SYNC_KEEP_RAW_FILES` - Keeps downloaded raw `.nc` files when set to `true`
- `ASPNETCORE_ENVIRONMENT` - Environment: Development, Staging, Production

## Dependencies

### External Services
- **PostgreSQL** - Data persistence (required)
  - Tables: `raw_files`, `lightning_events`, `tomadores_de_servico`, etc.
  - Retention: raw_files kept for 3-24 hours (configurable); events indefinite

- **Python 3.11+** - Render subprocess
  - Scripts: `web_render.py`, `web_tables.py`
  - Dependencies: `netCDF4`, `numpy`, `pandas`, `matplotlib`, `psycopg2`

### NuGet Packages
- `Npgsql` - PostgreSQL driver
- `Serilog` - Structured logging
- `Dapper` (optional) - Micro-ORM for queries

### Python Packages (called via subprocess)
See `../requirements.txt` for full list. Critical:
- `psycopg2-binary` - PostgreSQL connection
- `netCDF4` - NetCDF file parsing
- `matplotlib` - Image rendering
- `numpy`, `pandas` - Data manipulation

## Cleanup & Retention Policy

### Raw .nc Files
- **Location:** `data/raw/glm_20s_goes/`, `data/raw/abi_ir/`
- **Retention:** 3 days (configurable via `config/settings.yaml`: `cleanup_days_old`)
- **Trigger:** `sync_recent_glm_to_postgres.py` runs with `--keep-raw-files=false` (default)
- **Impact:** ✅ Safe — Data already in PostgreSQL (`raw_files.compressed_blob`)
- **Command:** `python scripts/sync_recent_glm_to_postgres.py` (automatic cleanup)

### PostgreSQL Raw File Blobs
- **Table:** `raw_files` (stores original NetCDF gzip-compressed)
- **Retention:** 24 hours (via `delete_raw_files_older_than()` in `sync_recent_glm_to_postgres.py`)
- **Purpose:** Recoverability if events need re-parsing

### PNG Cache
- **Status:** ❌ REMOVED (deprecated)
- **Reason:** Cache hit rate <10%; disk I/O overhead > benefit; renders always fresh from PostgreSQL
- **Previous Location:** `webapp/backend/cache/render_frames/` (now deleted)

### Lightning Events
- **Table:** `lightning_events`
- **Retention:** Indefinite (data scientifically valuable)
- **Growth Rate:** ~1GB/30 days (100k events/day)

## Performance Characteristics

### Typical Timings (per `/api/render` call)
| Operation | Duration |
|-----------|----------|
| PostgreSQL query (load points) | 50-150ms |
| Matplotlib render (matplotlib) | 10-30s (varies by point count) |
| Network + Python subprocess overhead | 200-500ms |
| **Total** | **~10-30 seconds** |

### Query Optimization
- `lightning_events` table indexed on `takerId`, `event_time` for fast range queries
- `raw_files` indexed on `source_url`, `source_time` for dedup checks

### Storage Projections (30-day window)
- Raw `.nc` files: ~10GB → deleted after 3 days
- PostgreSQL `raw_files`: ~3-5GB (compressed NetCDF)
- PostgreSQL `lightning_events`: ~1-2GB
- Total disk with cleanup: **~5-10GB** ✅ (vs. **121GB** without cleanup)

### Scaling Recommendations
- PostgreSQL: 2+ CPU cores, 4GB+ RAM, SSD for wal_log
- Backend API: 1-2 CPU cores, 1GB RAM; horizontal scale behind load balancer
- Python subprocesses: 1 CPU core per concurrent render (limit to 2-4)

## Troubleshooting

### API Returns 500 Error
- Check PostgreSQL connection: `LIGHTNING_TRACKER_PG_DSN` set correctly
- Check Python environment: Verify `web_render.py` runs standalone
- Review `stderr` from Python subprocess in logs

### Slow Render
- Check PostgreSQL query time with EXPLAIN PLAN
- Reduce `initialLoadHours` (limits points loaded)
- Use thumbnail mode (`thumb=1`) for faster feedback

### Raw Files Not Cleaned Up
- Verify `cleanup_enabled: true` in `config/settings.yaml`
- Check cron job for `sync_recent_glm_to_postgres.py` is running
- Use `--keep-raw-files` flag to disable cleanup during debugging

## Building & Running

### Prerequisites
```bash
# Backend
dotnet --version  # Should be 8.0+

# Python
python --version  # Should be 3.11+
pip install -r requirements.txt
```

### Build
```bash
cd webapp/backend
dotnet build
```

### Run
```bash
# Development (watch mode)
dotnet watch

# Production
dotnet publish -c Release
dotnet LightningTracker.WebApi.dll
```

### Run with Custom Settings
```bash
export LIGHTNING_TRACKER_PG_DSN="Host=prod-db;Port=5432;Database=tracker;..."
export ASPNETCORE_ENVIRONMENT=Production
dotnet LightningTracker.WebApi.dll
```

## Development Workflow

### Adding a New Endpoint
1. Create handler method in `Endpoints/LightningTrackerEndpoints.cs`
2. Use `app.MapGet()` or `app.MapPost()` to register route
3. Inject dependencies (services resolve from DI container)
4. Return `Results.Json()`, `Results.File()`, or `Results.NotFound()`
5. Test via `curl` or frontend

### Adding a Service
1. Create class in `Services/` directory
2. Register in `Program.cs`: `builder.Services.AddSingleton<MyService>()`
3. Inject in endpoints or other services via constructor

### Running Tests
```bash
cd webapp/backend
dotnet test
```

## Related Documentation

- [Parent Project README](../../README.md) - Overview of Lightning Tracker
- [Python Processing Pipeline](../../src/) - Data extraction, storage logic
- [Frontend README](../frontend/README.md) - React UI documentation
- [API Tables Documentation](../../docs/TABLES_AND_API.md) - API reference

---

**Last Updated:** 2024  
**Maintainer:** Lightning Tracker Dev Team
