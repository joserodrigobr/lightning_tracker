# 🗑️ Lixeira — Arquivos Removidos do Projeto Ativo

> Arquivos movidos para cá durante a auditoria de código em 2026-05-11.
> **Nenhum arquivo ativo do sistema depende destes módulos.**
> Podem ser deletados permanentemente após revisão.

---

## Arquivos Movidos

| Arquivo | Origem | Motivo |
|---------|--------|--------|
| `db_sqlite.py` | `src/db_sqlite.py` | Módulo de banco SQLite para eventos. **Nenhum import encontrado** em todo o projeto. O sistema migrou 100% para PostgreSQL via `src/db.py`. |
| `ingest_nc_to_sqlite.py` | `scripts/ingest_nc_to_sqlite.py` | Script de ingestão de .nc → SQLite. Dependia de `db_sqlite.py` (também removido). Substituído por `sync_recent_glm_to_postgres.py`. |
| `ingest_nc_to_db.py` | `scripts/ingest_nc_to_db.py` | Script de ingestão unitária de .nc → PostgreSQL. **Nenhuma referência** em código ou configuração. Substituído por `backfill_glm_to_postgres.py` e `sync_recent_glm_to_postgres.py`. |
| `createtables.sql` | `webapp/createtables.sql` | SQL com apenas tabela `service_takers`. **Duplicata** de `webapp/backend/db/schema.sql` que foi mantida como `init_schema_postgres.sql`. Sem referências. |
| `schema.sql` | `webapp/backend/db/schema.sql` | Schema simplificado com apenas `service_takers`. **Duplicata parcial** de `init_schema_postgres.sql` (que é o schema completo). Sem referências em código. |
| `scratch/` | `webapp/backend/scratch/` | Pasta de scripts temporários de debug (`list_takers.py`). Contém hardcoded paths e não faz parte do fluxo operacional. |

---

## Módulos Ativos Que NÃO Foram Movidos

Os seguintes módulos foram analisados e confirmados como **em uso ativo**:

- `src/notifier.py` — Usado por `core.py` (`from .notifier import beep`)
- `src/archiver.py` — Usado por `core.py` e `web_tables.py` (`from .archiver import HourlyArchiver`)
- `src/geo.py` — Usado por `core.py`, `visualizer.py`, `web_render.py`, `web_auto_select.py`
- `src/timeutils.py` — Usado por `core.py` e `ui.py`
- `src/ui.py` — Usado por `main.py` (`from src.ui import ask_selection`)
- `scripts/validate_production.py` — Script de teste operacional (mantido como ferramenta)
- `scripts/backfill_glm_to_postgres.py` — Script de backfill histórico (mantido como ferramenta)
