using System.Text.Json;

namespace LightningTracker.WebApi.Models;

public sealed class PendingAlert
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public int TakerId { get; set; }
    public string TakerName { get; set; } = "";
    public string AlertLevel { get; set; } = ""; // Red, Yellow, Observing, None
    public string MessagePayloadJson { get; set; } = "";
    public string Status { get; set; } = "Pending"; // Pending, Active, Resolved, Rejected
    public int DurationMinutes { get; set; } = 60; // Default 1h
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? UpdatedAt { get; set; }
    public DateTime? SentAt { get; set; }
    public DateTime? LastUpdateAt { get; set; }

    public AlertPayload GetPayload() => JsonSerializer.Deserialize<AlertPayload>(MessagePayloadJson) ?? new AlertPayload();
}

public sealed class AlertPayload
{
    public int FlashCount { get; set; }
    public double MinDistance { get; set; }
    public string CountsSummary { get; set; } = "";
    public string MessagePreview { get; set; } = "";
    public NowcastImpact? Impact { get; set; }
}
