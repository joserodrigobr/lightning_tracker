using System.Globalization;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using LightningTracker.WebApi.Models;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Caching.Memory;

namespace LightningTracker.WebApi.Data;

public sealed class ServiceTakerRepository
{
    private const string ForecastUnitsCacheKey = "forecast-units-service-takers";

    private readonly Services.ConfigurationService _config;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IMemoryCache _cache;
    private readonly ILogger<ServiceTakerRepository> _logger;
    private readonly string _sqlitePath;
    private readonly string _fallbackCsvPath;

    public ServiceTakerRepository(
        Services.ConfigurationService config,
        IHostEnvironment env,
        IHttpClientFactory httpClientFactory,
        IMemoryCache cache,
        ILogger<ServiceTakerRepository> logger)
    {
        _config = config;
        _httpClientFactory = httpClientFactory;
        _cache = cache;
        _logger = logger;

        var sqlitePath = config.GetServiceTakersDbPath();
        _sqlitePath = Path.IsPathRooted(sqlitePath)
            ? sqlitePath
            : Path.GetFullPath(Path.Combine(env.ContentRootPath, sqlitePath));
        _fallbackCsvPath = Path.GetFullPath(Path.Combine(env.ContentRootPath, "..", "..", "config", "service_takers.csv"));
    }

    public async Task<List<ServiceTaker>> GetAllAsync(CancellationToken cancellationToken)
    {
        var forecastUnits = await TryLoadFromForecastApiAsync(cancellationToken);
        if (forecastUnits is { Count: > 0 })
            return forecastUnits;

        try
        {
            return await LoadFromDatabaseAsync(cancellationToken);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Falha ao carregar tomadores do SQLite. Usando CSV local.");
            return LoadFromCsv();
        }
    }

    public async Task<ServiceTaker?> GetByIdAsync(int id, CancellationToken cancellationToken)
    {
        if (id == 0)
        {
            return new ServiceTaker(0, "América do Sul", -14.0, -52.0);
        }

        var takers = await GetAllAsync(cancellationToken);
        return takers.FirstOrDefault(t => t.Id == id);
    }

    private async Task<List<ServiceTaker>?> TryLoadFromForecastApiAsync(CancellationToken cancellationToken)
    {
        var apiUrl = _config.GetForecastUnitsApiUrl();
        var apiKey = _config.GetForecastUnitsApiKey();
        if (string.IsNullOrWhiteSpace(apiUrl) || string.IsNullOrWhiteSpace(apiKey))
            return null;

        if (_cache.TryGetValue(ForecastUnitsCacheKey, out List<ServiceTaker>? cached) && cached is { Count: > 0 })
            return cached;

        try
        {
            using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeoutCts.CancelAfter(TimeSpan.FromSeconds(10));

            using var request = new HttpRequestMessage(HttpMethod.Get, apiUrl);
            request.Headers.TryAddWithoutValidation("X-Integration-Key", apiKey);

            var client = _httpClientFactory.CreateClient();
            using var response = await client.SendAsync(request, timeoutCts.Token);
            response.EnsureSuccessStatusCode();

            var externalUnits = await response.Content.ReadFromJsonAsync<List<ForecastUnitDto>>(
                new JsonSerializerOptions(JsonSerializerDefaults.Web),
                timeoutCts.Token);

            if (externalUnits is null || externalUnits.Count == 0)
            {
                _logger.LogWarning("API de previsao nao retornou unidades.");
                return null;
            }

            var localTakers = await LoadLocalTakersAsync(cancellationToken);
            var mergedTakers = MergeForecastUnits(externalUnits, localTakers);
            if (mergedTakers.Count == 0)
                return null;

            await SaveToDatabaseAsync(mergedTakers, cancellationToken);

            _cache.Set(ForecastUnitsCacheKey, mergedTakers, TimeSpan.FromMinutes(1));
            return mergedTakers;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Falha ao consumir unidades da API de previsao. Usando cadastro local.");
            return null;
        }
    }

    private async Task<List<ServiceTaker>> LoadLocalTakersAsync(CancellationToken cancellationToken)
    {
        try
        {
            return await LoadFromDatabaseAsync(cancellationToken);
        }
        catch
        {
            return LoadFromCsv();
        }
    }

    private async Task<List<ServiceTaker>> LoadFromDatabaseAsync(CancellationToken cancellationToken)
    {
        if (!File.Exists(_sqlitePath))
            return LoadFromCsv();

        var results = new List<ServiceTaker>();
        await using var conn = new SqliteConnection($"Data Source={_sqlitePath}");
        await conn.OpenAsync(cancellationToken);

        const string sql = "select id, nome_plataforma, latitude, longitude from tomadores_servico order by nome_plataforma";
        await using var cmd = conn.CreateCommand();
        cmd.CommandText = sql;

        await using var reader = await cmd.ExecuteReaderAsync(cancellationToken);
        while (await reader.ReadAsync(cancellationToken))
        {
            results.Add(new ServiceTaker(
                reader.GetInt32(0),
                reader.GetString(1),
                reader.GetDouble(2),
                reader.GetDouble(3)
            ));
        }

        return results;
    }

