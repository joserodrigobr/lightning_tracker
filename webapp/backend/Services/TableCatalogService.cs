using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace LightningTracker.WebApi.Services;

public sealed record SavedTableSummary(
    string RelativePath,
    string FileName,
    string TakerSlug,
    string SavedAtLocal,
    string LastWriteLocal
);

public sealed record LoadedTableResponse(
    string RelativePath,
    string FileName,
    string SavedAtLocal,
    string[] HourLabels,
    string[] RadiiLabels,
    int[][] Values4x24
);

public sealed class TableCatalogService
{
    private readonly string _tablesRoot;
    private readonly string _contentRoot;

    public TableCatalogService(IConfiguration config, IHostEnvironment env)
    {
        var tablesRoot = config["Data:TablesRootPath"] ?? @"..\..\output\tables";
        _tablesRoot = Path.IsPathRooted(tablesRoot)
            ? tablesRoot
            : Path.GetFullPath(Path.Combine(env.ContentRootPath, tablesRoot));
        _contentRoot = env.ContentRootPath;
    }

    public Task<IReadOnlyList<SavedTableSummary>> GetLatestAsync(string takerName, int limit, CancellationToken cancellationToken)
    {
        var slug = Slugify(takerName);
        if (!Directory.Exists(_tablesRoot))
            return Task.FromResult<IReadOnlyList<SavedTableSummary>>(Array.Empty<SavedTableSummary>());

        var files = Directory.EnumerateFiles(_tablesRoot, "*_table_*.csv", SearchOption.AllDirectories)
            .Select(path => new FileInfo(path))
            .Where(info => info.Name.StartsWith(slug + "_table_", StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(info => info.LastWriteTimeUtc)
            .Take(Math.Max(1, limit));

        var result = files.Select(info => new SavedTableSummary(
            RelativePath: ToRelativePath(info.FullName),
            FileName: info.Name,
            TakerSlug: slug,
            SavedAtLocal: ExtractTimestampLabel(info.Name),
            LastWriteLocal: info.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture)
        )).ToList();

        return Task.FromResult<IReadOnlyList<SavedTableSummary>>(result);
    }

    public Task<LoadedTableResponse?> LoadAsync(string tableRelativePath, CancellationToken cancellationToken)
    {
        var fullPath = ResolveWithinTablesRoot(tableRelativePath);
        if (fullPath is null || !File.Exists(fullPath))
            return Task.FromResult<LoadedTableResponse?>(null);

        var lines = File.ReadAllLines(fullPath, Encoding.UTF8);
        if (lines.Length < 2)
            return Task.FromResult<LoadedTableResponse?>(null);

        var header = SplitCsvLine(lines[0]);
        var hourLabels = header.Skip(1).ToArray();
        var radiiLabels = new List<string>();
        var rows = new List<int[]>();

        foreach (var rawLine in lines.Skip(1))
        {
            var line = rawLine.Trim();
            if (string.IsNullOrWhiteSpace(line))
                continue;

            var parts = SplitCsvLine(line);
            if (parts.Length < 2)
                continue;

            radiiLabels.Add(parts[0]);
            var values = new int[hourLabels.Length];
            for (var i = 1; i < parts.Length && i <= hourLabels.Length; i++)
            {
                if (int.TryParse(parts[i], NumberStyles.Integer, CultureInfo.InvariantCulture, out var value))
                    values[i - 1] = value;
            }
            rows.Add(values);
        }

        var tablePath = ToRelativePath(fullPath);
        var savedAtLocal = ExtractTimestampLabel(Path.GetFileName(fullPath));
        return Task.FromResult<LoadedTableResponse?>(new LoadedTableResponse(
            RelativePath: tablePath,
            FileName: Path.GetFileName(fullPath),
            SavedAtLocal: savedAtLocal,
            HourLabels: hourLabels,
            RadiiLabels: radiiLabels.ToArray(),
            Values4x24: rows.ToArray()
        ));
    }

    private string? ResolveWithinTablesRoot(string relativePath)
    {
        if (string.IsNullOrWhiteSpace(relativePath))
            return null;

        var normalized = relativePath.Replace('/', Path.DirectorySeparatorChar);
        var combined = Path.GetFullPath(Path.Combine(_tablesRoot, normalized));
        if (!combined.StartsWith(_tablesRoot, StringComparison.OrdinalIgnoreCase))
            return null;

        return combined;
    }

    private string ToRelativePath(string fullPath)
    {
        try
        {
            return Path.GetRelativePath(_tablesRoot, fullPath).Replace(Path.DirectorySeparatorChar, '/');
        }
        catch
        {
            return fullPath.Replace(Path.DirectorySeparatorChar, '/');
        }
    }

    private static string[] SplitCsvLine(string line) => line.Split(';');

    private static string ExtractTimestampLabel(string fileName)
    {
        var match = Regex.Match(fileName, @"_table_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.csv$", RegexOptions.CultureInvariant);
        if (match.Success)
            return match.Groups[1].Value.Replace('_', ' ');
        return string.Empty;
    }

    private static string Slugify(string value)
    {
        var slug = Regex.Replace((value ?? string.Empty).Trim(), "[^A-Za-z0-9]+", "_");
        slug = slug.Trim('_');
        return slug.Length > 64 ? slug[..64] : slug;
    }
}
