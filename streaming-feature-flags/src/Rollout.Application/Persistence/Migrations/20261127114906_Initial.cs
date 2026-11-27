using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Rollout.Application.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class Initial : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "Audit",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    Environment = table.Column<string>(type: "TEXT", maxLength: 32, nullable: false),
                    FlagKey = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false),
                    Version = table.Column<long>(type: "INTEGER", nullable: false),
                    Actor = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false),
                    Action = table.Column<string>(type: "TEXT", maxLength: 16, nullable: false),
                    Changes = table.Column<string>(type: "TEXT", nullable: false),
                    BeforeJson = table.Column<string>(type: "TEXT", nullable: true),
                    AfterJson = table.Column<string>(type: "TEXT", nullable: false),
                    AtMs = table.Column<long>(type: "INTEGER", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Audit", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "Exposures",
                columns: table => new
                {
                    Environment = table.Column<string>(type: "TEXT", maxLength: 32, nullable: false),
                    FlagKey = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false),
                    Variant = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false),
                    HourStartMs = table.Column<long>(type: "INTEGER", nullable: false),
                    Count = table.Column<long>(type: "INTEGER", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Exposures", x => new { x.Environment, x.FlagKey, x.Variant, x.HourStartMs });
                    table.CheckConstraint("CK_Exposures_Count", "Count > 0");
                });

            migrationBuilder.CreateTable(
                name: "Flags",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    Environment = table.Column<string>(type: "TEXT", maxLength: 32, nullable: false),
                    Key = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false),
                    DefinitionJson = table.Column<string>(type: "TEXT", nullable: false),
                    Version = table.Column<long>(type: "INTEGER", nullable: false),
                    Archived = table.Column<bool>(type: "INTEGER", nullable: false),
                    UpdatedAtMs = table.Column<long>(type: "INTEGER", nullable: false),
                    UpdatedBy = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Flags", x => x.Id);
                    table.CheckConstraint("CK_Flags_Version", "Version >= 1");
                });

            migrationBuilder.CreateIndex(
                name: "IX_Audit_Environment_FlagKey_Version",
                table: "Audit",
                columns: new[] { "Environment", "FlagKey", "Version" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_Flags_Environment_Key",
                table: "Flags",
                columns: new[] { "Environment", "Key" },
                unique: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "Audit");

            migrationBuilder.DropTable(
                name: "Exposures");

            migrationBuilder.DropTable(
                name: "Flags");
        }
    }
}
