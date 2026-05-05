using LightningTracker.WebApi.Data;
using LightningTracker.WebApi.Endpoints;
using LightningTracker.WebApi.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSingleton<ServiceTakerRepository>();
builder.Services.AddSingleton<PythonRenderService>();
builder.Services.AddSingleton<PythonActivityService>();
builder.Services.AddSingleton<PythonTableService>();
builder.Services.AddSingleton<TableCatalogService>();

var app = builder.Build();

app.MapLightningTrackerEndpoints();

app.Run();
