using System.Data;
using LightningTracker.WebApi.Models;
using Npgsql;

namespace LightningTracker.WebApi.Services;

public class LightningDataService
{
    private readonly ConfigurationService _config;
    private readonly ILogger<LightningDataService> _logger;

    public LightningDataService(ConfigurationService config, ILogger<LightningDataService> logger)
    {
        _config = config;
        _logger = logger;
    }

    private static double HaversineKm(double lat1, double lon1, double lat2, double lon2)
    {
        var dLat = (lat2 - lat1) * Math.PI / 180.0;
        var dLon = (lon2 - lon1) * Math.PI / 180.0;
        var a = Math.Sin(dLat / 2) * Math.Sin(dLat / 2) +
                Math.Cos(lat1 * Math.PI / 180.0) * Math.Cos(lat2 * Math.PI / 180.0) *
                Math.Sin(dLon / 2) * Math.Sin(dLon / 2);
        var c = 2 * Math.Atan2(Math.Sqrt(a), Math.Sqrt(1 - a));
        return 6371.0 * c;
    }

    public async Task<List<LightningEvent>> GetEventsAsync(
        ServiceTaker taker,
        DateTime startUtc,
        DateTime endUtc,
        double maxRadiusKm,
        string kind, // "flash" or "event"
        int maxPoints = 1000000,
        CancellationToken ct = default)
    {
        var dsn = _config.GetPostgresDsn();
        if (string.IsNullOrWhiteSpace(dsn))
        {
            _logger.LogWarning("LIGHTNING_TRACKER_PG_DSN is not configured. Falling back to empty event list.");
            return new List<LightningEvent>();
        }

        // Convert libpq DSN (host=... port=...) to Npgsql connection string
        var parts = dsn.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var npgsqlDsn = string.Join(";", parts.Select(p => 
        {
            var pair = p.Split('=', 2);
            if (pair.Length != 2) return p;
            var key = pair[0].ToLowerInvariant();
            var val = pair[1];
            if (key == "dbname") key = "Database";
            else if (key == "user") key = "Username";
            return $"{key}={val}";
        })) + ";Timeout=30;CommandTimeout=30;";

        _logger.LogInformation("Buscando eventos para taker {TakerName} (ID {TakerId}) entre {Start} e {End}...", taker.Name, taker.Id, startUtc.ToString("HH:mm:ss"), endUtc.ToString("HH:mm:ss"));

        // Bounding box for rough filtering in SQL
        double dLat = maxRadiusKm / 111.0;
        double dLon = maxRadiusKm / (111.0 * Math.Max(0.2, Math.Cos(taker.Lat * Math.PI / 180.0)));
        double minLat = taker.Lat - dLat;
        double maxLat = taker.Lat + dLat;
        double minLon = taker.Lon - dLon;
        double maxLon = taker.Lon + dLon;

        var events = new List<LightningEvent>();

        try
        {
            await using var conn = new NpgsqlConnection(npgsqlDsn);
            await conn.OpenAsync(ct);

            // Filter roughly by bounding box and precisely by Haversine in C#
            var sql = @"
                SELECT id, kind, event_time, latitude, longitude, intensity
                FROM lightning_events
                WHERE event_time >= @startUtc AND event_time <= @endUtc
                  AND kind = @kind
                  AND latitude BETWEEN @minLat AND @maxLat
                  AND longitude BETWEEN @minLon AND @maxLon
                ORDER BY event_time DESC
                LIMIT @limit
            ";

            await using var cmd = new NpgsqlCommand(sql, conn);
            cmd.Parameters.AddWithValue("startUtc", startUtc);
            cmd.Parameters.AddWithValue("endUtc", endUtc);
            cmd.Parameters.AddWithValue("kind", kind);
            cmd.Parameters.AddWithValue("minLat", minLat);
            cmd.Parameters.AddWithValue("maxLat", maxLat);
            cmd.Parameters.AddWithValue("minLon", minLon);
            cmd.Parameters.AddWithValue("maxLon", maxLon);
            cmd.Parameters.AddWithValue("limit", maxPoints * 2); // Fetch extra to account for circular haversine filtering

            await using var reader = await cmd.ExecuteReaderAsync(ct);
            while (await reader.ReadAsync(ct))
            {
                var lat = reader.GetDouble(3);
                var lon = reader.GetDouble(4);
                
                // Precise distance check
                var dist = HaversineKm(taker.Lat, taker.Lon, lat, lon);
                if (dist <= maxRadiusKm)
                {
                    events.Add(new LightningEvent(
                        reader.GetInt64(0),
                        reader.GetString(1),
                        reader.GetDateTime(2),
                        lat,
                        lon,
                        reader.IsDBNull(5) ? null : reader.GetDouble(5)
                    ));

                    if (events.Count >= maxPoints)
                        break;
                }
            }
            
            _logger.LogInformation("Busca concluída: {Count} eventos encontrados para o taker {TakerId}.", events.Count, taker.Id);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Falha ao buscar eventos no PostgreSQL para o taker {TakerId}.", taker.Id);
        }

        // Return sorted ascending by time
        events.Reverse();
        return events;
    }

