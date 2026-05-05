using System.Diagnostics;
using System.Text.Json;

namespace LightningTracker.WebApi.Services;

public sealed class PythonActivityService
{
    private readonly string _pythonCommand;
    private readonly string _workingDirectory;
    private readonly string _settingsPath;
    private readonly string _sqlitePath;
    private readonly string _contentRoot;

    public PythonActivityService(IConfiguration config, IHostEnvironment env)
    {
        _pythonCommand = config["Python:Command"] ?? "python";
        _workingDirectory = config["Python:WorkingDirectory"] ?? "..\\..";
        _settingsPath = config["Python:SettingsPath"] ?? "config\\settings.yaml";
        _sqlitePath = config["Data:ServiceTakersDbPath"] ?? "db/service_takers.sqlite";
        _contentRoot = env.ContentRootPath;
    }

    public async Task<ActiveTakerSelection> GetDefaultTakerAsync(CancellationToken cancellationToken)
    {
        var args = new List<string>
        {
            "-m",
            "src.web_auto_select",
            "--settings",
            _settingsPath,
            "--db-path",
            ResolvePath(_sqlitePath),
            "--window-minutes",
            "30",
        };

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
            throw new InvalidOperationException("Falha ao iniciar o processo Python de seleção automática.");

        var stdout = await proc.StandardOutput.ReadToEndAsync(cancellationToken);
        var stderr = await proc.StandardError.ReadToEndAsync(cancellationToken);
        await proc.WaitForExitAsync(cancellationToken);

        if (proc.ExitCode != 0)
            throw new InvalidOperationException($"Python de seleção retornou código {proc.ExitCode}. STDERR: {stderr}");

        var result = JsonSerializer.Deserialize<ActiveTakerSelection>(stdout, new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true,
        });

        return result ?? throw new InvalidOperationException("Seleção automática não retornou um resultado válido.");
    }

    private string ResolveWorkingDirectory()
    {
        if (Path.IsPathRooted(_workingDirectory))
            return _workingDirectory;

        return Path.GetFullPath(Path.Combine(_contentRoot, _workingDirectory));
    }

    private string ResolvePath(string path)
    {
        if (Path.IsPathRooted(path))
            return path;

        return Path.GetFullPath(Path.Combine(_contentRoot, path));
    }
}

public sealed record ActiveTakerSelection(
    int TakerId,
    string TakerName,
    int FlashesCount,
    string WindowStartUtc,
    string WindowEndUtc
);