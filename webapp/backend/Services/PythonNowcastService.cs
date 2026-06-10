using System.Diagnostics;
using System.Text.Json;
using LightningTracker.WebApi.Data;
using LightningTracker.WebApi.Models;
using Microsoft.Extensions.Caching.Memory;

namespace LightningTracker.WebApi.Services;

public sealed class PythonNowcastService
{
    private readonly ConfigurationService _config;
    private readonly string _pythonCommand;
    private readonly string _workingDirectory;
    private readonly string _settingsPath;
    private readonly string _contentRoot;
    private readonly IMemoryCache _cache;
    private readonly SystemStatusService _status;
    private readonly ILogger<PythonNowcastService> _logger;
    private readonly ServiceTakerRepository _serviceTakerRepository;

    public PythonNowcastService(
        ConfigurationService config,
        IHostEnvironment env,
        IMemoryCache cache,
        ILogger<PythonNowcastService> logger,
        SystemStatusService status,
        ServiceTakerRepository serviceTakerRepository)
    {
        _config = config;
        _status = status;
        _pythonCommand = config.GetPythonCommand();
        _workingDirectory = config.GetPythonWorkingDirectory();
        _settingsPath = Path.Combine(config.GetPythonWorkingDirectory(), "config", "settings.yaml");
        _contentRoot = env.ContentRootPath;
        _cache = cache;
        _logger = logger;
        _serviceTakerRepository = serviceTakerRepository;
    }

    public async Task<NowcastReport> GetNowcastAsync(int? takerId, CancellationToken cancellationToken)
    {
        // Cache the result for 60 seconds to avoid running the python engine multiple times per minute
        var cacheKey = $"nowcast_{takerId?.ToString() ?? "all"}";
        
        if (_cache.TryGetValue(cacheKey, out NowcastReport? cachedReport) && cachedReport != null)
        {
            return cachedReport;
        }

        await _serviceTakerRepository.GetAllAsync(cancellationToken);

        var args = new List<string>
        {
            "-m",
            "src.nowcast.engine",
            "--settings",
            _settingsPath,
        };

        if (takerId.HasValue)
        {
            args.Add("--taker-ids");
            args.Add(takerId.Value.ToString());
        }

        var psi = new ProcessStartInfo
        {
            FileName = _pythonCommand,
            WorkingDirectory = ResolveWorkingDirectory(),
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };

        var dsn = _config.GetPostgresDsn();
        if (!string.IsNullOrEmpty(dsn))
        {
            psi.EnvironmentVariables["LIGHTNING_TRACKER_PG_DSN"] = dsn;
        }

        foreach (var arg in args)
            psi.ArgumentList.Add(arg);

        _logger.LogInformation("Executando Nowcast Engine para taker {TakerId}...", takerId?.ToString() ?? "todos");
        _status.SetNowcastRunning(true);

        using var proc = new Process { StartInfo = psi };
        if (!proc.Start())
            throw new InvalidOperationException("Falha ao iniciar o processo Python Nowcast.");

        var stdoutTask = proc.StandardOutput.ReadToEndAsync(cancellationToken);
        var stderrTask = proc.StandardError.ReadToEndAsync(cancellationToken);
        var waitTask = proc.WaitForExitAsync(cancellationToken);

        var timeoutTask = Task.Delay(TimeSpan.FromSeconds(60), cancellationToken);
        var completedTask = await Task.WhenAny(Task.WhenAll(stdoutTask, stderrTask, waitTask), timeoutTask);

        if (completedTask == timeoutTask)
        {
            try { proc.Kill(true); } catch {}
            _status.UpdateNowcast(0, 0, "Timeout: Engine demorou mais de 60s");
            throw new TimeoutException("O motor de Nowcast excedeu o tempo limite de 60 segundos.");
        }

        var stdout = await stdoutTask;
        var stderr = await stderrTask;

        if (proc.ExitCode != 0)
        {
            _status.UpdateNowcast(0, 0, $"Exit code {proc.ExitCode}");
            _logger.LogError("Erro no Nowcast Engine: {Stderr}", stderr);
            throw new InvalidOperationException($"Python nowcast retornou código {proc.ExitCode}. STDERR: {stderr}");
        }

        var result = JsonSerializer.Deserialize<NowcastReport>(stdout, new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true,
        });

        if (result == null)
        {
            _status.UpdateNowcast(0, 0, "Invalid JSON result");
            throw new InvalidOperationException("Nowcast engine não retornou um resultado válido.");
        }

        _status.UpdateNowcast(result.Cells?.Count ?? 0, result.Impacts?.Count ?? 0);
        _logger.LogInformation("Nowcast concluído: {CellCount} células identificadas, {ImpactCount} impactos previstos.", result.Cells?.Count ?? 0, result.Impacts?.Count ?? 0);

        _cache.Set(cacheKey, result, TimeSpan.FromSeconds(60));

        return result;
    }

    private string ResolveWorkingDirectory()
    {
        if (Path.IsPathRooted(_workingDirectory))
            return _workingDirectory;

        return Path.GetFullPath(Path.Combine(_contentRoot, _workingDirectory));
    }
}
