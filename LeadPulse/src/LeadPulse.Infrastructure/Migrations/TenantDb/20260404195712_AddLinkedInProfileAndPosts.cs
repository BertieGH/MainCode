using System;
using Microsoft.EntityFrameworkCore.Metadata;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace LeadPulse.Infrastructure.Migrations.TenantDb
{
    /// <inheritdoc />
    public partial class AddLinkedInProfileAndPosts : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "LinkedInAbout",
                table: "Prospects",
                type: "longtext",
                nullable: true)
                .Annotation("MySql:CharSet", "utf8mb4");

            migrationBuilder.AddColumn<string>(
                name: "LinkedInContactInfo",
                table: "Prospects",
                type: "longtext",
                nullable: true)
                .Annotation("MySql:CharSet", "utf8mb4");

            migrationBuilder.AddColumn<string>(
                name: "LinkedInHeadline",
                table: "Prospects",
                type: "longtext",
                nullable: true)
                .Annotation("MySql:CharSet", "utf8mb4");

            migrationBuilder.AddColumn<string>(
                name: "LinkedInPhotoUrl",
                table: "Prospects",
                type: "longtext",
                nullable: true)
                .Annotation("MySql:CharSet", "utf8mb4");

            migrationBuilder.AddColumn<DateTime>(
                name: "LinkedInScrapedAt",
                table: "Prospects",
                type: "datetime(6)",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "LinkedInType",
                table: "Prospects",
                type: "longtext",
                nullable: true)
                .Annotation("MySql:CharSet", "utf8mb4");

            migrationBuilder.CreateTable(
                name: "LinkedInPosts",
                columns: table => new
                {
                    Id = table.Column<int>(type: "int", nullable: false)
                        .Annotation("MySql:ValueGenerationStrategy", MySqlValueGenerationStrategy.IdentityColumn),
                    ProspectId = table.Column<int>(type: "int", nullable: false),
                    Content = table.Column<string>(type: "longtext", nullable: false)
                        .Annotation("MySql:CharSet", "utf8mb4"),
                    PostUrl = table.Column<string>(type: "longtext", nullable: true)
                        .Annotation("MySql:CharSet", "utf8mb4"),
                    PostDate = table.Column<DateTime>(type: "datetime(6)", nullable: true),
                    Likes = table.Column<int>(type: "int", nullable: false),
                    Comments = table.Column<int>(type: "int", nullable: false),
                    ScrapedAt = table.Column<DateTime>(type: "datetime(6)", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_LinkedInPosts", x => x.Id);
                    table.ForeignKey(
                        name: "FK_LinkedInPosts_Prospects_ProspectId",
                        column: x => x.ProspectId,
                        principalTable: "Prospects",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                })
                .Annotation("MySql:CharSet", "utf8mb4");

            migrationBuilder.CreateIndex(
                name: "IX_LinkedInPosts_ProspectId",
                table: "LinkedInPosts",
                column: "ProspectId");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "LinkedInPosts");

            migrationBuilder.DropColumn(
                name: "LinkedInAbout",
                table: "Prospects");

            migrationBuilder.DropColumn(
                name: "LinkedInContactInfo",
                table: "Prospects");

            migrationBuilder.DropColumn(
                name: "LinkedInHeadline",
                table: "Prospects");

            migrationBuilder.DropColumn(
                name: "LinkedInPhotoUrl",
                table: "Prospects");

            migrationBuilder.DropColumn(
                name: "LinkedInScrapedAt",
                table: "Prospects");

            migrationBuilder.DropColumn(
                name: "LinkedInType",
                table: "Prospects");
        }
    }
}
