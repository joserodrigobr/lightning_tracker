namespace LightningTracker.WebApi.Endpoints;

public sealed record RenderQuery(
    int TakerId,
    int Mode,
    string? StartLocal,
    string? EndLocal,
    int InitialLoadHours,
    int Background
)
{
    public static RenderQuery Normalize(
        int takerId,
        int mode,
        string? startLocal,
        string? endLocal,
        int initialLoadHours,
        int background
    )
    {
        var safeMode = mode is >= 1 and <= 4 ? mode : 1;
        var safeInit = Math.Clamp(initialLoadHours, 0, 24);
        var safeBg = background != 0 ? 1 : 0;

        return new RenderQuery(
            takerId,
            safeMode,
            NormalizeDateTimeLocal(startLocal),
            NormalizeDateTimeLocal(endLocal),
            safeInit,
            safeBg
        );
    }

    private static string? NormalizeDateTimeLocal(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return null;

        var text = value.Trim();
        if (text.Length == 16)
            return $"{text}:00";

        return text;
    }
}
