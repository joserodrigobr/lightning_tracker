using System;
using Microsoft.Extensions.Configuration;

namespace LightningTracker.WebApi.Services;

/// <summary>
/// Centralized configuration service that supports environment variable overrides.
/// Priority: Environment Variable > appsettings.json > Default
/// </summary>
public class ConfigurationService
{
    private readonly IConfiguration _configuration;

    public ConfigurationService(IConfiguration configuration)
    {
        _configuration = configuration;
    }

    /// <summary>
    /// Gets PostgreSQL DSN with environment variable override support.
    /// Priority: LIGHTNING_TRACKER_PG_DSN env var > appsettings.json
    /// </summary>
    public string? GetPostgresDsn()
    {
        // First check environment variable
        var envDsn = Environment.GetEnvironmentVariable("LIGHTNING_TRACKER_PG_DSN");
        if (!string.IsNullOrEmpty(envDsn))
        {
            return envDsn;
        }

        // Fall back to appsettings.json
        return _configuration.GetValue<string>("Data:PostgresDsn");
    }

    /// <summary>
    /// Gets Python command with environment variable override support.
    /// </summary>
    public string GetPythonCommand()
    {
        var envCmd = Environment.GetEnvironmentVariable("LIGHTNING_TRACKER_PYTHON_CMD");
        return !string.IsNullOrEmpty(envCmd) 
            ? envCmd 
            : _configuration.GetValue<string>("Python:Command") ?? "python";
    }

    /// <summary>
    /// Gets Python working directory.
    /// </summary>
    public string GetPythonWorkingDirectory()
    {
        return _configuration.GetValue<string>("Python:WorkingDirectory") ?? "..\\..";
    }

    /// <summary>
    /// Gets tables root path for fallback storage.
    /// </summary>
    public string GetTablesRootPath()
    {
        return _configuration.GetValue<string>("Data:TablesRootPath") ?? "..\\..\\output\\tables";
    }

    /// <summary>
    /// Gets service takers database path.
    /// </summary>
    public string GetServiceTakersDbPath()
    {
        return _configuration.GetValue<string>("Data:ServiceTakersDbPath") ?? "db/service_takers.sqlite";
    }

    /// <summary>
    /// Gets the forecast system units integration API URL.
    /// </summary>
    public string? GetForecastUnitsApiUrl()
    {
        var envValue = Environment.GetEnvironmentVariable("LIGHTNING_TRACKER_FORECAST_UNITS_API_URL");
        if (!string.IsNullOrWhiteSpace(envValue))
        {
            return envValue.Trim();
        }

        return _configuration.GetValue<string>("Integrations:ForecastUnits:ApiUrl");
    }

    /// <summary>
    /// Gets the shared integration key used to call the forecast system units API.
    /// </summary>
    public string? GetForecastUnitsApiKey()
    {
        var envValue = Environment.GetEnvironmentVariable("LIGHTNING_TRACKER_FORECAST_UNITS_API_KEY");
        if (!string.IsNullOrWhiteSpace(envValue))
        {
            return envValue.Trim();
        }

        return _configuration.GetValue<string>("Integrations:ForecastUnits:ApiKey");
    }

    /// <summary>
    /// Gets whether the GLM sync service should start automatically.
    /// </summary>
    public bool GetGlmSyncEnabled()
    {
        var envValue = Environment.GetEnvironmentVariable("LIGHTNING_TRACKER_SYNC_ENABLED");
        if (!string.IsNullOrWhiteSpace(envValue) && bool.TryParse(envValue, out var parsed))
        {
            return parsed;
        }

        return _configuration.GetValue("Sync:Enabled", true);
    }

    /// <summary>
    /// Gets the GLM sync interval in seconds.
    /// </summary>
    public int GetGlmSyncIntervalSeconds()
    {
        var envValue = Environment.GetEnvironmentVariable("LIGHTNING_TRACKER_SYNC_INTERVAL_SECONDS");
        if (!string.IsNullOrWhiteSpace(envValue) && int.TryParse(envValue, out var parsed) && parsed > 0)
        {
            return parsed;
        }

        return _configuration.GetValue("Sync:IntervalSeconds", 300);
    }

    /// <summary>
    /// Gets the GLM sync lookback window in minutes for each iteration.
    /// </summary>
    public int GetGlmSyncLookbackMinutes()
    {
        var envValue = Environment.GetEnvironmentVariable("LIGHTNING_TRACKER_SYNC_LOOKBACK_MINUTES");
        if (!string.IsNullOrWhiteSpace(envValue) && int.TryParse(envValue, out var parsed) && parsed > 0)
        {
            return parsed;
        }

        return _configuration.GetValue("Sync:LookbackMinutes", 5);
    }

    /// <summary>
    /// Gets the GLM sync raw retention window in hours.
    /// </summary>
    public int GetGlmSyncRetentionHours()
    {
        var envValue = Environment.GetEnvironmentVariable("LIGHTNING_TRACKER_SYNC_RETENTION_HOURS");
        if (!string.IsNullOrWhiteSpace(envValue) && int.TryParse(envValue, out var parsed) && parsed > 0)
        {
            return parsed;
        }

        return _configuration.GetValue("Sync:RetentionHours", 3);
    }

    /// <summary>
    /// Gets whether raw files should be preserved after sync.
    /// </summary>
    public bool GetGlmSyncKeepRawFiles()
    {
        var envValue = Environment.GetEnvironmentVariable("LIGHTNING_TRACKER_SYNC_KEEP_RAW_FILES");
        if (!string.IsNullOrWhiteSpace(envValue) && bool.TryParse(envValue, out var parsed))
        {
            return parsed;
        }

        return _configuration.GetValue("Sync:KeepRawFiles", false);
    }
}
