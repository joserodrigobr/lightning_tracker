using System.Web;
using LightningTracker.WebApi.Data;
using LightningTracker.WebApi.Services;

namespace LightningTracker.WebApi.Endpoints;

public static class LightningTrackerEndpoints
{
    public static IEndpointRouteBuilder MapLightningTrackerEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/takers", async (ServiceTakerRepository repo, CancellationToken ct) =>
        {
            var takers = await repo.GetAllAsync(ct);
            return Results.Json(takers);
        });

        app.MapGet("/api/takers/active", async (PythonActivityService activityService, CancellationToken ct) =>
        {
            var selection = await activityService.GetDefaultTakerAsync(ct);
            return Results.Json(selection);
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

            var renderResult = await renderer.RenderAsync(
                taker,
                safeRequest.Mode,
                safeRequest.StartLocal,
                safeRequest.EndLocal,
                safeRequest.InitialLoadHours,
                safeRequest.Background,
                false,
                ct
            );

            var png = renderResult.Png;
            var metadata = renderResult.Metadata;

            foreach (var header in metadata.Headers)
                SetResponseHeader(response, header.Key, header.Value);

            return Results.File(png, "image/png");
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
            int takerId,
            string? endLocal,
            ServiceTakerRepository repo,
            PythonTableService tableService,
            CancellationToken ct
        ) =>
        {
            var taker = await repo.GetByIdAsync(takerId, ct);
            if (taker is null)
                return Results.NotFound(new { message = "Tomador não encontrado" });

            var result = await tableService.GenerateAsync(taker, endLocal, ct);
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

        return app;
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
