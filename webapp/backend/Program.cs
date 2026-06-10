using LightningTracker.WebApi.Data;
using LightningTracker.WebApi.Endpoints;
using LightningTracker.WebApi.Services;
using LightningTracker.WebApi.Workers;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddMemoryCache();
builder.Services.AddHttpClient();
builder.Services.AddSingleton<ConfigurationService>();
builder.Services.AddSingleton<SystemStatusService>();
builder.Services.AddSingleton<ServiceTakerRepository>();
builder.Services.AddSingleton<PythonRenderService>();
builder.Services.AddSingleton<PythonActivityService>();
builder.Services.AddSingleton<PythonTableService>();
builder.Services.AddSingleton<TableCatalogService>();
builder.Services.AddSingleton<PythonBackgroundService>();
builder.Services.AddSingleton<PythonAbiService>();
builder.Services.AddSingleton<PythonNowcastService>();
builder.Services.AddSingleton<LightningDataService>();
builder.Services.AddSingleton<PendingAlertRepository>();
builder.Services.AddSingleton<WhatsAppService>();
builder.Services.AddSingleton<DataRequestEmailService>();
builder.Services.AddHostedService<GlmSyncHostedService>();
builder.Services.AddHostedService<LightningAlertWorker>();

var app = builder.Build();

app.MapGet("/ping", () => "pong");

app.MapLightningTrackerEndpoints();

app.Run("http://0.0.0.0:5080");
