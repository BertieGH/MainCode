# Build stage
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

COPY src/LeadPulse.Domain/LeadPulse.Domain.csproj src/LeadPulse.Domain/
COPY src/LeadPulse.Application/LeadPulse.Application.csproj src/LeadPulse.Application/
COPY src/LeadPulse.Infrastructure/LeadPulse.Infrastructure.csproj src/LeadPulse.Infrastructure/
COPY src/LeadPulse.Api/LeadPulse.Api.csproj src/LeadPulse.Api/
RUN dotnet restore src/LeadPulse.Api/LeadPulse.Api.csproj

COPY src/ src/
RUN dotnet publish src/LeadPulse.Api/LeadPulse.Api.csproj -c Release -o /app/publish --no-restore

# Runtime stage
FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app

RUN adduser --disabled-password --gecos '' appuser
USER appuser

COPY --from=build /app/publish .

EXPOSE 8080
ENV ASPNETCORE_URLS=http://+:8080
ENV ASPNETCORE_ENVIRONMENT=Production

ENTRYPOINT ["dotnet", "LeadPulse.Api.dll"]
