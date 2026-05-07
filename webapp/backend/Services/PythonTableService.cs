using System.Diagnostics;
using System.Text.Json;
using LightningTracker.WebApi.Models;

namespace LightningTracker.WebApi.Services;

public sealed class PythonTableService
{
    private readonly string _pythonCommand;
    private readonly string _workingDirectory;
    private readonly string _settingsPath;
    private readonly string _contentRoot;
    private readonly string? _postgresDsn;

    public PythonTableService(ConfigurationService config, IHostEnvironment env)
    {
        _pythonCommand = config.GetPythonCommand();
        _workingDirectory = config.GetPythonWorkingDirectory();
        _settingsPath = config.GetPythonWorkingDirectory() is string wd 
            ? Path.Combine(wd, "config", "settings.yaml")
            : "config\\settings.yaml";
        _postgresDsn = config.GetPostgresDsn();
        _contentRoot = env.ContentRootPath;
    }

    public async Task<GeneratedTableResponse> GenerateAsync(
        ServiceTaker taker,
        string? endLocal,
        string? period,
        int binSize,
        CancellationToken cancellationToken
    )
    {
        var args = new List<string>
        {
            "-m",
            "src.web_tables",
            "--settings",
            _settingsPath,
            "--taker-id",
            taker.Id.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "--name",
            taker.Name,
            "--lat",
            taker.Lat.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "--lon",
            taker.Lon.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "--bin-size",
            binSize.ToString(System.Globalization.CultureInfo.InvariantCulture)
        };

        if (!string.IsNullOrWhiteSpace(endLocal))
        {
            args.Add("--end-local");
            args.Add(endLocal!);
        }
        
        if (!string.IsNullOrWhiteSpace(period))
        {
            args.Add("--period");
            args.Add(period!);
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

        foreach (var arg in args)
            psi.ArgumentList.Add(arg);

        if (!string.IsNullOrWhiteSpace(_postgresDsn))
            psi.Environment["LIGHTNING_TRACKER_PG_DSN"] = _postgresDsn;

        psi.Environment["LIGHTNING_TRACKER_TAKER_ID"] = taker.Id.ToString(System.Globalization.CultureInfo.InvariantCulture);

        using var proc = new Process { StartInfo = psi };
        if (!proc.Start())
            throw new InvalidOperationException("Falha ao iniciar o processo Python de geração da tabela.");

        var stdoutTask = proc.StandardOutput.ReadToEndAsync(cancellationToken);
        var stderrTask = proc.StandardError.ReadToEndAsync(cancellationToken);
        await proc.WaitForExitAsync(cancellationToken);

        var stdout = await stdoutTask;
        var stderr = await stderrTask;

        if (proc.ExitCode != 0)
            throw new InvalidOperationException($"Python de tabela retornou código {proc.ExitCode}. STDERR: {stderr}");

        var result = JsonSerializer.Deserialize<GeneratedTableResponse>(stdout, new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true,
        });

        return result ?? throw new InvalidOperationException("Geração da tabela não retornou um resultado válido.");
    }

    private string ResolveWorkingDirectory()
    {
        if (Path.IsPathRooted(_workingDirectory))
            return _workingDirectory;

        return Path.GetFullPath(Path.Combine(_contentRoot, _workingDirectory));
    }
}
