using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using Survey.Core.Entities;

namespace Survey.Infrastructure.Data.Configurations;

public class ResponseConfiguration : IEntityTypeConfiguration<Response>
{
    public void Configure(EntityTypeBuilder<Response> builder)
    {
        builder.ToTable("Responses");

        builder.HasKey(r => r.Id);

        builder.Property(r => r.CrmClientId)
            .IsRequired()
            .HasMaxLength(100);

        builder.Property(r => r.ClientData)
            .HasColumnType("JSON");

        builder.Property(r => r.IsComplete)
            .HasDefaultValue(false);

        builder.Property(r => r.IpAddress)
            .HasMaxLength(50);

        builder.Property(r => r.UserAgent)
            .HasMaxLength(500);

        builder.HasMany(r => r.Answers)
            .WithOne(a => a.Response)
            .HasForeignKey(a => a.ResponseId)
            .OnDelete(DeleteBehavior.Cascade);
    }
}
