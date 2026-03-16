FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
WORKDIR /app
EXPOSE 8080

FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY ["LeadPulse.Api/LeadPulse.Api.csproj", "LeadPulse.Api/"]
COPY ["LeadPulse.Application/LeadPulse.Application.csproj", "LeadPulse.Application/"]
COPY ["LeadPulse.Domain/LeadPulse.Domain.csproj", "LeadPulse.Domain/"]
COPY ["LeadPulse.Infrastructure/LeadPulse.Infrastructure.csproj", "LeadPulse.Infrastructure/"]
RUN dotnet restore "LeadPulse.Api/LeadPulse.Api.csproj"
COPY . .
RUN dotnet build "LeadPulse.Api/LeadPulse.Api.csproj" -c Release -o /app/build

FROM build AS publish
RUN dotnet publish "LeadPulse.Api/LeadPulse.Api.csproj" -c Release -o /app/publish /p:UseAppHost=false

FROM base AS final
WORKDIR /app
COPY --from=publish /app/publish .
ENTRYPOINT ["dotnet", "LeadPulse.Api.dll"]