    private List<ServiceTaker> LoadFromCsv()
    {
        if (!File.Exists(_fallbackCsvPath))
            return [];

        var takers = new List<ServiceTaker>();
        var lines = File.ReadAllLines(_fallbackCsvPath, Encoding.UTF8);
        foreach (var rawLine in lines.Skip(1))
        {
            var line = rawLine.Trim();
            if (string.IsNullOrWhiteSpace(line))
                continue;

            var parts = line.Split(';');
            if (parts.Length < 5)
                continue;

            if (!int.TryParse(parts[0].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var id))
                continue;

            if (!double.TryParse(parts[3].Trim().Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out var lat))
                continue;

            if (!double.TryParse(parts[4].Trim().Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out var lon))
                continue;

            var municipality = parts[1].Trim();
            var unit = parts[2].Trim();
            var name = string.IsNullOrWhiteSpace(unit) ? municipality : unit;

            takers.Add(new ServiceTaker(id, name, lat, lon));
        }

        return takers.OrderBy(t => t.Name, StringComparer.CurrentCultureIgnoreCase).ToList();
    }

    private List<ServiceTaker> MergeForecastUnits(
        IReadOnlyList<ForecastUnitDto> forecastUnits,
        IReadOnlyList<ServiceTaker> localTakers)
    {
        var localByName = new Dictionary<string, ServiceTaker>(StringComparer.Ordinal);
        var usedIds = new HashSet<int>();

        foreach (var taker in localTakers)
        {
            usedIds.Add(taker.Id);
            var key = NormalizeName(taker.Name);
            if (!string.IsNullOrWhiteSpace(key) && !localByName.ContainsKey(key))
                localByName[key] = taker;
        }

        var merged = new List<ServiceTaker>();
        foreach (var unit in forecastUnits)
        {
            if (!unit.IsActive || string.IsNullOrWhiteSpace(unit.Name))
                continue;

            if (!IsValidCoordinate(unit.Latitude, unit.Longitude))
                continue;

            var key = NormalizeName(unit.Name);
            var id = localByName.TryGetValue(key, out var local)
                ? local.Id
                : CreateStableId(unit.Id, usedIds);

            usedIds.Add(id);
            merged.Add(new ServiceTaker(id, unit.Name.Trim(), unit.Latitude, unit.Longitude));
        }

        return merged
            .OrderBy(t => t.Name, StringComparer.CurrentCultureIgnoreCase)
            .ToList();
    }

    private async Task SaveToDatabaseAsync(IReadOnlyList<ServiceTaker> takers, CancellationToken cancellationToken)
    {
        try
        {
            var directory = Path.GetDirectoryName(_sqlitePath);
            if (!string.IsNullOrWhiteSpace(directory))
                Directory.CreateDirectory(directory);

            await using var conn = new SqliteConnection($"Data Source={_sqlitePath}");
            await conn.OpenAsync(cancellationToken);

            await using (var schemaCmd = conn.CreateCommand())
            {
                schemaCmd.CommandText = """
                    create table if not exists tomadores_servico (
                        id integer primary key,
                        nome_plataforma text not null,
                        latitude real not null,
                        longitude real not null
                    );
                    create unique index if not exists ux_tomadores_servico_nome on tomadores_servico(nome_plataforma);
                    """;
                await schemaCmd.ExecuteNonQueryAsync(cancellationToken);
            }

            await using var tx = conn.BeginTransaction();

            await using (var deleteCmd = conn.CreateCommand())
            {
                deleteCmd.Transaction = tx;
                deleteCmd.CommandText = "delete from tomadores_servico";
                await deleteCmd.ExecuteNonQueryAsync(cancellationToken);
            }

            foreach (var taker in takers)
            {
                await using var insertCmd = conn.CreateCommand();
                insertCmd.Transaction = tx;
                insertCmd.CommandText = """
                    insert into tomadores_servico (id, nome_plataforma, latitude, longitude)
                    values ($id, $name, $lat, $lon)
                    """;
                insertCmd.Parameters.AddWithValue("$id", taker.Id);
                insertCmd.Parameters.AddWithValue("$name", taker.Name);
                insertCmd.Parameters.AddWithValue("$lat", taker.Lat);
                insertCmd.Parameters.AddWithValue("$lon", taker.Lon);
                await insertCmd.ExecuteNonQueryAsync(cancellationToken);
            }

            await tx.CommitAsync(cancellationToken);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Unidades da API de previsao foram carregadas, mas nao foi possivel sincronizar o SQLite local.");
        }
    }

    private static bool IsValidCoordinate(double latitude, double longitude)
    {
        return latitude is >= -90 and <= 90
            && longitude is >= -180 and <= 180
            && !double.IsNaN(latitude)
            && !double.IsNaN(longitude);
    }

    private static int CreateStableId(string externalId, HashSet<int> usedIds)
    {
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(externalId));
        var id = BitConverter.ToInt32(hash, 0) & int.MaxValue;
        if (id == 0)
            id = 1;

        while (usedIds.Contains(id))
            id = id == int.MaxValue ? 1 : id + 1;

        return id;
    }

    private static string NormalizeName(string value)
    {
        var normalized = value.Trim().Normalize(NormalizationForm.FormD);
        var builder = new StringBuilder(normalized.Length);
        var previousWasWhiteSpace = false;

        foreach (var c in normalized)
        {
            var category = CharUnicodeInfo.GetUnicodeCategory(c);
            if (category == UnicodeCategory.NonSpacingMark)
                continue;

            if (char.IsWhiteSpace(c))
            {
                if (!previousWasWhiteSpace)
                    builder.Append(' ');

                previousWasWhiteSpace = true;
                continue;
            }

            builder.Append(char.ToUpperInvariant(c));
            previousWasWhiteSpace = false;
        }

        return builder.ToString().Normalize(NormalizationForm.FormC).Trim();
    }

    private sealed record ForecastUnitDto(
        string Id,
        string Name,
        double Latitude,
        double Longitude,
        bool IsActive);
}
