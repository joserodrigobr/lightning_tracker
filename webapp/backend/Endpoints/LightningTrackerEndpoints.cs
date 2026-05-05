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
            int takerId,
            int mode,
            string? startLocal,
            string? endLocal,
            int initialLoadHours,
            int background,
            ServiceTakerRepository repo,
            PythonRenderService renderer,
            HttpResponse response,
            CancellationToken ct
        ) =>
        {
            var taker = await repo.GetByIdAsync(takerId, ct);
            if (taker is null)
                return Results.NotFound(new { message = "Tomador não encontrado" });

            var safeRequest = RenderQuery.Normalize(
                takerId,
                mode,
                startLocal,
                endLocal,
                initialLoadHours,
                background
            );

            var (png, metadata) = await renderer.RenderAsync(
                taker,
                safeRequest.Mode,
                safeRequest.StartLocal,
                safeRequest.EndLocal,
                safeRequest.InitialLoadHours,
                safeRequest.Background,
                ct
            );

            foreach (var header in metadata.Headers)
                response.Headers[header.Key] = header.Value;

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

            var result = await catalog.GetLatestAsync(taker.Name, limit <= 0 ? 8 : limit, ct);
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
}
