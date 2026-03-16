using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using LeadPulse.Application.DTOs;
using LeadPulse.Application.Interfaces;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class OpenAiIntentAnalyzer : IIntentAnalyzer
{
    private readonly HttpClient _httpClient;
    private readonly string _apiKey;
    private readonly string _model;
    private readonly ILogger<OpenAiIntentAnalyzer> _logger;

    public OpenAiIntentAnalyzer(HttpClient httpClient, string apiKey, string model, ILogger<OpenAiIntentAnalyzer> logger)
    {
        _httpClient = httpClient;
        _apiKey = apiKey;
        _model = string.IsNullOrEmpty(model) ? "gpt-4o-mini" : model;
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

        var request = new HttpRequestMessage(HttpMethod.Post, "https://api.openai.com/v1/chat/completions");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);
        request.Content = new StringContent(JsonSerializer.Serialize(requestBody), Encoding.UTF8, "application/json");

        try
        {
            var response = await _httpClient.SendAsync(request);
            response.EnsureSuccessStatusCode();

            var responseJson = await response.Content.ReadAsStringAsync();
            using var doc = JsonDocument.Parse(responseJson);

            var textContent = doc.RootElement
                .GetProperty("choices")[0]
                .GetProperty("message")
                .GetProperty("content")
                .GetString() ?? "";

            return IntentPromptBuilder.ParseResponse(textContent);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "OpenAI intent analysis failed");
            throw;
        }
    }
}
