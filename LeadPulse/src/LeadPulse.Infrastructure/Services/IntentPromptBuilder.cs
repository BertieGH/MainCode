using System.Text.Json;
using System.Text.RegularExpressions;
using LeadPulse.Application.DTOs;

namespace LeadPulse.Infrastructure.Services;

public static class IntentPromptBuilder
{
    public static string Build(string postContent, string platform)
    {
        return "You are an insurance lead scoring AI. Analyze this social media post and determine:\n" +
            "1. Intent Score (0-100): How likely is this person looking for insurance services?\n" +
            "2. Category: Which insurance type? (Auto, Home, Life, Health, Commercial, General, None)\n" +
            "3. Sentiment: (Positive, Negative, Neutral, Urgent)\n" +
            "4. Summary: One sentence describing the lead potential.\n" +
            "5. Phone: Extract any phone number mentioned in the post (null if none found)\n" +
            "6. Email: Extract any email address mentioned in the post (null if none found)\n\n" +
            $"Post from {platform}:\n\"{postContent}\"\n\n" +
            "Respond ONLY in JSON: {\"intentScore\":N,\"category\":\"...\",\"sentiment\":\"...\",\"summary\":\"...\",\"phone\":null,\"email\":null}";
    }

    public static IntentAnalysisResult ParseResponse(string responseText)
    {
        // Extract JSON from response (may have markdown fences or extra text)
        var jsonMatch = Regex.Match(responseText, @"\{[^{}]*""intentScore""[^{}]*\}", RegexOptions.Singleline);
        if (!jsonMatch.Success)
        {
            return new IntentAnalysisResult
            {
                IntentScore = 0,
                IntentCategory = "None",
                Sentiment = "Neutral",
                Summary = "AI response could not be parsed."
            };
        }

        try
        {
            using var doc = JsonDocument.Parse(jsonMatch.Value);
            var root = doc.RootElement;

            string? phone = null;
            string? email = null;
            if (root.TryGetProperty("phone", out var phoneProp) && phoneProp.ValueKind == JsonValueKind.String)
                phone = phoneProp.GetString();
            if (root.TryGetProperty("email", out var emailProp) && emailProp.ValueKind == JsonValueKind.String)
                email = emailProp.GetString();

            return new IntentAnalysisResult
            {
                IntentScore = Math.Clamp(root.GetProperty("intentScore").GetInt32(), 0, 100),
                IntentCategory = root.GetProperty("category").GetString() ?? "None",
                Sentiment = root.GetProperty("sentiment").GetString() ?? "Neutral",
                Summary = root.GetProperty("summary").GetString() ?? "",
                Phone = phone,
                Email = email
            };
        }
        catch
        {
            return new IntentAnalysisResult
            {
                IntentScore = 0,
                IntentCategory = "None",
                Sentiment = "Neutral",
                Summary = "AI response could not be parsed."
            };
        }
    }
}
