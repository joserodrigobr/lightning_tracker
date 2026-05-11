using System.Net.Http.Json;
using System.Text.Json;
using LightningTracker.WebApi.Models;

namespace LightningTracker.WebApi.Services;

public sealed class WhatsAppService
{
    private readonly ILogger<WhatsAppService> _logger;
    private const string InstanceId = "3F2C681BEBCAF1933F5DEAAA29470FA9";
    private const string InstanceToken = "6D478E447558779AE85FEEF8";
    private const string ClientToken = "F69b60f2b6f024139a33e5d911459bc38S";

    public WhatsAppService(ILogger<WhatsAppService> logger)
    {
        _logger = logger;
    }

    public async Task SendAlertAsync(string phone, string contactName, string unitName, string alertLevel, AlertPayload payload)
    {
        string messageText = alertLevel.ToUpper() switch
        {
            "OBSERVING" => GetObservingTemplate(contactName, unitName),
            "YELLOW" => GetYellowTemplate(contactName, unitName, payload.FlashCount, payload.MinDistance, payload.CountsSummary, payload.Impact),
            "RED" => GetRedTemplate(contactName, unitName, payload.FlashCount, payload.MinDistance, payload.CountsSummary, payload.Impact),
            "NONE" => GetGreenTemplate(contactName, unitName),
            _ => ""
        };

        await SendMessageAsync(phone, messageText);
    }

    public async Task SendUpdateAsync(string phone, string contactName, string unitName, string alertLevel, int duration, AlertPayload payload)
    {
        var levelLabel = alertLevel.ToUpper() == "RED" ? "🔴 VERMELHO" : "🟡 AMARELO";
        var messageText = $@"🔄 *ATUALIZAÇÃO DE ALERTA - SENTINELA*

Olá {contactName}! 
O status da unidade *{unitName}* foi atualizado para nível {levelLabel}.

📊 *Resumo Atual:*
⚡ Raios detectados: {payload.FlashCount}
📍 Distância mínima: {payload.MinDistance:F1} km
⏱️ Duração prevista: {duration} minutos

📍 Acompanhe: http://nowcast.blueocean.com";

        await SendMessageAsync(phone, messageText);
    }

    public async Task SendResolvedAsync(string phone, string contactName, string unitName)
    {
        var messageText = $@"✅ *ALERTA ENCERRADO - SENTINELA*

Olá {contactName}! 
As condições meteorológicas para a unidade *{unitName}* foram normalizadas e o monitoramento intensivo foi encerrado.

Desejamos um bom trabalho a todos.";

        await SendMessageAsync(phone, messageText);
    }

    private async Task SendMessageAsync(string phone, string messageText)
    {
        if (string.IsNullOrEmpty(messageText)) return;
        var cleanPhone = new string(phone.Where(char.IsDigit).ToArray());
        if (!cleanPhone.StartsWith("55")) cleanPhone = "55" + cleanPhone;

        try {
            using var httpClient = new HttpClient();
            httpClient.DefaultRequestHeaders.Add("client-token", ClientToken);

            var data = new { phone = cleanPhone, message = messageText };
            var url = $"https://api.z-api.io/instances/{InstanceId}/token/{InstanceToken}/send-text";

            var response = await httpClient.PostAsJsonAsync(url, data);
            if (response.IsSuccessStatusCode)
                _logger.LogInformation("WhatsApp enviado para {Phone}.", phone);
            else
                _logger.LogError("Erro Z-API ({Code}): {Msg}", response.StatusCode, await response.Content.ReadAsStringAsync());
        } catch (Exception ex) {
            _logger.LogError(ex, "Falha crítica ao enviar WhatsApp.");
        }
    }

    private string GetObservingTemplate(string contactName, string unitName) =>
        $@"⚠️ *SENTINELA BLUEOCEAN* ⚠️

Olá {contactName}! Sou o *Sentinela*, sistema de monitoramento da BLUEOCEAN.

Estamos observando uma intensificação de tempestade na região da unidade: *{unitName}*.

Nossa equipe está em vigilância. Caso o tempo mude ou a atividade se aproxime, enviaremos novos alertas imediatamente.

📍 Acompanhe ao vivo: http://nowcast.blueocean.com";

    private string GetYellowTemplate(string contactName, string unitName, int count, double minDistance, string countsSummary, NowcastImpact? impact)
    {
        string statusText = impact != null
            ? $"\n\n💡 *Previsão Sentinela:* Tempestade se deslocando a {impact.VelocityKmh:F0} km/h na direção {impact.BearingLabel}. Chegada estimada em *{impact.EtaMinutes} minutos* no raio de {impact.RingKm}km."
            : "\n\n💡 *Status:* Monitoramento ativo. Enviaremos atualizações caso a atividade se intensifique.";

        return $@"🟡 *ALERTA AMARELO - SENTINELA*

Olá {contactName}! 
**Foram detectados raios a {minDistance:F1} km de distância da unidade {unitName}.**

📊 *Informações de proximidade:* {countsSummary}

⛈️ *Total de raios:* {count}
📍 *Raio mais próximo:* {minDistance:F1} km{statusText}

📍 Veja no mapa: http://nowcast.blueocean.com";
    }

    private string GetRedTemplate(string contactName, string unitName, int count, double minDistance, string countsSummary, NowcastImpact? impact)
    {
        string prediction = impact != null
            ? $"\n\n💡 *Previsão Sentinela:* Impacto iminente. Tempestade a {impact.VelocityKmh:F0} km/h em direção à unidade. ETA: *{impact.EtaMinutes} minutos*."
            : "";

        return $@"🔴 *ALERTA VERMELHO - SENTINELA*

Olá {contactName}! 
**Foram detectados raios a {minDistance:F1} km de distância da unidade {unitName}.**

📊 *Informações de proximidade:* {countsSummary}

⛈️ *Total de raios:* {count}
📍 *Raio mais próximo:* {minDistance:F1} km{prediction}

📍 Veja no mapa: http://nowcast.blueocean.com

*ATENÇÃO:* Procure abrigo seguro e evite áreas abertas.";
    }

    private string GetGreenTemplate(string contactName, string unitName) =>
        $@"✅ *ALERTA VERDE - SENTINELA* ✅

Condições normalizadas. Sem registro de relâmpagos na última hora para as proximidades da unidade *{unitName}*.";
}
