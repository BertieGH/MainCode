using Microsoft.AspNetCore.Mvc;
using Agents;

namespace WebApi.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class ClaudeController : ControllerBase
    {
        private readonly ClaudeClient _client;

        public ClaudeController(ClaudeClient client)
        {
            _client = client;
        }

        [HttpPost("ask")]
        public async Task<IActionResult> Ask([FromBody] PromptRequest req)
        {
            if (string.IsNullOrWhiteSpace(req.Prompt)) return BadRequest("prompt required");
            var response = await _client.AskAsync(req.Prompt, req.Role);
            return Ok(new { raw = response });
        }
    }

    public record PromptRequest(string Prompt, string? Role);
}