    /// <summary>
    /// Fetch all events within the South America bounding box, without taker-based spatial filtering.
    /// </summary>
    public async Task<List<LightningEvent>> GetAllEventsAsync(
        DateTime startUtc,
        DateTime endUtc,
        string kind,
        int maxPoints = 1000000,
        CancellationToken ct = default)
    {
        var dsn = _config.GetPostgresDsn();
        if (string.IsNullOrWhiteSpace(dsn))
        {
            _logger.LogWarning("LIGHTNING_TRACKER_PG_DSN is not configured.");
            return new List<LightningEvent>();
        }

        var parts = dsn.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var npgsqlDsn = string.Join(";", parts.Select(p =>
        {
            var pair = p.Split('=', 2);
            if (pair.Length != 2) return p;
            var key = pair[0].ToLowerInvariant();
            var val = pair[1];
            if (key == "dbname") key = "Database";
            else if (key == "user") key = "Username";
            return $"{key}={val}";
        })) + ";";

        // South America bounding box
        double minLat = -60.0, maxLat = 15.0;
        double minLon = -90.0, maxLon = -30.0;

        var events = new List<LightningEvent>();

        try
        {
            await using var conn = new NpgsqlConnection(npgsqlDsn);
            await conn.OpenAsync(ct);

            var sql = @"
                SELECT id, kind, event_time, latitude, longitude, intensity
                FROM lightning_events
                WHERE event_time >= @startUtc AND event_time <= @endUtc
                  AND kind = @kind
                  AND latitude BETWEEN @minLat AND @maxLat
                  AND longitude BETWEEN @minLon AND @maxLon
                ORDER BY event_time DESC
                LIMIT @limit
            ";

            await using var cmd = new NpgsqlCommand(sql, conn);
            cmd.Parameters.AddWithValue("startUtc", startUtc);
            cmd.Parameters.AddWithValue("endUtc", endUtc);
            cmd.Parameters.AddWithValue("kind", kind);
            cmd.Parameters.AddWithValue("minLat", minLat);
            cmd.Parameters.AddWithValue("maxLat", maxLat);
            cmd.Parameters.AddWithValue("minLon", minLon);
            cmd.Parameters.AddWithValue("maxLon", maxLon);
            cmd.Parameters.AddWithValue("limit", maxPoints);

            await using var reader = await cmd.ExecuteReaderAsync(ct);
            while (await reader.ReadAsync(ct))
            {
                events.Add(new LightningEvent(
                    reader.GetInt64(0),
                    reader.GetString(1),
                    reader.GetDateTime(2),
                    reader.GetDouble(3),
                    reader.GetDouble(4),
                    reader.IsDBNull(5) ? null : reader.GetDouble(5)
                ));

                if (events.Count >= maxPoints)
                    break;
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to fetch all events from PostgreSQL");
        }

        events.Reverse();
        return events;
    }
}
