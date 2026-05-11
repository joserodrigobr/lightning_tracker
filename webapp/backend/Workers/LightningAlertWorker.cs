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
    private readonly TimeSpan _checkInterval = TimeSpan.FromMinutes(2);

    private enum AlertLevel { None, Observing, Yellow, Red }

    private class AlertSession
    {
        public AlertLevel CurrentLevel { get; set; } = AlertLevel.None;
        public int MessagesSentInLevel { get; set; } = 0;
        public DateTime InitialAlertTime { get; set; }
        public DateTime LastUpdateTime { get; set; }
        public DateTime LastLightningTime { get; set; }
        public double ClosestDistance { get; set; }
    }

    private readonly Dictionary<int, AlertSession> _activeSessions = new();

    public LightningAlertWorker(ILogger<LightningAlertWorker> logger, IServiceProvider serviceProvider)
    {
        _logger = logger;
        _serviceProvider = serviceProvider;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        await Task.Yield(); // Yield control back to the host startup
        _logger.LogInformation("Sistema Sentinel de Alertas da BlueOcean iniciado e em monitoramento real.");

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await CheckAndAlertAsync(stoppingToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Sentinel: Erro crítico no motor de alerta.");
            }

            await Task.Delay(_checkInterval, stoppingToken);
        }
    }

    private async Task CheckAndAlertAsync(CancellationToken ct)
    {
        using var scope = _serviceProvider.CreateScope();
        var repo = scope.ServiceProvider.GetRequiredService<ServiceTakerRepository>();
        var dataService = scope.ServiceProvider.GetRequiredService<LightningDataService>();
        var nowcastService = scope.ServiceProvider.GetRequiredService<PythonNowcastService>();
        
        var takers = await repo.GetAllAsync(ct);
        var contacts = await LoadContactsAsync(ct);
        if (contacts == null || !contacts.Any()) return;

        // Fetch global nowcast report once per cycle
        var nowcast = await nowcastService.GetNowcastAsync(null, ct);
        _logger.LogInformation("[SENTINEL] Iniciando ciclo de varredura para {TakerCount} tomadores. Nowcast Global obtido.", takers.Count);

        foreach (var taker in takers)
        {
            var takerContacts = contacts.Where(c => c.UnitName.Equals(taker.Name, StringComparison.OrdinalIgnoreCase)).ToList();
            if (!takerContacts.Any()) continue;

            var now = DateTime.UtcNow;
            _logger.LogDebug("[SENTINEL] Analisando taker {TakerName}...", taker.Name);
            // Increased range to 500km to capture 'Observing' events beyond 200km
            var recentEvents = (await dataService.GetEventsAsync(taker, now.AddMinutes(-10), now, 500.0, "flash", 1000, ct)).ToList();
            
            double minDistance = 999;
            if (recentEvents.Any())
            {
                minDistance = recentEvents.Min(e => HaversineKm(taker.Lat, taker.Lon, e.Latitude, e.Longitude));
            }

            AlertLevel targetLevel = GetTargetLevel(minDistance);

            if (_activeSessions.TryGetValue(taker.Id, out var session))
            {
                if (recentEvents.Any())
                {
                    session.LastLightningTime = now;
                    session.ClosestDistance = minDistance;

                    if (targetLevel > session.CurrentLevel)
                    {
                        // Escalation
                        session.CurrentLevel = targetLevel;
                        session.MessagesSentInLevel = 0;
                        var impact = nowcast.Impacts.FirstOrDefault(i => i.TakerId == taker.Id);
                        await SendAlertToContactsAsync(taker, takerContacts, recentEvents, minDistance, targetLevel, impact, ct);
                        session.MessagesSentInLevel++;
                        session.LastUpdateTime = now;
                    }
                    else
                    {
                        // Same level update (or de-escalation)
                        double minutesSinceLastUpdate = (now - session.LastUpdateTime).TotalMinutes;
                        bool shouldUpdate = ShouldUpdateByInterval(session.CurrentLevel, minDistance, minutesSinceLastUpdate);

                        if (shouldUpdate)
                        {
                            var impact = nowcast.Impacts.FirstOrDefault(i => i.TakerId == taker.Id);
                            await SendAlertToContactsAsync(taker, takerContacts, recentEvents, minDistance, session.CurrentLevel, impact, ct);
                            session.MessagesSentInLevel++;
                            session.LastUpdateTime = now;
                        }
                    }
                }
                else 
                {
                    // No recent lightning. Check for 20 minutes inactivity
                    if ((now - session.LastLightningTime).TotalMinutes >= 20)
                    {
                        _logger.LogInformation("Sentinel: Enviando encerramento para {Name} por inatividade.", taker.Name);
                        await SendAlertToContactsAsync(taker, takerContacts, new List<LightningEvent>(), 0, AlertLevel.None, null, ct);
                        _activeSessions.Remove(taker.Id);
                    }
                }
            }
            else if (recentEvents.Any())
            {
                // New alert session
                _logger.LogInformation("Sentinel: NOVO MONITORAMENTO para {Name}", taker.Name);
                
                var newSession = new AlertSession { 
                    InitialAlertTime = now, 
                    LastUpdateTime = now, 
                    LastLightningTime = now,
                    ClosestDistance = minDistance
                };

                var impact = nowcast.Impacts.FirstOrDefault(i => i.TakerId == taker.Id);
                if (targetLevel == AlertLevel.Red)
                {
                    // Exception: Immediate Red
                    await SendAlertToContactsAsync(taker, takerContacts, recentEvents, minDistance, AlertLevel.Observing, impact, ct);
                    await Task.Delay(2000, ct); 
                    await SendAlertToContactsAsync(taker, takerContacts, recentEvents, minDistance, AlertLevel.Red, impact, ct);
                    newSession.CurrentLevel = AlertLevel.Red;
                    newSession.MessagesSentInLevel = 1;
                }
                else 
                {
                    await SendAlertToContactsAsync(taker, takerContacts, recentEvents, minDistance, AlertLevel.Observing, impact, ct);
                    newSession.CurrentLevel = AlertLevel.Observing;
                    newSession.MessagesSentInLevel = 1;
                }

                _activeSessions[taker.Id] = newSession;
            }
        }
    }

    private AlertLevel GetTargetLevel(double distance)
    {
        if (distance <= 100) return AlertLevel.Red;
        if (distance <= 200) return AlertLevel.Yellow;
        if (distance <= 500) return AlertLevel.Observing;
        return AlertLevel.None;
    }

    private bool ShouldUpdateByInterval(AlertLevel level, double minDistance, double minutesSinceUpdate)
    {
        if (level == AlertLevel.Red || minDistance <= 100) return true; // Real-time
        if (level == AlertLevel.Yellow || minDistance <= 200) return minutesSinceUpdate >= 20;
        return minutesSinceUpdate >= 60; // Observing updates
    }

    private async Task<List<AlertContact>?> LoadContactsAsync(CancellationToken ct)
    {
        var contactsPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "db/alert_contacts.json");
        if (!File.Exists(contactsPath)) contactsPath = Path.Combine(Directory.GetCurrentDirectory(), "db/alert_contacts.json");
        if (!File.Exists(contactsPath)) return null;

        var json = await File.ReadAllTextAsync(contactsPath, ct);
        return JsonSerializer.Deserialize<List<AlertContact>>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
    }

    private async Task SendAlertToContactsAsync(ServiceTaker taker, List<AlertContact> contacts, List<LightningEvent> events, double minDistance, AlertLevel level, NowcastImpact? impact, CancellationToken ct)
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
        string countsSummary = $"\n🟠 Até 30km: {c30} \n🟡 Até 50km: {c50} \n🟢 Até 100km: {c100} \n🔵 Até 200km: {c200}";

        foreach (var contact in contacts)
        {
            try
            {
                if (!string.IsNullOrEmpty(contact.Phone))
                    await SendWhatsAppAsync(contact, taker.Name, events.Count, minDistance, countsSummary, level, impact);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Falha ao enviar alerta para {Contact}", contact.Name);
            }
        }
    }

    private async Task SendWhatsAppAsync(AlertContact contact, string unitName, int count, double minDistance, string countsSummary, AlertLevel level, NowcastImpact? impact)
    {
        var instanceId = "3F2C681BEBCAF1933F5DEAAA29470FA9"; 
        var instanceToken = "6D478E447558779AE85FEEF8";
        var clientToken = "F69b60f2b6f024139a33e5d911459bc38S";

        using var httpClient = new HttpClient();
        httpClient.DefaultRequestHeaders.Add("client-token", clientToken);

        var cleanPhone = new string(contact.Phone.Where(char.IsDigit).ToArray());
        if (!cleanPhone.StartsWith("55")) cleanPhone = "55" + cleanPhone;

        string messageText = level switch {
            AlertLevel.Observing => GetObservingTemplate(contact.Name, unitName),
            AlertLevel.Yellow => GetYellowTemplate(contact.Name, unitName, count, minDistance, countsSummary, impact),
            AlertLevel.Red => GetRedTemplate(contact.Name, unitName, count, minDistance, countsSummary, impact),
            AlertLevel.None => GetGreenTemplate(contact.Name, unitName),
            _ => ""
        };

        var payload = new { phone = cleanPhone, message = messageText };
        var url = $"https://api.z-api.io/instances/{instanceId}/token/{instanceToken}/send-text";
        
        var response = await httpClient.PostAsJsonAsync(url, payload);
        if (response.IsSuccessStatusCode)
            _logger.LogInformation("WhatsApp {Level} enviado para {Phone}.", level, contact.Phone);
        else
            _logger.LogError("Erro Z-API ({Code}): {Msg}", response.StatusCode, await response.Content.ReadAsStringAsync());
    }

    private string GetObservingTemplate(string contactName, string unitName)
    {
        return $@"⚠️ *SENTINEL BLUEOCEAN* ⚠️

Olá {contactName}! Sou o *Sentinel*, sistema de monitoramento da BLUEOCEAN.

Estamos observando uma intensificação de tempestade na região da unidade: *{unitName}*.

Nossa equipe está em vigilância. Caso o tempo mude ou a atividade se aproxime, enviaremos novos alertas imediatamente.

📍 Acompanhe ao vivo: http://nowcast.blueocean.com";
    }

    private string GetYellowTemplate(string contactName, string unitName, int count, double minDistance, string countsSummary, NowcastImpact? impact)
    {
        string statusText = impact != null
            ? $"\n\n💡 *Previsão Sentinel:* Tempestade se deslocando a {impact.VelocityKmh:F0} km/h na direção {impact.BearingLabel}. Chegada estimada em *{impact.EtaMinutes} minutos* no raio de {impact.RingKm}km."
            : "\n\n💡 *Status:* Monitoramento ativo. Enviaremos atualizações caso a atividade se intensifique.";
        
        return $@"🟡 *ALERTA AMARELO*

Olá {contactName}! 
**Foram detectados raios a {minDistance:F1} km de distância da unidade {unitName}.**

📊 *Informações de proximidade:* {countsSummary}

⛈️ *Total de raios:* {count}
📍 *Raio mais próximo:* {minDistance:F1} km{statusText}

📍 Veja no mapa: http://nowcast.blueocean.com

Continuaremos enviando atualizações conforme a proximidade dos eventos.";
    }

    private string GetRedTemplate(string contactName, string unitName, int count, double minDistance, string countsSummary, NowcastImpact? impact)
    {
        string prediction = impact != null
            ? $"\n\n💡 *Previsão Sentinel:* Impacto iminente. Tempestade a {impact.VelocityKmh:F0} km/h em direção à unidade. ETA: *{impact.EtaMinutes} minutos*."
            : "";

        return $@"🔴 *ALERTA VERMELHO*

Olá {contactName}! 
**Foram detectados raios a {minDistance:F1} km de distância da unidade {unitName}.**

📊 *Informações de proximidade:* {countsSummary}

⛈️ *Total de raios:* {count}
📍 *Raio mais próximo:* {minDistance:F1} km{prediction}

📍 Veja no mapa: http://nowcast.blueocean.com

*ATENÇÃO:* Procure abrigo seguro e evite áreas abertas.";
    }

    private string GetGreenTemplate(string contactName, string unitName)
    {
        return $@"✅ *ALERTA VERDE - BLUEOCEAN* ✅

Condições normalizadas. Sem registro de relâmpagos na última hora para as proximidades da unidade *{unitName}*.";
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

    private class AlertContact
    {
        public string Name { get; set; } = "";
        public string UnitName { get; set; } = "";
        public string Email { get; set; } = "";
        public string Phone { get; set; } = "";
    }
}


