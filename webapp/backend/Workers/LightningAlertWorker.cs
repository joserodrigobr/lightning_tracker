using System.Net;
using System.Net.Mail;
using System.Net.Http.Json;
using System.Text.Json;
using LightningTracker.WebApi.Data;
using LightningTracker.WebApi.Services;
using LightningTracker.WebApi.Models;

namespace LightningTracker.WebApi.Workers;

public class LightningAlertWorker : BackgroundService
{
    private readonly ILogger<LightningAlertWorker> _logger;
    private readonly IServiceProvider _serviceProvider;
    private readonly TimeSpan _checkInterval = TimeSpan.FromMinutes(5);

    private enum AlertLevel { None, Observing, Yellow, Red }

    private class AlertSession
    {
        public AlertLevel CurrentLevel { get; set; } = AlertLevel.None;
        public DateTime LastUpdateTime { get; set; }
    }

    private readonly Dictionary<int, AlertSession> _activeSessions = new();

    public LightningAlertWorker(ILogger<LightningAlertWorker> logger, IServiceProvider serviceProvider)
    {
        _logger = logger;
        _serviceProvider = serviceProvider;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        await Task.Yield();
        _logger.LogInformation("Sistema Sentinel Nowcast de Alertas (Aprovação Humana) iniciado.");

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await CheckAndQueueAlertsAsync(stoppingToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Sentinel: Erro no ciclo de verificação.");
            }

            await Task.Delay(_checkInterval, stoppingToken);
        }
    }

    private async Task CheckAndQueueAlertsAsync(CancellationToken ct)
    {
        using var scope = _serviceProvider.CreateScope();
        var repo = scope.ServiceProvider.GetRequiredService<ServiceTakerRepository>();
        var pendingRepo = scope.ServiceProvider.GetRequiredService<PendingAlertRepository>();
        var dataService = scope.ServiceProvider.GetRequiredService<LightningDataService>();
        var nowcastService = scope.ServiceProvider.GetRequiredService<PythonNowcastService>();
        
        var takers = await repo.GetAllAsync(ct);
        var nowcast = await nowcastService.GetNowcastAsync(null, ct);
        
        _logger.LogInformation("[SENTINEL] Ciclo de alertas: {Takers} tomadores, {Cells} células detectadas, {Impacts} impactos encontrados.", 
            takers.Count(), nowcast.Cells.Count, nowcast.Impacts.Count);

        foreach (var taker in takers)
        {
            var impact = nowcast.Impacts.FirstOrDefault(i => i.TakerId == taker.Id && i.Approaching);
            AlertLevel targetLevel = AlertLevel.None;

            if (impact != null)
            {
                if (impact.EtaMinutes <= 15) targetLevel = AlertLevel.Red;
                else if (impact.EtaMinutes <= 30) targetLevel = AlertLevel.Yellow;
                else targetLevel = AlertLevel.Observing;
            }

            if (targetLevel == AlertLevel.None) 
            {
                if (_activeSessions.ContainsKey(taker.Id))
                {
                     _activeSessions.Remove(taker.Id);
                }
                continue;
            }

            // RE-VALIDATION LOGIC:
            // If we think we have an active session, check if it's still "Active" in the database.
            // If the user closed it manually, we should allow a new alert to be queued if the threat persists.
            if (_activeSessions.ContainsKey(taker.Id))
            {
                var hasActiveDb = await pendingRepo.HasActiveAsync(taker.Id, ct);
                if (!hasActiveDb)
                {
                    _logger.LogInformation("[SENTINEL] Alerta anterior para {Taker} foi encerrado manualmente. Re-avaliando impacto.", taker.Name);
                    _activeSessions.Remove(taker.Id);
                }
            }

            if (!_activeSessions.TryGetValue(taker.Id, out var session) || session.CurrentLevel != targetLevel)
            {
                if (await pendingRepo.HasRecentPendingAsync(taker.Id, targetLevel.ToString(), ct))
                    continue;

                var recentEvents = (await dataService.GetEventsAsync(taker, DateTime.UtcNow.AddMinutes(-10), DateTime.UtcNow, 200.0, "flash", 100, ct)).ToList();
                
                var payload = new AlertPayload {
                    FlashCount = recentEvents.Count,
                    MinDistance = recentEvents.Any() ? recentEvents.Min(e => HaversineKm(taker.Lat, taker.Lon, e.Latitude, e.Longitude)) : 0,
                    CountsSummary = BuildSummary(taker, recentEvents),
                    Impact = impact
                };

                var pending = new PendingAlert {
                    TakerId = taker.Id,
                    TakerName = taker.Name,
                    AlertLevel = targetLevel.ToString(),
                    MessagePayloadJson = JsonSerializer.Serialize(payload),
                    Status = "Pending",
                    DurationMinutes = 60
                };

                // AUTO-APPROVE LOGIC:
                // If high confidence AND lightning jump, send immediately
                if (impact != null && impact.Confidence > 0.8 && impact.LightningJump)
                {
                    _logger.LogInformation("[SENTINEL] AUTO-APPROVE: Alta confiança + Lightning Jump para {Taker}. Enviando WhatsApp...", taker.Name);
                    
                    var wa = scope.ServiceProvider.GetRequiredService<WhatsAppService>();
                    var contactsPath = Path.Combine(Directory.GetCurrentDirectory(), "db/alert_contacts.json");
                    if (File.Exists(contactsPath))
                    {
                        var json = await File.ReadAllTextAsync(contactsPath, ct);
                        var contacts = JsonSerializer.Deserialize<List<AlertContact>>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                        var takerContacts = contacts?.Where(c => c.UnitName.Equals(taker.Name, StringComparison.OrdinalIgnoreCase)).ToList();

                        if (takerContacts != null && takerContacts.Any())
                        {
                            foreach (var contact in takerContacts)
                            {
                                if (!string.IsNullOrEmpty(contact.Phone))
                                {
                                    await wa.SendAlertAsync(contact.Phone, contact.Name, taker.Name, targetLevel.ToString(), payload);
                                }
                            }
                        }
                    }

                    pending.Status = "Active";
                    pending.SentAt = DateTime.UtcNow;
                }

                await pendingRepo.AddAsync(pending, ct);
                _logger.LogInformation("[SENTINEL] Novo alerta {Level} ({Status}) para {Taker}", targetLevel, pending.Status, taker.Name);

                if (session == null) {
                    _activeSessions[taker.Id] = new AlertSession { CurrentLevel = targetLevel, LastUpdateTime = DateTime.UtcNow };
                } else {
                    session.CurrentLevel = targetLevel;
                    session.LastUpdateTime = DateTime.UtcNow;
                }
            }
        }
    }

    private string BuildSummary(ServiceTaker taker, List<LightningEvent> events)
    {
        int c30 = 0, c50 = 0, c100 = 0, c200 = 0;
        foreach (var evt in events)
        {
            var d = HaversineKm(taker.Lat, taker.Lon, evt.Latitude, evt.Longitude);
            if (d <= 30) c30++;
            else if (d <= 50) c50++;
            else if (d <= 100) c100++;
            else if (d <= 200) c200++;
        }
        return $"\n🟠 Até 30km: {c30} \n🟡 Até 50km: {c50} \n🟢 Até 100km: {c100} \n🔵 Até 200km: {c200}";
    }

    private static double HaversineKm(double lat1, double lon1, double lat2, double lon2)
    {
        var R = 6371;
        var dLat = (lat2 - lat1) * Math.PI / 180;
        var dLon = (lon2 - lon1) * Math.PI / 180;
        var a = Math.Sin(dLat / 2) * Math.Sin(dLat / 2) +
                Math.Cos(lat1 * Math.PI / 180) * Math.Cos(lat2 * Math.PI / 180) *
                Math.Sin(dLon / 2) * Math.Sin(dLon / 2);
        var c = 2 * Math.Atan2(Math.Sqrt(a), Math.Sqrt(1 - a));
        return R * c;
    }
}
