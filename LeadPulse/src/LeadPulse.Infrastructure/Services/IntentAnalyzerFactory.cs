using LeadPulse.Application.Interfaces;
using LeadPulse.Domain.Entities.Tenant;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class IntentAnalyzerFactory
{
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IEncryptionService _encryptionService;
    private readonly ILoggerFactory _loggerFactory;

    public IntentAnalyzerFactory(
        IHttpClientFactory httpClientFactory,
        IEncryptionService encryptionService,
        ILoggerFactory loggerFactory)
    {
        _httpClientFactory = httpClientFactory;
        _encryptionService = encryptionService;
        _loggerFactory = loggerFactory;
    }

    public IIntentAnalyzer Create(AiSettings? settings, int tenantId)
    {
        var provider = settings?.AiProvider ?? "Local";

        return provider switch
        {
            "Claude" => CreateClaude(settings!, tenantId),
            "OpenAI" => CreateOpenAi(settings!, tenantId),
            "Google" => CreateGoogle(settings!, tenantId),
            _ => new LocalIntentAnalyzer()
        };
    }

    private ClaudeIntentAnalyzer CreateClaude(AiSettings settings, int tenantId)
    {
        var apiKey = string.IsNullOrEmpty(settings.EncryptedApiKey)
            ? throw new InvalidOperationException("Claude API key not configured")
            : _encryptionService.Decrypt(settings.EncryptedApiKey, tenantId);

        return new ClaudeIntentAnalyzer(
            _httpClientFactory.CreateClient(),
            apiKey,
            settings.AiModel ?? "claude-sonnet-4-6",
            _loggerFactory.CreateLogger<ClaudeIntentAnalyzer>());
    }

    private OpenAiIntentAnalyzer CreateOpenAi(AiSettings settings, int tenantId)
    {
        var apiKey = string.IsNullOrEmpty(settings.EncryptedApiKey)
            ? throw new InvalidOperationException("OpenAI API key not configured")
            : _encryptionService.Decrypt(settings.EncryptedApiKey, tenantId);

        return new OpenAiIntentAnalyzer(
            _httpClientFactory.CreateClient(),
            apiKey,
            settings.AiModel ?? "gpt-4o-mini",
            _loggerFactory.CreateLogger<OpenAiIntentAnalyzer>());
    }

    private GoogleIntentAnalyzer CreateGoogle(AiSettings settings, int tenantId)
    {
        var apiKey = string.IsNullOrEmpty(settings.EncryptedApiKey)
            ? throw new InvalidOperationException("Google AI API key not configured")
            : _encryptionService.Decrypt(settings.EncryptedApiKey, tenantId);

        return new GoogleIntentAnalyzer(
            _httpClientFactory.CreateClient(),
            apiKey,
            settings.AiModel ?? "gemini-2.0-flash",
            _loggerFactory.CreateLogger<GoogleIntentAnalyzer>());
    }
}
