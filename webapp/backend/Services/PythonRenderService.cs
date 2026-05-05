using System.Diagnostics;
using LightningTracker.WebApi.Models;

namespace LightningTracker.WebApi.Services;

public sealed class PythonRenderService
{
    private readonly string _pythonCommand;
    private readonly string _workingDirectory;
    private readonly string _settingsPath;
    private readonly string _contentRoot;

    public sealed record RenderMetadata(
        string? LastUpdateLocal,
        IReadOnlyDictionary<string, string> Headers
    );

    public PythonRenderService(IConfiguration config, IHostEnvironment env)
    {
        _pythonCommand = config["Python:Command"] ?? "python";
        _workingDirectory = config["Python:WorkingDirectory"] ?? "..\\..";
        _settingsPath = config["Python:SettingsPath"] ?? "config\\settings.yaml";
        _contentRoot = env.ContentRootPath;
    }

    public async Task<(byte[] Png, RenderMetadata Metadata)> RenderAsync(
        ServiceTaker taker,
        int mode,
        string? startLocal,
        string? endLocal,
        int initialLoadHours,
        int background,
        CancellationToken cancellationToken
    )
    {
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
        };

        foreach (var a in args)
            psi.ArgumentList.Add(a);

        using var proc = new Process { StartInfo = psi };

        if (!proc.Start())
            throw new InvalidOperationException("Falha ao iniciar o processo Python.");

        await using var ms = new MemoryStream();

        var copyOut = proc.StandardOutput.BaseStream.CopyToAsync(ms, cancellationToken);
        var readErr = proc.StandardError.ReadToEndAsync(cancellationToken);

        await Task.WhenAll(copyOut, readErr);
        await proc.WaitForExitAsync(cancellationToken);

        if (proc.ExitCode != 0)
        {
            var err = (await readErr) ?? "";
            throw new InvalidOperationException($"Python retornou código {proc.ExitCode}. STDERR: {err}");
        }

        var stderr = (await readErr) ?? "";
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
