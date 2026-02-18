using Microsoft.EntityFrameworkCore;
using Survey.Core.Entities;
using Survey.Core.Enums;
using System.Text.Json;

namespace Survey.Infrastructure.Data;

public class SurveyDbContext : DbContext
{
    public SurveyDbContext(DbContextOptions<SurveyDbContext> options) : base(options)
    {
    }

    public DbSet<QuestionCategory> QuestionCategories { get; set; }
    public DbSet<QuestionBank> QuestionBank { get; set; }
    public DbSet<QuestionBankOption> QuestionBankOptions { get; set; }
    public DbSet<Core.Entities.Survey> Surveys { get; set; }
    public DbSet<SurveyQuestion> SurveyQuestions { get; set; }
    public DbSet<SurveyQuestionOption> SurveyQuestionOptions { get; set; }
    public DbSet<FieldMapping> FieldMappings { get; set; }
    public DbSet<Response> Responses { get; set; }
    public DbSet<ResponseAnswer> ResponseAnswers { get; set; }
    public DbSet<User> Users { get; set; }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        // Apply all configurations from assembly
        modelBuilder.ApplyConfigurationsFromAssembly(typeof(SurveyDbContext).Assembly);

        // Configure enum to string conversions
        modelBuilder.Entity<QuestionBank>()
            .Property(q => q.QuestionType)
            .HasConversion<string>();

        modelBuilder.Entity<SurveyQuestion>()
            .Property(sq => sq.QuestionType)
            .HasConversion<string>();

        modelBuilder.Entity<Core.Entities.Survey>()
            .Property(s => s.Status)
            .HasConversion<string>();

        modelBuilder.Entity<User>()
            .Property(u => u.Role)
            .HasConversion<string>();

        // Configure JSON column for ResponseAnswer.SelectedOptionIds
        modelBuilder.Entity<ResponseAnswer>()
            .Property(ra => ra.SelectedOptionIds)
            .HasConversion(
                v => JsonSerializer.Serialize(v, (JsonSerializerOptions)null!),
                v => JsonSerializer.Deserialize<List<int>>(v, (JsonSerializerOptions)null!)
            );
    }
}
