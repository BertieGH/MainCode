# .NET + SQL app scaffold with Claude agent (VS Code)

This workspace provides a minimal starter scaffold to develop a .NET Web API backed by SQL and a simple Claude agent client for Business Analysis (BA) and QA workflows.

Prerequisites
- Install .NET SDK (recommended .NET 8 or 7): https://dotnet.microsoft.com/
- Install VS Code and the recommended extensions (see .vscode/extensions.json)
- A SQL engine: SQL Server, Azure SQL, or use SQLite for local testing
- Set environment variables: `CLAUDE_API_KEY` and optionally `CLAUDE_API_URL`

Quick start

1. Open workspace in VS Code.
2. Restore and build:

```bash
dotnet build src\WebApi
```

3. Run the Web API:

```bash
dotnet run --project src\WebApi
```

4. Example HTTP request to the Claude agent endpoint:

```bash
curl -X POST http://localhost:5000/api/claude/ask -H "Content-Type: application/json" -d '{"prompt":"Summarize the following requirements...","role":"ba"}'
```

Files added
- `src/WebApi` : minimal ASP.NET Core Web API
- `src/Agents/ClaudeClient.cs` : minimal C# HTTP client wrapper to call a Claude-compatible API
- `sql/init.sql` : example schema and sample data
- `.vscode/` : recommended extensions, tasks and launch configuration

Next steps
- Replace the placeholder prompt templates in `docs/` (if added) with your BA and QA prompts
- Hook up a production vector DB and RAG pipeline if you need retrieval
- Add tests and CI that run generated tests for QA workflows
