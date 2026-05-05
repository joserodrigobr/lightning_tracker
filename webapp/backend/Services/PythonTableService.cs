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

    public PythonTableService(IConfiguration config, IHostEnvironment env)
    {
        _pythonCommand = config["Python:Command"] ?? "python";
        _workingDirectory = config["Python:WorkingDirectory"] ?? "..\\..";
        _settingsPath = config["Python:SettingsPath"] ?? "config\\settings.yaml";
        _contentRoot = env.ContentRootPath;
    }

    public async Task<GeneratedTableResponse> GenerateAsync(
        ServiceTaker taker,
        string? endLocal,
        CancellationToken cancellationToken
    )
    {
        var args = new List<string>
        {
            "-m",
            "src.web_tables",
            "--settings",
            _settingsPath,
            "--name",
            taker.Name,
            "--lat",
            taker.Lat.ToString(System.Globalization.CultureInfo.InvariantCulture),
            "--lon",
            taker.Lon.ToString(System.Globalization.CultureInfo.InvariantCulture),
        };

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
        };

        foreach (var arg in args)
            psi.ArgumentList.Add(arg);

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
