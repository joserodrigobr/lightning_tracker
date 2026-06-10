using System.Net;
using System.Net.Mail;
using LightningTracker.WebApi.Models;

namespace LightningTracker.WebApi.Services;

public sealed class DataRequestEmailService
{
    private readonly IConfiguration _configuration;
    private readonly ILogger<DataRequestEmailService> _logger;

    public DataRequestEmailService(IConfiguration configuration, ILogger<DataRequestEmailService> logger)
    {
        _configuration = configuration;
        _logger = logger;
    }

    public async Task<DataRequestEmailResult> SendAsync(
        DataRequestEmailRequest request,
        DateTime startTime,
        DateTime endTime,
        CancellationToken cancellationToken)
    {
        var options = GetOptions();
        var missing = GetMissingConfiguration(options).ToArray();
        if (missing.Length > 0)
        {
            _logger.LogError("Configuracao SMTP incompleta para requisicao de dados. Faltando: {Missing}", string.Join(", ", missing));
            return new DataRequestEmailResult(false, $"Envio de e-mail nao configurado. Faltando: {string.Join(", ", missing)}.");
        }

        using var message = new MailMessage
        {
            From = new MailAddress(options.From!),
            Subject = $"Requisicao de dados - {request.TakerName}",
            Body = BuildBody(request, startTime, endTime),
            IsBodyHtml = false
        };

        message.To.Add(options.To!);
        message.ReplyToList.Add(new MailAddress(request.Email, request.Name));

        using var smtp = new SmtpClient(options.Host!, options.Port)
        {
            DeliveryMethod = SmtpDeliveryMethod.Network,
            EnableSsl = options.EnableSsl,
            Timeout = 30000,
            UseDefaultCredentials = false,
            Credentials = new NetworkCredential(options.Username, options.Password)
        };

        try
        {
            await smtp.SendMailAsync(message, cancellationToken);
            _logger.LogInformation(
                "Requisicao de dados enviada por e-mail. TakerId={TakerId}, TakerName={TakerName}, Email={Email}",
                request.TakerId,
                request.TakerName,
                request.Email);

            return new DataRequestEmailResult(true, "Solicitacao enviada com sucesso.");
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (SmtpException ex) when (IsAuthenticationError(ex))
        {
            _logger.LogError(ex, "Falha de autenticacao SMTP ao enviar requisicao de dados.");
            return new DataRequestEmailResult(false, "O Gmail recusou as credenciais SMTP. Use uma senha de app valida da conta remetente e confirme se a verificacao em duas etapas esta ativa.");
        }
        catch (SmtpException ex)
        {
            _logger.LogError(ex, "Falha SMTP ao enviar requisicao de dados.");
            return new DataRequestEmailResult(false, $"Falha no servidor SMTP: {ex.StatusCode}.");
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Falha ao enviar requisicao de dados por e-mail.");
            return new DataRequestEmailResult(false, "Nao foi possivel enviar a solicitacao por e-mail no momento.");
        }
    }

    private DataRequestEmailOptions GetOptions()
    {
        var section = _configuration.GetSection("DataRequestEmail");
        return new DataRequestEmailOptions
        {
            Host = GetEnvOrConfig("LIGHTNING_TRACKER_SMTP_HOST", section["Host"])?.Trim(),
            Port = GetIntEnvOrConfig("LIGHTNING_TRACKER_SMTP_PORT", section["Port"], 587),
            Username = GetEnvOrConfig("LIGHTNING_TRACKER_SMTP_USERNAME", section["Username"])?.Trim(),
            Password = NormalizePassword(
                GetEnvOrConfig("LIGHTNING_TRACKER_SMTP_HOST", section["Host"]),
                GetEnvOrConfig("LIGHTNING_TRACKER_SMTP_PASSWORD", section["Password"])),
            From = GetEnvOrConfig("LIGHTNING_TRACKER_SMTP_FROM", section["From"])?.Trim(),
            To = GetEnvOrConfig("LIGHTNING_TRACKER_DATA_REQUEST_TO", section["To"])?.Trim(),
            EnableSsl = GetBoolEnvOrConfig("LIGHTNING_TRACKER_SMTP_ENABLE_SSL", section["EnableSsl"], true)
        };
    }

    private static bool IsAuthenticationError(SmtpException ex)
    {
        var message = ex.Message;
        return message.Contains("5.7.8", StringComparison.OrdinalIgnoreCase)
            || message.Contains("5.7.0", StringComparison.OrdinalIgnoreCase)
            || message.Contains("Authentication", StringComparison.OrdinalIgnoreCase)
            || message.Contains("authenticated", StringComparison.OrdinalIgnoreCase)
            || message.Contains("Password not accepted", StringComparison.OrdinalIgnoreCase);
    }

    private static string? NormalizePassword(string? host, string? password)
    {
        if (string.IsNullOrWhiteSpace(password))
            return password;

        var trimmed = password.Trim();
        if (host?.Trim().Equals("smtp.gmail.com", StringComparison.OrdinalIgnoreCase) == true)
            return string.Concat(trimmed.Where(c => !char.IsWhiteSpace(c)));

        return trimmed;
    }

    private static IEnumerable<string> GetMissingConfiguration(DataRequestEmailOptions options)
    {
        if (string.IsNullOrWhiteSpace(options.Host)) yield return "LIGHTNING_TRACKER_SMTP_HOST";
        if (options.Port <= 0) yield return "LIGHTNING_TRACKER_SMTP_PORT";
        if (string.IsNullOrWhiteSpace(options.Username)) yield return "LIGHTNING_TRACKER_SMTP_USERNAME";
        if (string.IsNullOrWhiteSpace(options.Password)) yield return "LIGHTNING_TRACKER_SMTP_PASSWORD";
        if (string.IsNullOrWhiteSpace(options.From)) yield return "LIGHTNING_TRACKER_SMTP_FROM";
        if (string.IsNullOrWhiteSpace(options.To)) yield return "LIGHTNING_TRACKER_DATA_REQUEST_TO";
    }

    private static string BuildBody(DataRequestEmailRequest request, DateTime startTime, DateTime endTime)
    {
        return $"""
        Nova requisicao de dados recebida.

        Solicitante: {request.Name}
        E-mail para retorno: {request.Email}

        Tomador: {request.TakerName}
        ID do tomador: {request.TakerId}

        Periodo inicial: {startTime:yyyy-MM-dd HH:mm}
        Periodo final: {endTime:yyyy-MM-dd HH:mm}
        Intervalo acumulado: {request.IntervalMinutes} minuto(s)
        Tipo de dado: {request.DataType}

        Prazo informado ao usuario: 24h para retorno por e-mail.
        """;
    }

    private static string? GetEnvOrConfig(string envName, string? configValue)
    {
        var envValue = Environment.GetEnvironmentVariable(envName);
        return string.IsNullOrWhiteSpace(envValue) ? configValue : envValue;
    }

    private static int GetIntEnvOrConfig(string envName, string? configValue, int defaultValue)
    {
        var value = GetEnvOrConfig(envName, configValue);
        return int.TryParse(value, out var parsed) ? parsed : defaultValue;
    }

    private static bool GetBoolEnvOrConfig(string envName, string? configValue, bool defaultValue)
    {
        var value = GetEnvOrConfig(envName, configValue);
        return bool.TryParse(value, out var parsed) ? parsed : defaultValue;
    }
}
