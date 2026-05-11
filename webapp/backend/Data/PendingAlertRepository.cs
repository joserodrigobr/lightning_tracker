using LightningTracker.WebApi.Models;
using Microsoft.Data.Sqlite;
using System.Text.Json;

namespace LightningTracker.WebApi.Data;

public sealed class PendingAlertRepository
{
    private readonly string _sqlitePath;

    public PendingAlertRepository(Services.ConfigurationService config, IHostEnvironment env)
    {
        var dbDir = Path.Combine(env.ContentRootPath, "db");
        if (!Directory.Exists(dbDir)) Directory.CreateDirectory(dbDir);
        _sqlitePath = Path.Combine(dbDir, "alerts.sqlite");
        InitializeDatabase();
    }

    private void InitializeDatabase()
    {
        using var conn = new SqliteConnection($"Data Source={_sqlitePath}");
        conn.Open();
        
        // Initial table creation
        using (var cmd = conn.CreateCommand())
        {
            cmd.CommandText = @"
                CREATE TABLE IF NOT EXISTS pending_alerts (
                    id TEXT PRIMARY KEY,
                    taker_id INTEGER,
                    taker_name TEXT,
                    alert_level TEXT,
                    payload_json TEXT,
                    status TEXT,
                    created_at TEXT
                )";
            cmd.ExecuteNonQuery();
        }

        // Migrations (Add columns if missing)
        string[] migrations = {
            "ALTER TABLE pending_alerts ADD COLUMN duration_minutes INTEGER DEFAULT 60",
            "ALTER TABLE pending_alerts ADD COLUMN updated_at TEXT",
            "ALTER TABLE pending_alerts ADD COLUMN sent_at TEXT"
        };

        foreach (var sql in migrations)
        {
            try
            {
                using var cmd = conn.CreateCommand();
                cmd.CommandText = sql;
                cmd.ExecuteNonQuery();
            }
            catch (SqliteException ex) when (ex.SqliteErrorCode == 1) // 1 = Table already has column
            {
                // Ignore "duplicate column" errors
            }
        }
    }

    public async Task AddAsync(PendingAlert alert, CancellationToken ct)
    {
        await using var conn = new SqliteConnection($"Data Source={_sqlitePath}");
        await conn.OpenAsync(ct);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = @"
            INSERT INTO pending_alerts (id, taker_id, taker_name, alert_level, payload_json, status, duration_minutes, created_at)
            VALUES ($id, $tid, $tname, $level, $payload, $status, $dur, $created)";
        
        cmd.Parameters.AddWithValue("$id", alert.Id.ToString());
        cmd.Parameters.AddWithValue("$tid", alert.TakerId);
        cmd.Parameters.AddWithValue("$tname", alert.TakerName);
        cmd.Parameters.AddWithValue("$level", alert.AlertLevel);
        cmd.Parameters.AddWithValue("$payload", alert.MessagePayloadJson);
        cmd.Parameters.AddWithValue("$status", alert.Status);
        cmd.Parameters.AddWithValue("$dur", alert.DurationMinutes);
        cmd.Parameters.AddWithValue("$created", alert.CreatedAt.ToString("o"));

        await cmd.ExecuteNonQueryAsync(ct);
    }

    public async Task<List<PendingAlert>> GetPendingAsync(CancellationToken ct)
    {
        return await GetByStatusAsync("Pending", ct);
    }

    public async Task<List<PendingAlert>> GetActiveAsync(CancellationToken ct)
    {
        return await GetByStatusAsync("Active", ct);
    }

