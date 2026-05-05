namespace LightningTracker.WebApi.Models;

public sealed record GeneratedTableResponse(
    string TakerName,
    string CsvPath,
    string CsvRelativePath,
    string SavedAtLocal,
    string EndLocal,
    string[] HourLabels,
    string[] RadiiLabels,
    int[][] Values4x24
);
