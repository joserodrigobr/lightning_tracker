using System.Diagnostics;
using System.Globalization;

namespace LightningTracker.WebApi.Services;

public sealed class GlmSyncHostedService : BackgroundService
{
    private readonly ConfigurationService _config;
    private readonly ILogger<GlmSyncHostedService> _logger;
    private readonly string _pythonCommand;
    private readonly string _workingDirectory;
    private readonly string _settingsPath;
    private readonly string _scriptPath;
    private readonly string? _postgresDsn;

    public GlmSyncHostedService(ConfigurationService config, IHostEnvironment env, ILogger<GlmSyncHostedService> logger)
    {
        _config = config;
        _logger = logger;
        _pythonCommand = config.GetPythonCommand();
        _workingDirectory = ResolvePath(env.ContentRootPath, config.GetPythonWorkingDirectory());
        _settingsPath = ResolvePath(_workingDirectory, "config", "settings.yaml");
        _scriptPath = ResolvePath(_workingDirectory, "scripts", "sync_recent_glm_to_postgres.py");
        _postgresDsn = config.GetPostgresDsn();
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!_config.GetGlmSyncEnabled())
        {
            _logger.LogInformation("GLM sync hosted service is disabled by configuration.");
            return;
        }

        if (string.IsNullOrWhiteSpace(_postgresDsn))
        {
            _logger.LogWarning("GLM sync is enabled, but no PostgreSQL DSN is configured. The backend will start without sync.");
            return;
        }

        var intervalSeconds = Math.Max(30, _config.GetGlmSyncIntervalSeconds());
        var interval = TimeSpan.FromSeconds(intervalSeconds);
        var lookbackMinutes = Math.Max(1, _config.GetGlmSyncLookbackMinutes());
        var retentionHours = Math.Max(1, _config.GetGlmSyncRetentionHours());
        var keepRawFiles = _config.GetGlmSyncKeepRawFiles();

        _logger.LogInformation(
            "Starting automatic GLM sync loop: interval={IntervalSeconds}s, lookback={LookbackMinutes}m, retention={RetentionHours}h, keepRawFiles={KeepRawFiles}, script={ScriptPath}",
            intervalSeconds,
            lookbackMinutes,
            retentionHours,
            keepRawFiles,
            _scriptPath);

        var firstRun = true;
        while (!stoppingToken.IsCancellationRequested)
        {
            if (!firstRun)
            {
                try
                {
                    await Task.Delay(interval, stoppingToken);
                }
                catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
                {
                    break;
                }
            }

            firstRun = false;

            try
            {
                await RunSyncOnceAsync(lookbackMinutes, retentionHours, keepRawFiles, stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Automatic GLM sync iteration failed.");
            }
        }

        _logger.LogInformation("Automatic GLM sync loop stopped.");
    }

    private async Task RunSyncOnceAsync(int lookbackMinutes, int retentionHours, bool keepRawFiles, CancellationToken cancellationToken)
    {
        var psi = new ProcessStartInfo
        {
            FileName = _pythonCommand,
            WorkingDirectory = _workingDirectory,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
            CreateNoWindow = true,
        };

        psi.ArgumentList.Add("-u");
        psi.ArgumentList.Add(_scriptPath);
        psi.ArgumentList.Add("--settings");
        psi.ArgumentList.Add(_settingsPath);
        psi.ArgumentList.Add("--lookback-minutes");
        psi.ArgumentList.Add(lookbackMinutes.ToString(CultureInfo.InvariantCulture));
        psi.ArgumentList.Add("--retention-hours");
        psi.ArgumentList.Add(retentionHours.ToString(CultureInfo.InvariantCulture));

        if (keepRawFiles)
        {
            psi.ArgumentList.Add("--keep-raw-files");
        }

        if (!string.IsNullOrWhiteSpace(_postgresDsn))
        {
            psi.Environment["LIGHTNING_TRACKER_PG_DSN"] = _postgresDsn;
        }

        psi.Environment["PYTHONIOENCODING"] = "utf-8";
        psi.Environment["PYTHONUNBUFFERED"] = "1";

        using var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
        using var cancellationRegistration = cancellationToken.Register(() =>
        {
            try
            {
                if (!proc.HasExited)
                {
                    proc.Kill(entireProcessTree: true);
                }
            }
            catch
            {
                // Best effort shutdown only.
            }
        });

        if (!proc.Start())
        {
            throw new InvalidOperationException("Failed to start GLM sync Python process.");
        }

        _logger.LogInformation("GLM sync process started: pid={ProcessId}, wd={WorkingDirectory}", proc.Id, psi.WorkingDirectory);

        var stdoutTask = DrainStreamAsync(proc.StandardOutput, line => _logger.LogInformation("[GLM-SYNC] {Line}", line), cancellationToken);
        var stderrTask = DrainStreamAsync(proc.StandardError, line => _logger.LogWarning("[GLM-SYNC] {Line}", line), cancellationToken);

        await proc.WaitForExitAsync(cancellationToken);
        await Task.WhenAll(stdoutTask, stderrTask);

        if (proc.ExitCode != 0)
        {
            throw new InvalidOperationException($"GLM sync Python process exited with code {proc.ExitCode}.");
        }

        _logger.LogInformation("GLM sync process completed successfully.");
    }

    private static async Task DrainStreamAsync(StreamReader reader, Action<string> logLine, CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            var line = await reader.ReadLineAsync();
            if (line is null)
            {
                break;
            }

            if (!string.IsNullOrWhiteSpace(line))
            {
                logLine(line);
            }
        }
    }

    private static string ResolvePath(params string[] segments)
    {
        return Path.GetFullPath(Path.Combine(segments));
    }

    private static string ResolvePath(string root, params string[] segments)
    {
        return Path.GetFullPath(Path.Combine(new[] { root }.Concat(segments).ToArray()));
    }
}