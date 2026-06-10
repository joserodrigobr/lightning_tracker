namespace LightningTracker.WebApi.Models;

public sealed record DataRequestEmailRequest(
    string Name,
    string Email,
    int TakerId,
    string TakerName,
    string StartTime,
    string EndTime,
    int IntervalMinutes,
    string DataType
);

public sealed record DataRequestEmailResult(bool Success, string Message);

public sealed class DataRequestEmailOptions
{
    public string? Host { get; init; }
    public int Port { get; init; } = 587;
    public string? Username { get; init; }
    public string? Password { get; init; }
    public string? From { get; init; }
    public string? To { get; init; }
    public bool EnableSsl { get; init; } = true;
}
