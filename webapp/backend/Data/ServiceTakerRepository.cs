using LightningTracker.WebApi.Models;
using Microsoft.Data.Sqlite;
using System.Globalization;
using System.Text;

namespace LightningTracker.WebApi.Data;

public sealed class ServiceTakerRepository
{
    private readonly string _sqlitePath;
    private readonly string _fallbackCsvPath;

    public ServiceTakerRepository(Services.ConfigurationService config, IHostEnvironment env)
    {
        var sqlitePath = config.GetServiceTakersDbPath();
        _sqlitePath = Path.IsPathRooted(sqlitePath)
            ? sqlitePath
            : Path.GetFullPath(Path.Combine(env.ContentRootPath, sqlitePath));
        _fallbackCsvPath = Path.GetFullPath(Path.Combine(env.ContentRootPath, "..", "..", "config", "service_takers.csv"));
    }

    public async Task<List<ServiceTaker>> GetAllAsync(CancellationToken cancellationToken)
    {
        try
        {
            return await LoadFromDatabaseAsync(cancellationToken);
        }

        catch (Exception)
        {
            return LoadFromCsv();
        }
    }

    public async Task<ServiceTaker?> GetByIdAsync(int id, CancellationToken cancellationToken)
    {
        try
        {
            return await LoadByIdFromDatabaseAsync(id, cancellationToken);
        }
        catch (Exception)
        {
            return LoadFromCsv().FirstOrDefault(t => t.Id == id);
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

    private async Task<ServiceTaker?> LoadByIdFromDatabaseAsync(int id, CancellationToken cancellationToken)
    {
        if (!File.Exists(_sqlitePath))
            return LoadFromCsv().FirstOrDefault(t => t.Id == id);

        await using var conn = new SqliteConnection($"Data Source={_sqlitePath}");
        await conn.OpenAsync(cancellationToken);

        const string sql = "select id, nome_plataforma, latitude, longitude from tomadores_servico where id = $id";

        await using var cmd = conn.CreateCommand();
        cmd.CommandText = sql;
        cmd.Parameters.AddWithValue("$id", id);

        await using var reader = await cmd.ExecuteReaderAsync(cancellationToken);
        if (!await reader.ReadAsync(cancellationToken))
            return null;

        return new ServiceTaker(
            reader.GetInt32(0),
            reader.GetString(1),
            reader.GetDouble(2),
            reader.GetDouble(3)
        );
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
}