    private async Task<List<PendingAlert>> GetByStatusAsync(string status, CancellationToken ct)
    {
        var results = new List<PendingAlert>();
        await using var conn = new SqliteConnection($"Data Source={_sqlitePath}");
        await conn.OpenAsync(ct);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT id, taker_id, taker_name, alert_level, payload_json, status, duration_minutes, created_at, sent_at FROM pending_alerts WHERE status = $status ORDER BY created_at DESC";
        cmd.Parameters.AddWithValue("$status", status);

        await using var reader = await cmd.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct))
        {
            results.Add(new PendingAlert {
                Id = Guid.Parse(reader.GetString(0)),
                TakerId = reader.GetInt32(1),
                TakerName = reader.GetString(2),
                AlertLevel = reader.GetString(3),
                MessagePayloadJson = reader.GetString(4),
                Status = reader.GetString(5),
                DurationMinutes = reader.GetInt32(6),
                CreatedAt = DateTime.Parse(reader.GetString(7)),
                SentAt = reader.IsDBNull(8) ? null : DateTime.Parse(reader.GetString(8))
            });
        }
        return results;
    }

    public async Task UpdateStatusAsync(Guid id, string status, CancellationToken ct)
    {
        await using var conn = new SqliteConnection($"Data Source={_sqlitePath}");
        await conn.OpenAsync(ct);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = "UPDATE pending_alerts SET status = $status, updated_at = $updated WHERE id = $id";
        cmd.Parameters.AddWithValue("$status", status);
        cmd.Parameters.AddWithValue("$updated", DateTime.UtcNow.ToString("o"));
        cmd.Parameters.AddWithValue("$id", id.ToString());
        await cmd.ExecuteNonQueryAsync(ct);
    }

    public async Task UpdateAlertAsync(PendingAlert alert, CancellationToken ct)
    {
        await using var conn = new SqliteConnection($"Data Source={_sqlitePath}");
        await conn.OpenAsync(ct);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = @"
            UPDATE pending_alerts 
            SET status = $status, 
                alert_level = $level, 
                duration_minutes = $dur, 
                payload_json = $payload,
                updated_at = $updated, 
                sent_at = $sent
            WHERE id = $id";
        
        cmd.Parameters.AddWithValue("$status", alert.Status);
        cmd.Parameters.AddWithValue("$level", alert.AlertLevel);
        cmd.Parameters.AddWithValue("$dur", alert.DurationMinutes);
        cmd.Parameters.AddWithValue("$payload", alert.MessagePayloadJson);
        cmd.Parameters.AddWithValue("$updated", DateTime.UtcNow.ToString("o"));
        cmd.Parameters.AddWithValue("$sent", alert.SentAt?.ToString("o") ?? (object)DBNull.Value);
        cmd.Parameters.AddWithValue("$id", alert.Id.ToString());
        
        await cmd.ExecuteNonQueryAsync(ct);
    }

    public async Task<PendingAlert?> GetByIdAsync(Guid id, CancellationToken ct)
    {
        await using var conn = new SqliteConnection($"Data Source={_sqlitePath}");
        await conn.OpenAsync(ct);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT id, taker_id, taker_name, alert_level, payload_json, status, duration_minutes, created_at, sent_at FROM pending_alerts WHERE id = $id";
        cmd.Parameters.AddWithValue("$id", id.ToString());

        await using var reader = await cmd.ExecuteReaderAsync(ct);
        if (await reader.ReadAsync(ct))
        {
            return new PendingAlert {
                Id = Guid.Parse(reader.GetString(0)),
                TakerId = reader.GetInt32(1),
                TakerName = reader.GetString(2),
                AlertLevel = reader.GetString(3),
                MessagePayloadJson = reader.GetString(4),
                Status = reader.GetString(5),
                DurationMinutes = reader.GetInt32(6),
                CreatedAt = DateTime.Parse(reader.GetString(7)),
                SentAt = reader.IsDBNull(8) ? null : DateTime.Parse(reader.GetString(8))
            };
        }
        return null;
    }

    public async Task<bool> HasActiveAsync(int takerId, CancellationToken ct)
    {
        await using var conn = new SqliteConnection($"Data Source={_sqlitePath}");
        await conn.OpenAsync(ct);
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT COUNT(*) FROM pending_alerts WHERE taker_id = $tid AND status = 'Active'";
        cmd.Parameters.AddWithValue("$tid", takerId);
        
        var count = (long)(await cmd.ExecuteScalarAsync(ct) ?? 0L);
        return count > 0;
    }

    public async Task<bool> HasRecentPendingAsync(int takerId, string level, CancellationToken ct)
    {
        await using var conn = new SqliteConnection($"Data Source={_sqlitePath}");
        await conn.OpenAsync(ct);
        await using var cmd = conn.CreateCommand();
        // Check if there is an active or pending alert for this taker
        cmd.CommandText = "SELECT COUNT(*) FROM pending_alerts WHERE taker_id = $tid AND (status = 'Pending' OR status = 'Active') AND created_at > $time";
        cmd.Parameters.AddWithValue("$tid", takerId);
        cmd.Parameters.AddWithValue("$time", DateTime.UtcNow.AddMinutes(-20).ToString("o"));
        
        var count = (long)(await cmd.ExecuteScalarAsync(ct) ?? 0L);
        return count > 0;
    }
}
