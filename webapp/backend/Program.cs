using LightningTracker.WebApi.Data;
using LightningTracker.WebApi.Endpoints;
using LightningTracker.WebApi.Services;
using LightningTracker.WebApi.Workers;
using System.Text;

// Ensure UTF-8 encoding for non-ASCII paths and I/O
Console.OutputEncoding = Encoding.UTF8;
Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSingleton<ConfigurationService>();
builder.Services.AddSingleton<ServiceTakerRepository>();
builder.Services.AddSingleton<PythonRenderService>();
builder.Services.AddSingleton<PythonActivityService>();
builder.Services.AddSingleton<PythonTableService>();
builder.Services.AddSingleton<TableCatalogService>();
builder.Services.AddSingleton<PythonBackgroundService>();
builder.Services.AddSingleton<PythonAbiService>();
builder.Services.AddSingleton<LightningDataService>();
builder.Services.AddHostedService<GlmSyncHostedService>();
builder.Services.AddHostedService<LightningAlertWorker>();

var app = builder.Build();

app.MapLightningTrackerEndpoints();

app.Run();
