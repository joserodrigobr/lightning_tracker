using System.Text.Json.Serialization;

namespace LightningTracker.WebApi.Models;

public sealed record NowcastProjection(
    [property: JsonPropertyName("minutes")] int Minutes,
    [property: JsonPropertyName("lat")] double Lat,
    [property: JsonPropertyName("lon")] double Lon,
    [property: JsonPropertyName("confidence")] double Confidence
);

public sealed record NowcastCellReport(
    [property: JsonPropertyName("cellId")] string CellId,
    [property: JsonPropertyName("centroidLat")] double CentroidLat,
    [property: JsonPropertyName("centroidLon")] double CentroidLon,
    [property: JsonPropertyName("flashCount")] int FlashCount,
    [property: JsonPropertyName("areaKm2")] double AreaKm2,
    [property: JsonPropertyName("velocityKmh")] double VelocityKmh,
    [property: JsonPropertyName("bearingDeg")] double BearingDeg,
    [property: JsonPropertyName("bearingLabel")] string BearingLabel,
    [property: JsonPropertyName("confidence")] double Confidence,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("projections")] List<NowcastProjection> Projections,
    [property: JsonPropertyName("hullLat")] List<double> HullLat,
    [property: JsonPropertyName("hullLon")] List<double> HullLon
);

public sealed record NowcastImpact(
    [property: JsonPropertyName("takerId")] int TakerId,
    [property: JsonPropertyName("takerName")] string TakerName,
    [property: JsonPropertyName("cellId")] string CellId,
    [property: JsonPropertyName("etaMinutes")] int EtaMinutes,
    [property: JsonPropertyName("ringKm")] int RingKm,
    [property: JsonPropertyName("projectedLat")] double ProjectedLat,
    [property: JsonPropertyName("projectedLon")] double ProjectedLon,
    [property: JsonPropertyName("confidence")] double Confidence,
    [property: JsonPropertyName("velocityKmh")] double VelocityKmh,
    [property: JsonPropertyName("bearingDeg")] double BearingDeg,
    [property: JsonPropertyName("bearingLabel")] string BearingLabel,
    [property: JsonPropertyName("approaching")] bool Approaching
);

public sealed record NowcastReport(
    [property: JsonPropertyName("generatedAtUtc")] string GeneratedAtUtc,
    [property: JsonPropertyName("frameCount")] int FrameCount,
    [property: JsonPropertyName("cells")] List<NowcastCellReport> Cells,
    [property: JsonPropertyName("impacts")] List<NowcastImpact> Impacts
);
