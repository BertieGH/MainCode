using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using LeadPulse.Application.DTOs;
using LeadPulse.Application.Interfaces;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class ClaudeIntentAnalyzer : IIntentAnalyzer
{
    private readonly HttpClient _httpClient;
    private readonly string _apiKey;
    private readonly string _model;
    private readonly ILogger<ClaudeIntentAnalyzer> _logger;

    public ClaudeIntentAnalyzer(HttpClient httpClient, string apiKey, string model, ILogger<ClaudeIntentAnalyzer> logger)
    {
        _httpClient = httpClient;
        _apiKey = apiKey;
        _model = string.IsNullOrEmpty(model) ? "claude-sonnet-4-6" : model;
        _logger = logger;
    }

    public async Task<IntentAnalysisResult> AnalyzeAsync(string postContent, string platform)
    {
        var prompt = IntentPromptBuilder.Build(postContent, platform);

        var requestBody = new
        {
            model = _model,
            max_tokens = 256,
            messages = new[]
            {
                new { role = "user", content = prompt }
            }
        };

        var request = new HttpRequestMessage(HttpMethod.Post, "https://api.anthropic.com/v1/messages");
        request.Headers.Add("x-api-key", _apiKey);
        request.Headers.Add("anthropic-version", "2023-06-01");
        request.Content = new StringContent(JsonSerializer.Serialize(requestBody), Encoding.UTF8, "application/json");

        try
        {
            var response = await _httpClient.SendAsync(request);
            response.EnsureSuccessStatusCode();

            var responseJson = await response.Content.ReadAsStringAsync();
            using var doc = JsonDocument.Parse(responseJson);

            var textContent = doc.RootElement
                .GetProperty("content")[0]
                .GetProperty("text")
                .GetString() ?? "";

            return IntentPromptBuilder.ParseResponse(textContent);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Claude intent analysis failed");
            throw;
        }
    }
}
