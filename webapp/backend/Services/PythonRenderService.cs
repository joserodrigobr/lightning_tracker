using System.Diagnostics;
using LightningTracker.WebApi.Models;

namespace LightningTracker.WebApi.Services;

public sealed class PythonRenderService
{
    private readonly ILogger<PythonRenderService> _logger;
    private readonly string _pythonCommand;
    private readonly string _workingDirectory;
    private readonly string _settingsPath;
    private readonly string _contentRoot;
    private readonly string? _postgresDsn;

    public sealed record RenderMetadata(
        string? LastUpdateLocal,
        IReadOnlyDictionary<string, string> Headers
    );

    public PythonRenderService(ConfigurationService config, IHostEnvironment env, ILogger<PythonRenderService> logger)
    {
        _logger = logger;
        _pythonCommand = config.GetPythonCommand();
        _workingDirectory = config.GetPythonWorkingDirectory();
        _settingsPath = config.GetPythonWorkingDirectory() is string wd 
            ? Path.Combine(wd, "config", "settings.yaml")
            : "config\\settings.yaml";
        _postgresDsn = config.GetPostgresDsn();
        _contentRoot = env.ContentRootPath;
    }

    public async Task<(byte[] Png, RenderMetadata Metadata)> RenderAsync(
        ServiceTaker taker,
        int mode,
        string? startLocal,
        string? endLocal,
        int initialLoadHours,
        int background,
        bool thumb,
        CancellationToken cancellationToken
    )
    {
        const int renderTimeoutSeconds = 300;
        var processStarted = Stopwatch.StartNew();

        var args = new List<string>
        {
            "-m",
            "src.web_render",
            "--settings",
            _settingsPath,
            "--name",
            taker.Name,
            "--lat",
            taker.Lat.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "--lon",
            taker.Lon.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "--mode",
            mode.ToString(),
            "--initial-load-hours",
            initialLoadHours.ToString(),
            "--background",
            background.ToString(),
            "--thumb",
            thumb ? "1" : "0",
        };

        if (!string.IsNullOrWhiteSpace(startLocal))
        {
            args.Add("--start-local");
            args.Add(startLocal!);
        }

        if (!string.IsNullOrWhiteSpace(endLocal))
        {
            args.Add("--end-local");
            args.Add(endLocal!);
        }

        var psi = new ProcessStartInfo
        {
            FileName = _pythonCommand,
            WorkingDirectory = ResolveWorkingDirectory(),
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
        };

        foreach (var a in args)
            psi.ArgumentList.Add(a);

        if (!string.IsNullOrWhiteSpace(_postgresDsn))
            psi.Environment["LIGHTNING_TRACKER_PG_DSN"] = _postgresDsn;
        
        // Ensure Python uses UTF-8
        psi.Environment["PYTHONIOENCODING"] = "utf-8";

        using var proc = new Process { StartInfo = psi };

        if (!proc.Start())
            throw new InvalidOperationException("Falha ao iniciar o processo Python.");

        // Log for debugging
        var debugInfo = $"[DEBUG] Python subprocess started: wd={psi.WorkingDirectory}, settings={_settingsPath}";
        _logger.LogInformation(debugInfo);

        await using var ms = new MemoryStream();
        var stdoutTask = proc.StandardOutput.BaseStream.CopyToAsync(ms, cancellationToken);
        var stderrTask = proc.StandardError.ReadToEndAsync(cancellationToken);
        var waitTask = proc.WaitForExitAsync(cancellationToken);
        var timeoutTask = Task.Delay(TimeSpan.FromSeconds(renderTimeoutSeconds), cancellationToken);

        var completed = await Task.WhenAny(Task.WhenAll(stdoutTask, stderrTask, waitTask), timeoutTask);
        if (completed == timeoutTask)
        {
            try
            {
                if (!proc.HasExited)
                    proc.Kill(entireProcessTree: true);
            }
            catch
            {
                // ignore process cleanup failures
            }

            string timeoutStderr = "";
            try
            {
                var stderrCompleted = await Task.WhenAny(stderrTask, Task.Delay(TimeSpan.FromSeconds(5), cancellationToken));
                if (stderrCompleted == stderrTask)
                    timeoutStderr = await stderrTask ?? "";
            }
            catch
            {
                // ignore diagnostics collection failures
            }

            var elapsed = processStarted.Elapsed;
            if (!string.IsNullOrWhiteSpace(timeoutStderr))
                _logger.LogWarning("Python render timed out after {ElapsedMs}ms. STDERR: {Stderr}", elapsed.TotalMilliseconds, timeoutStderr);
            else
                _logger.LogWarning("Python render timed out after {ElapsedMs}ms.", elapsed.TotalMilliseconds);

            throw new TimeoutException($"Python render excedeu {renderTimeoutSeconds} segundos. Elapsed={elapsed.TotalSeconds:F1}s. {timeoutStderr}".Trim());
        }

        var stderr = await stderrTask ?? "";
        if (proc.ExitCode != 0)
        {
            throw new InvalidOperationException($"Python retornou código {proc.ExitCode}. STDERR: {stderr}");
        }

        if (!string.IsNullOrWhiteSpace(stderr))
        {
            _logger.LogDebug("Python render stderr: {Stderr}", stderr);
            
            // Write stderr to debug file for diagnostics
            try
            {
                var debugFile = Path.Combine(_contentRoot, "..", "..", "python_stderr_debug.txt");
                System.IO.File.WriteAllText(debugFile, stderr);
            }
            catch { }
        }

        _logger.LogInformation("Python render finished in {ElapsedMs}ms.", processStarted.Elapsed.TotalMilliseconds);

        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var line in stderr.Split(new[] { "\r\n", "\n" }, StringSplitOptions.RemoveEmptyEntries))
        {
            var colonIndex = line.IndexOf(':');
            if (colonIndex <= 0)
                continue;

            var key = line[..colonIndex].Trim();
            var value = line[(colonIndex + 1)..].Trim();
            if (key.StartsWith("X-", StringComparison.OrdinalIgnoreCase) && value.Length > 0)
                headers[key] = value;
        }

        headers.TryGetValue("X-Last-Update-Local", out var lastUpdateLocal);
        return (ms.ToArray(), new RenderMetadata(lastUpdateLocal, headers));
    }

    private string ResolveWorkingDirectory()
    {
        // Resolve relative to the web project's content root.
        if (Path.IsPathRooted(_workingDirectory))
            return _workingDirectory;

        return Path.GetFullPath(Path.Combine(_contentRoot, _workingDirectory));
    }
}
