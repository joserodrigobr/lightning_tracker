using System.Web;
using LightningTracker.WebApi.Data;
using LightningTracker.WebApi.Services;
using LightningTracker.WebApi.Models;

namespace LightningTracker.WebApi.Endpoints;

public static class LightningTrackerEndpoints
{
    public static IEndpointRouteBuilder MapLightningTrackerEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/status", (SystemStatusService status) => 
        {
            return Results.Json(new {
                sync = status.LastSync,
                nowcast = status.LastNowcast,
                logs = status.RecentLogs.ToArray()
            });
        });

        app.MapGet("/api/takers", async (ServiceTakerRepository repo, CancellationToken ct) =>
        {
            var takers = await repo.GetAllAsync(ct);
            return Results.Json(takers);
        });

        app.MapGet("/api/nowcast", async (
            HttpRequest request,
            PythonNowcastService nowcastService,
            CancellationToken ct
        ) =>
        {
            var takerId = GetIntQuery(request, "takerId");
            int? tid = takerId > 0 ? takerId : null;
            var report = await nowcastService.GetNowcastAsync(tid, ct);
            return Results.Json(report);
        });

        app.MapGet("/api/takers/active", async (PythonActivityService activityService, CancellationToken ct) =>
        {
            var selection = await activityService.GetDefaultTakerAsync(ct);
            return Results.Json(selection);
        });

        app.MapGet("/api/events", async (
            HttpRequest request,
            ServiceTakerRepository repo,
            LightningDataService dataService,
            CancellationToken ct
        ) =>
        {
            var takerId = GetIntQuery(request, "takerId");
            var mode = GetIntQuery(request, "mode", 1);
            var startLocalStr = GetStringQuery(request, "startLocal");
            var endLocalStr = GetStringQuery(request, "endLocal");
            var initialLoadHours = GetIntQuery(request, "initialLoadHours", 0);

            // BRT offset (UTC-3) for interpreting local times from frontend
            var brtOffset = TimeSpan.FromHours(-3);

            DateTime endUtc;
            if (string.IsNullOrEmpty(endLocalStr))
                endUtc = DateTime.UtcNow;
            else
            {
                var parsed = DateTime.Parse(endLocalStr);
                var dto = new DateTimeOffset(parsed, brtOffset);
                endUtc = dto.UtcDateTime;
            }

            DateTime startUtc;
            if (string.IsNullOrEmpty(startLocalStr))
                startUtc = endUtc.AddHours(initialLoadHours > 0 ? -initialLoadHours : -1);
            else
            {
                var parsed = DateTime.Parse(startLocalStr);
                var dto = new DateTimeOffset(parsed, brtOffset);
                startUtc = dto.UtcDateTime;
            }

            string kind = mode == 3 || mode == 4 ? "event" : "flash";

            // takerId <= 0 means "América do Sul" — fetch all events without spatial filter
            if (takerId <= 0)
            {
                var allEvents = await dataService.GetAllEventsAsync(startUtc, endUtc, kind, 1000000, ct);
                return Results.Json(allEvents);
            }

            var taker = await repo.GetByIdAsync(takerId, ct);
            if (taker is null)
                return Results.NotFound(new { message = "Tomador não encontrado" });

            // Fetch events near the taker (250km radius)
            var events = await dataService.GetEventsAsync(taker, startUtc, endUtc, 250.0, kind, 1000000, ct);
            return Results.Json(events);
        });

        app.MapGet("/api/background", async (
            HttpRequest request,
            ServiceTakerRepository repo,
            PythonBackgroundService bgService,
            CancellationToken ct
        ) =>
        {
            var takerId = GetIntQuery(request, "takerId");
            var maxRadiusKm = 250.0;
            var endLocalStr = GetStringQuery(request, "endLocal");

            var taker = await repo.GetByIdAsync(takerId, ct);
            if (taker is null)
                return Results.NotFound(new { message = "Tomador não encontrado" });

            DateTime endUtc = string.IsNullOrEmpty(endLocalStr) ? DateTime.UtcNow : DateTime.Parse(endLocalStr).ToUniversalTime();

            double dLat = maxRadiusKm / 111.0;
            double dLon = maxRadiusKm / (111.0 * Math.Max(0.2, Math.Cos(taker.Lat * Math.PI / 180.0)));
            double minLat = taker.Lat - dLat;
            double maxLat = taker.Lat + dLat;
            double minLon = taker.Lon - dLon;
            double maxLon = taker.Lon + dLon;

            var png = await bgService.GetBackgroundPngAsync(minLon, maxLon, minLat, maxLat, endUtc, ct);
            if (png == null || png.Length == 0)
            {
                // Return an empty transparent 1x1 PNG so Leaflet doesn't break
                byte[] emptyPng = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=");
                return Results.File(emptyPng, "image/png");
            }

            var response = request.HttpContext.Response;
            SetResponseHeader(response, "X-Background-Bounds", $"{minLat},{minLon},{maxLat},{maxLon}");
            
            return Results.File(png, "image/png");
        });

        // ── ABI IR Tile ──────────────────────────────────────────────────────────
        // Returns a georeferenced RGBA PNG for Leaflet ImageOverlay (full ABI disk, reprojected).
        // Query params:
        //   utc    ISO8601 UTC timestamp (defaults to now)
        //   cmap   gray_r | ir_enhanced (default: gray_r)
        // Response headers:
        //   X-Abi-Bounds   lat_min,lon_min,lat_max,lon_max  (real disk bounds)
        //   X-Abi-Utc      actual UTC of the ABI image used
        app.MapGet("/api/abi", async (
            HttpRequest request,
            PythonAbiService abiService,
            CancellationToken ct
        ) =>
        {
            var utcStr = GetStringQuery(request, "utc");
            DateTime utcTime = string.IsNullOrEmpty(utcStr) ? DateTime.UtcNow : DateTime.Parse(utcStr).ToUniversalTime();
            string cmap = GetStringQuery(request, "cmap") ?? "gray_r";

            var result = await abiService.GetTileAsync(utcTime, cmap, ct);

            if (result is null)
            {
                byte[] emptyPng = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=");
                return Results.File(emptyPng, "image/png");
            }

            var response = request.HttpContext.Response;
            SetResponseHeader(response, "X-Abi-Bounds", result.Bounds);
            SetResponseHeader(response, "X-Abi-Utc", result.UtcTime.ToString("O"));

            return Results.File(result.Png, "image/png");
        });

        app.MapGet("/api/render", async (
            HttpRequest request,
            ServiceTakerRepository repo,
            PythonRenderService renderer,
            HttpResponse response,
            CancellationToken ct
        ) =>
        {
            var takerId = GetIntQuery(request, "takerId");
            var mode = GetIntQuery(request, "mode");
            var startLocal = GetStringQuery(request, "startLocal");
            var endLocal = GetStringQuery(request, "endLocal");
            var safeInitialLoadHours = GetIntQuery(request, "initialLoadHours", 0);
            var safeBackground = GetIntQuery(request, "background", 0);

            var taker = await repo.GetByIdAsync(takerId, ct);
            if (taker is null)
                return Results.NotFound(new { message = "Tomador não encontrado" });

            var safeRequest = RenderQuery.Normalize(
                takerId,
                mode,
                startLocal,
                endLocal,
                safeInitialLoadHours,
                safeBackground
            );

            if (safeRequest.StartLocal is null && safeRequest.EndLocal is null && safeRequest.InitialLoadHours < 3)
            {
                safeRequest = safeRequest with { InitialLoadHours = 3 };
            }

            var safeBinMinutes = GetIntQuery(request, "binMinutes", 30);
            var safeShowPolygon = GetIntQuery(request, "showPolygon", 1) != 0;

            var renderResult = await renderer.RenderAsync(
                taker,
                safeRequest.Mode,
                safeRequest.StartLocal,
                safeRequest.EndLocal,
                safeRequest.InitialLoadHours,
                safeRequest.Background,
                false,
                safeBinMinutes,
                safeShowPolygon,
                false,
                ct
            );

            var png = renderResult.Png;
            var metadata = renderResult.Metadata;

            foreach (var header in metadata.Headers)
                SetResponseHeader(response, header.Key, header.Value);

            return Results.File(png, "image/png");
        });

        app.MapGet("/api/render/animation", async (
            HttpRequest request,
            ServiceTakerRepository repo,
            PythonRenderService renderer,
            HttpResponse response,
            CancellationToken ct
        ) =>
        {
            var takerId = GetIntQuery(request, "takerId");
            var mode = GetIntQuery(request, "mode");
            var startLocal = GetStringQuery(request, "startLocal");
            var endLocal = GetStringQuery(request, "endLocal");
            var binMinutes = GetIntQuery(request, "binMinutes", 10);
            var showPolygon = GetIntQuery(request, "showPolygon", 0) != 0;

            var taker = await repo.GetByIdAsync(takerId, ct);
            if (taker is null)
                return Results.NotFound(new { message = "Tomador não encontrado" });

            var renderResult = await renderer.RenderAsync(
                taker,
                mode,
                startLocal,
                endLocal,
                0,
                0, // Background? maybe too slow for animation
                false,
                binMinutes,
                showPolygon,
                true, // animate = true
                ct
            );

            return Results.File(renderResult.Png, "video/mp4", $"animation_{takerId}.mp4");
        });

        app.MapGet("/api/render/frame", async (
            HttpRequest request,
            ServiceTakerRepository repo,
            PythonRenderService renderer,
            HttpResponse response,
            CancellationToken ct
        ) =>
        {
            var takerId = GetIntQuery(request, "takerId");
            var mode = GetIntQuery(request, "mode");
            var startLocal = GetStringQuery(request, "startLocal");
            var endLocal = GetStringQuery(request, "endLocal");
            var safeInitialLoadHours = GetIntQuery(request, "initialLoadHours", 0);
            var safeBackground = GetIntQuery(request, "background", 0);
            var safeThumb = GetIntQuery(request, "thumb", 0);

            var safeBinMinutes = GetIntQuery(request, "binMinutes", 30);
            var safeShowPolygon = GetIntQuery(request, "showPolygon", 1) != 0;

            var taker = await repo.GetByIdAsync(takerId, ct);
            if (taker is null)
                return Results.NotFound(new { message = "Tomador não encontrado" });

            var safeRequest = RenderQuery.Normalize(
                takerId,
                mode,
                startLocal,
                endLocal,
                safeInitialLoadHours,
                safeBackground
            );

            if (safeRequest.StartLocal is null && safeRequest.EndLocal is null && safeRequest.InitialLoadHours < 3)
            {
                safeRequest = safeRequest with { InitialLoadHours = 3 };
            }

            var renderResult = await renderer.RenderAsync(
                taker,
                safeRequest.Mode,
                safeRequest.StartLocal,
                safeRequest.EndLocal,
                safeRequest.InitialLoadHours,
                safeRequest.Background,
                safeThumb != 0,
                safeBinMinutes,
                safeShowPolygon,
                false,
                ct
            );

            var png = renderResult.Png;
            var metadata = renderResult.Metadata;

            foreach (var header in metadata.Headers)
                SetResponseHeader(response, header.Key, header.Value);

            response.Headers["X-Render-Frame-Thumb"] = safeThumb != 0 ? "1" : "0";

            return Results.File(png, "image/png");
        });

        app.MapGet("/api/tables/generate", async (
            HttpRequest request,
            int takerId,
            string? endLocal,
            ServiceTakerRepository repo,
            PythonTableService tableService,
            CancellationToken ct
        ) =>
        {
            var period = GetStringQuery(request, "period");
            var binSizeStr = GetStringQuery(request, "binSize");
            if (!int.TryParse(binSizeStr, out var binSize)) binSize = 5;

            var taker = await repo.GetByIdAsync(takerId, ct);
            if (taker is null)
                return Results.NotFound(new { message = "Tomador não encontrado" });

            var result = await tableService.GenerateAsync(taker, endLocal, period, binSize, ct);
            return Results.Json(result);
        });

        app.MapGet("/api/tables/latest", async (
            int takerId,
            int limit,
            ServiceTakerRepository repo,
            TableCatalogService catalog,
            CancellationToken ct
        ) =>
        {
            var taker = await repo.GetByIdAsync(takerId, ct);
            if (taker is null)
                return Results.NotFound(new { message = "Tomador não encontrado" });

            var result = await catalog.GetLatestAsync(taker.Id, taker.Name, limit <= 0 ? 8 : limit, ct);
            return Results.Json(result);
        });

        app.MapGet("/api/tables/load", async (
            string relativePath,
            TableCatalogService catalog,
            CancellationToken ct
        ) =>
        {
            var result = await catalog.LoadAsync(relativePath, ct);
            return result is null
                ? Results.NotFound(new { message = "Tabela não encontrada" })
                : Results.Json(result);
        });

        // ── Pending & Active Alerts (Sentinela Operations) ──────────────────
        app.MapGet("/api/alerts/pending", async (PendingAlertRepository repo, CancellationToken ct) =>
        {
            var alerts = await repo.GetPendingAsync(ct);
            return Results.Json(alerts);
        });

        app.MapGet("/api/alerts/active", async (PendingAlertRepository repo, CancellationToken ct) =>
        {
            var alerts = await repo.GetActiveAsync(ct);
            return Results.Json(alerts);
        });

        app.MapPost("/api/alerts/{id}/approve", async (Guid id, int? duration, PendingAlertRepository repo, WhatsAppService wa, CancellationToken ct) =>
        {
            var alert = await repo.GetByIdAsync(id, ct);
            if (alert == null || alert.Status != "Pending") return Results.NotFound();

            alert.Status = "Active";
            alert.DurationMinutes = duration ?? alert.DurationMinutes;
            alert.SentAt = DateTime.UtcNow;

            // Load contacts and send WhatsApp
            var takerContacts = await GetTakerContactsAsync(alert.TakerName, ct);
            if (takerContacts.Any())
            {
                var payload = alert.GetPayload();
                foreach (var contact in takerContacts)
                {
                    if (!string.IsNullOrEmpty(contact.Phone))
                    {
                        await wa.SendAlertAsync(contact.Phone, contact.Name, alert.TakerName, alert.AlertLevel, payload);
                    }
                }
            }

            await repo.UpdateAlertAsync(alert, ct);
            return Results.Ok();
        });

        app.MapPost("/api/alerts/{id}/update", async (Guid id, string? newLevel, int? newDuration, PendingAlertRepository repo, WhatsAppService wa, CancellationToken ct) =>
        {
            var alert = await repo.GetByIdAsync(id, ct);
            if (alert == null || alert.Status != "Active") return Results.NotFound();

            if (!string.IsNullOrEmpty(newLevel)) alert.AlertLevel = newLevel;
            if (newDuration.HasValue) alert.DurationMinutes = newDuration.Value;
            alert.SentAt = DateTime.UtcNow;

            var takerContacts = await GetTakerContactsAsync(alert.TakerName, ct);
            if (takerContacts.Any())
            {
                var payload = alert.GetPayload();
                foreach (var contact in takerContacts)
                {
                    if (!string.IsNullOrEmpty(contact.Phone))
                    {
                        await wa.SendUpdateAsync(contact.Phone, contact.Name, alert.TakerName, alert.AlertLevel, alert.DurationMinutes, payload);
                    }
                }
            }

            await repo.UpdateAlertAsync(alert, ct);
            return Results.Ok();
        });

        app.MapPost("/api/alerts/{id}/close", async (Guid id, PendingAlertRepository repo, WhatsAppService wa, CancellationToken ct) =>
        {
            var alert = await repo.GetByIdAsync(id, ct);
            if (alert == null || alert.Status != "Active") return Results.NotFound();

            alert.Status = "Resolved";
            alert.SentAt = DateTime.UtcNow;

            var takerContacts = await GetTakerContactsAsync(alert.TakerName, ct);
            if (takerContacts.Any())
            {
                foreach (var contact in takerContacts)
                {
                    if (!string.IsNullOrEmpty(contact.Phone))
                    {
                        await wa.SendResolvedAsync(contact.Phone, contact.Name, alert.TakerName);
                    }
                }
            }

            await repo.UpdateAlertAsync(alert, ct);
            return Results.Ok();
        });

        app.MapPost("/api/alerts/{id}/reject", async (Guid id, PendingAlertRepository repo, CancellationToken ct) =>
        {
            await repo.UpdateStatusAsync(id, "Rejected", ct);
            return Results.Ok();
        });

        return app;
    }

    private static async Task<List<AlertContact>> GetTakerContactsAsync(string takerName, CancellationToken ct)
    {
        var contactsPath = Path.Combine(Directory.GetCurrentDirectory(), "db/alert_contacts.json");
        if (!File.Exists(contactsPath)) return new List<AlertContact>();
        
        var json = await File.ReadAllTextAsync(contactsPath, ct);
        var contacts = System.Text.Json.JsonSerializer.Deserialize<List<AlertContact>>(json, new System.Text.Json.JsonSerializerOptions { PropertyNameCaseInsensitive = true });
        return contacts?.Where(c => c.UnitName.Equals(takerName, StringComparison.OrdinalIgnoreCase)).ToList() ?? new List<AlertContact>();
    }

    private static int GetIntQuery(HttpRequest request, string key, int defaultValue = 0)
    {
        if (!request.Query.TryGetValue(key, out var value))
            return defaultValue;

        return int.TryParse(value.ToString(), out var parsed) ? parsed : defaultValue;
    }

    private static string? GetStringQuery(HttpRequest request, string key)
    {
        if (!request.Query.TryGetValue(key, out var value))
            return null;

        var text = value.ToString().Trim();
        return string.IsNullOrWhiteSpace(text) ? null : text;
    }

    private static double GetDoubleQuery(HttpRequest request, string key, double defaultValue = 0.0)
    {
        if (!request.Query.TryGetValue(key, out var value))
            return defaultValue;

        return double.TryParse(value.ToString(), System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture, out var parsed)
            ? parsed
            : defaultValue;
    }

    private static void SetResponseHeader(HttpResponse response, string key, string? value)
    {
        if (string.IsNullOrWhiteSpace(key) || string.IsNullOrWhiteSpace(value))
            return;

        // HTTP headers must be ASCII-safe. Encode non-ASCII characters using URL encoding (percent-encoding).
        var encoded = System.Web.HttpUtility.UrlEncode(value, System.Text.Encoding.UTF8);
        if (string.IsNullOrWhiteSpace(encoded))
            return;

        response.Headers[key] = encoded;
    }
}
