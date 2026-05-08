using System.Net;
using System.Net.Mail;
using LightningTracker.WebApi.Data;
using LightningTracker.WebApi.Services;

namespace LightningTracker.WebApi.Workers;

public class LightningAlertWorker : BackgroundService
{
    private readonly ILogger<LightningAlertWorker> _logger;
    private readonly IServiceProvider _serviceProvider;
    private readonly TimeSpan _checkInterval = TimeSpan.FromMinutes(2);
    
    // Memory cache to avoid spamming alerts (15min debounce per unit)
    private readonly Dictionary<int, DateTime> _lastAlertSent = new();

    public LightningAlertWorker(ILogger<LightningAlertWorker> logger, IServiceProvider serviceProvider)
    {
        _logger = logger;
        _serviceProvider = serviceProvider;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("Sistema Sentinel de Alertas da BlueOcean iniciado e em monitoramento real.");

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await CheckAndAlertAsync(stoppingToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Erro no motor de alerta.");
            }

            await Task.Delay(_checkInterval, stoppingToken);
        }
    }

    private async Task CheckAndAlertAsync(CancellationToken ct)
    {
        using var scope = _serviceProvider.CreateScope();
        var repo = scope.ServiceProvider.GetRequiredService<ServiceTakerRepository>();
        var dataService = scope.ServiceProvider.GetRequiredService<LightningDataService>();
        
        // Hardcoded target: Porto Belém (ID usually depends on DB, but we fetch all and filter by name if needed)
        var takers = await repo.GetAllAsync(ct);
        var targetTaker = takers.FirstOrDefault(t => t.Name.Contains("Porto Belém"));

        if (targetTaker == null) return;

        // Debounce: 10 minutes between alerts
        if (_lastAlertSent.TryGetValue(targetTaker.Id, out var lastTime) && 
            DateTime.UtcNow - lastTime < TimeSpan.FromMinutes(10))
        {
            return;
        }

        // Check for lightning in last 5 minutes within 200km
        var startUtc = DateTime.UtcNow.AddMinutes(-5);
        var endUtc = DateTime.UtcNow;
        
        var events = await dataService.GetEventsAsync(targetTaker, startUtc, endUtc, 200.0, "flash", 100, ct);

        if (events.Any())
        {
            _logger.LogInformation("Relâmpago detectado perto de {Name}! Calculando distâncias...", targetTaker.Name);
            
            // Calculate counts per ring
            int c30 = 0, c50 = 0, c100 = 0, c200 = 0;
            foreach (var evt in events)
            {
                var d = HaversineKm(targetTaker.Lat, targetTaker.Lon, evt.Latitude, evt.Longitude);
                if (d <= 30) c30++;
                else if (d <= 50) c50++;
                else if (d <= 100) c100++;
                else if (d <= 200) c200++;
            }

            var countsStr = $@"
🟠 Até 30km: {c30}
🟡 Até 50km: {c50}
🟢 Até 100km: {c100}
🔵 Até 200km: {c200}"; 
            
            // Read contacts from JSON table
            var contactsPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "db/alert_contacts.json");
            if (!File.Exists(contactsPath)) {
                // Fallback to project root for dev
                contactsPath = Path.Combine(Directory.GetCurrentDirectory(), "db/alert_contacts.json");
            }

            if (File.Exists(contactsPath))
            {
                var json = await File.ReadAllTextAsync(contactsPath, ct);
                var options = new System.Text.Json.JsonSerializerOptions { PropertyNameCaseInsensitive = true };
                var contacts = System.Text.Json.JsonSerializer.Deserialize<List<AlertContact>>(json, options);
                
                if (contacts != null)
                {
                    foreach (var contact in contacts)
                    {
                        // Check if contact is subscribed to this unit
                        if (targetTaker.Name.Contains(contact.Unit, StringComparison.OrdinalIgnoreCase))
                        {
                            if (!string.IsNullOrWhiteSpace(contact.Email))
                                await SendEmailAlert(targetTaker.Name, contact.Name, contact.Email, countsStr);
                            
                            if (!string.IsNullOrWhiteSpace(contact.Whatsapp))
                                await SendWhatsAppAlert(targetTaker.Name, contact.Name, contact.Whatsapp, countsStr);
                        }
                    }
                }
            }
            
            _lastAlertSent[targetTaker.Id] = DateTime.UtcNow;
        }
    }

    private static double HaversineKm(double lat1, double lon1, double lat2, double lon2)
    {
        var dLat = (lat2 - lat1) * Math.PI / 180.0;
        var dLon = (lon2 - lon1) * Math.PI / 180.0;
        var a = Math.Sin(dLat / 2) * Math.Sin(dLat / 2) +
                Math.Cos(lat1 * Math.PI / 180.0) * Math.Cos(lat2 * Math.PI / 180.0) *
                Math.Sin(dLon / 2) * Math.Sin(dLon / 2);
        var c = 2 * Math.Atan2(Math.Sqrt(a), Math.Sqrt(1 - a));
        return 6371.0 * c;
    }

    private class AlertContact
    {
        public string Name { get; set; } = "";
        public string Unit { get; set; } = "";
        public string Email { get; set; } = "";
        public string Whatsapp { get; set; } = "";
    }

    private async Task SendWhatsAppAlert(string unitName, string contactName, string phoneNumber, string countsSummary)
    {
        if (string.IsNullOrWhiteSpace(phoneNumber)) return;
        try
        {
            // CONFIGURAÇÃO Z-API
            var instanceId = "3F2C681BEBCAF1933F5DEAAA29470FA9"; 
            var instanceToken = "6D478E447558779AE85FEEF8";
            var clientToken = "F69b60f2b6f024139a33e5d911459bc38S";
            
            using var client = new HttpClient();
            client.DefaultRequestHeaders.Add("client-token", clientToken);

            // 1. Verificar Status da Instância
            var statusUrl = $"https://api.z-api.io/instances/{instanceId}/token/{instanceToken}/status";
            var statusRes = await client.GetAsync(statusUrl);
            var statusJson = await statusRes.Content.ReadAsStringAsync();
            _logger.LogInformation("STATUS Z-API: {Status}", statusJson);

            // 2. Enviar Mensagem
            var url = $"https://api.z-api.io/instances/{instanceId}/token/{instanceToken}/send-text";
            
            // Clean phone number
            var cleanPhone = new string(phoneNumber.Where(char.IsDigit).ToArray());
            if (!cleanPhone.StartsWith("55")) cleanPhone = "55" + cleanPhone;

            var payload = new
            {
                phone = cleanPhone,
                message = $@"⚠️ *ALERTA BLUEOCEAN* ⚠️

Olá {contactName}! Me chamo Sentinel, sou o alerta automático.

Há relâmpagos detectados perto da unidade: *{unitName}*.

📊 *Resumo de proximidade (últimos 5 min):*{countsSummary}

📍 Acompanhe agora: http://nowcast.oceanblue.com
Entraremos em contato com mais atualizações."
            };

            var response = await client.PostAsJsonAsync(url, payload);
            var resultBody = await response.Content.ReadAsStringAsync();
            
            if (response.IsSuccessStatusCode)
                _logger.LogInformation("WHATSAPP ENVIADO! Resposta: {Body}", resultBody);
            else
                _logger.LogError("FALHA WHATSAPP: {Code} - {Msg}", response.StatusCode, resultBody);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Erro ao disparar WhatsApp via Z-API.");
        }
    }

    private async Task SendEmailAlert(string unitName, string contactName, string email, string countsSummary)
    {
        if (string.IsNullOrWhiteSpace(email)) return;
        try
        {
            // CONFIGURAÇÃO DO REMETENTE (Quem vai enviar o e-mail)
            var smtpHost = "smtp.office365.com";         // Servidor Office 365 / Microsoft
            var smtpPort = 587;                          // Porta para STARTTLS
            var smtpUser = "samuel.amorim@BRBlueocean.com"; // Seu e-mail corporativo
            var smtpPass = "P&593209307730ay";           // Senha de Aplicativo ou senha da conta

            using var client = new SmtpClient(smtpHost, smtpPort)
            {
                Credentials = new NetworkCredential(smtpUser, smtpPass),
                EnableSsl = true
            };

            var message = new MailMessage
            {
                From = new MailAddress(smtpUser, "BlueOcean Alerta"),
                Subject = $"⚠️ ALERTA: Relâmpagos em {unitName}",
                Body = $@"Olá {contactName}! 

Sou o alerta automático da BLUOCEAN! 
Há relâmpagos detectados perto da sua unidade de serviço: {unitName}. 

Resumo de proximidade (últimos 5 min):
{countsSummary}

Acompanhe em tempo real em: http://nowcast.oceanblue.com
Entraremos em contato para mais atualizações.

Atenciosamente,
Sistema Sentinel BlueOcean",
                IsBodyHtml = false
            };

            message.To.Add(email);
            
            await client.SendMailAsync(message);
            _logger.LogInformation("E-MAIL ENVIADO COM SUCESSO para {Email}.", email);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Falha ao enviar e-mail de alerta.");
        }
    }
}
