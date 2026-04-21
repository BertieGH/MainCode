using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace LeadPulse.Infrastructure.Migrations.TenantDb
{
    /// <inheritdoc />
    public partial class AddEnhancedLinkedInFields : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "EncryptedLinkedInCookie",
                table: "LinkedInScraperSettings",
                type: "longtext",
                nullable: true)
                .Annotation("MySql:CharSet", "utf8mb4");

            migrationBuilder.AddColumn<DateTime>(
                name: "LinkedInCookieExpiresAt",
                table: "LinkedInScraperSettings",
                type: "datetime(6)",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "CommentsJson",
                table: "LinkedInPosts",
                type: "longtext",
                nullable: true)
                .Annotation("MySql:CharSet", "utf8mb4");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "EncryptedLinkedInCookie",
                table: "LinkedInScraperSettings");

            migrationBuilder.DropColumn(
                name: "LinkedInCookieExpiresAt",
                table: "LinkedInScraperSettings");

            migrationBuilder.DropColumn(
                name: "CommentsJson",
                table: "LinkedInPosts");
        }
    }
}
