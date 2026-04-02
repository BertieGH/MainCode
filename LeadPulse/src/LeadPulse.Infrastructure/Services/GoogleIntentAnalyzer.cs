using System.Text;
using System.Text.Json;
using LeadPulse.Application.DTOs;
using LeadPulse.Application.Interfaces;
using Microsoft.Extensions.Logging;

namespace LeadPulse.Infrastructure.Services;

public class GoogleIntentAnalyzer : IIntentAnalyzer
{
    private readonly HttpClient _httpClient;
    private readonly string _apiKey;
    private readonly string _model;
    private readonly ILogger<GoogleIntentAnalyzer> _logger;

    public GoogleIntentAnalyzer(HttpClient httpClient, string apiKey, string model, ILogger<GoogleIntentAnalyzer> logger)
    {
        _httpClient = httpClient;
        _apiKey = apiKey;
        _model = string.IsNullOrEmpty(model) ? "gemini-2.0-flash" : model;
        _logger = logger;
    }

    public async Task<IntentAnalysisResult> AnalyzeAsync(string postContent, string platform)
    {
        var prompt = IntentPromptBuilder.Build(postContent, platform);

        var requestBody = new
        {
            contents = new[]
            {
                new
                {
                    parts = new[]
                    {
                        new { text = prompt }
                    }
                }
            },
            generationConfig = new
            {
                maxOutputTokens = 256,
                temperature = 0.1
            }
        };

        var url = $"https://generativelanguage.googleapis.com/v1beta/models/{_model}:generateContent?key={_apiKey}";

        var request = new HttpRequestMessage(HttpMethod.Post, url);
        request.Content = new StringContent(JsonSerializer.Serialize(requestBody), Encoding.UTF8, "application/json");

        try
        {
            var response = await _httpClient.SendAsync(request);
            var responseJson = await response.Content.ReadAsStringAsync();

            if (!response.IsSuccessStatusCode)
            {
                _logger.LogError("Google AI API error {Status}: {Body}", response.StatusCode, responseJson);
                var errMsg = response.StatusCode.ToString();
                try
                {
                    using var errDoc = JsonDocument.Parse(responseJson);
                    if (errDoc.RootElement.TryGetProperty("error", out var errObj) && errObj.TryGetProperty("message", out var msg))
                        errMsg = msg.GetString() ?? errMsg;
                } catch { }
                throw new HttpRequestException($"Google AI: {errMsg}", null, response.StatusCode);
            }

            using var doc = JsonDocument.Parse(responseJson);

            var textContent = doc.RootElement
                .GetProperty("candidates")[0]
                .GetProperty("content")
                .GetProperty("parts")[0]
                .GetProperty("text")
                .GetString() ?? "";

            return IntentPromptBuilder.ParseResponse(textContent);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Google AI intent analysis failed");
            throw;
        }
    }
}
