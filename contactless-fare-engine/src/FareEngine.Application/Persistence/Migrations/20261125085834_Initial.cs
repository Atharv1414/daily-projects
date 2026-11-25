using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace FareEngine.Application.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class Initial : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "Jobs",
                columns: table => new
                {
                    CardToken = table.Column<string>(type: "TEXT", nullable: false),
                    WeekStart = table.Column<DateOnly>(type: "TEXT", nullable: false),
                    Revision = table.Column<long>(type: "INTEGER", nullable: false),
                    DueAtMs = table.Column<long>(type: "INTEGER", nullable: false),
                    Attempts = table.Column<int>(type: "INTEGER", nullable: false),
                    LastError = table.Column<string>(type: "TEXT", nullable: true),
                    Dead = table.Column<bool>(type: "INTEGER", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Jobs", x => new { x.CardToken, x.WeekStart });
                });

            migrationBuilder.CreateTable(
                name: "SettlementLines",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    SettlementDate = table.Column<DateOnly>(type: "TEXT", nullable: false),
                    CardToken = table.Column<string>(type: "TEXT", nullable: false),
                    AmountPence = table.Column<long>(type: "INTEGER", nullable: false),
                    EntryCount = table.Column<int>(type: "INTEGER", nullable: false),
                    CreatedAtMs = table.Column<long>(type: "INTEGER", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_SettlementLines", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "SettlementRuns",
                columns: table => new
                {
                    SettlementDate = table.Column<DateOnly>(type: "TEXT", nullable: false),
                    Lines = table.Column<int>(type: "INTEGER", nullable: false),
                    CollectedPence = table.Column<long>(type: "INTEGER", nullable: false),
                    RefundedPence = table.Column<long>(type: "INTEGER", nullable: false),
                    CompletedAtMs = table.Column<long>(type: "INTEGER", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_SettlementRuns", x => x.SettlementDate);
                });

            migrationBuilder.CreateTable(
                name: "Taps",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "TEXT", nullable: false),
                    CardToken = table.Column<string>(type: "TEXT", maxLength: 64, nullable: false),
                    PlaceId = table.Column<string>(type: "TEXT", maxLength: 32, nullable: false),
                    Kind = table.Column<string>(type: "TEXT", maxLength: 8, nullable: false),
                    OccurredAtMs = table.Column<long>(type: "INTEGER", nullable: false),
                    ReceivedAtMs = table.Column<long>(type: "INTEGER", nullable: false),
                    Source = table.Column<string>(type: "TEXT", maxLength: 20, nullable: false),
                    SubmittedBy = table.Column<string>(type: "TEXT", nullable: false),
                    Reason = table.Column<string>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Taps", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "Ledger",
                columns: table => new
                {
                    Id = table.Column<long>(type: "INTEGER", nullable: false)
                        .Annotation("Sqlite:Autoincrement", true),
                    CardToken = table.Column<string>(type: "TEXT", nullable: false),
                    WeekStart = table.Column<DateOnly>(type: "TEXT", nullable: false),
                    ServiceDate = table.Column<DateOnly>(type: "TEXT", nullable: false),
                    AmountPence = table.Column<long>(type: "INTEGER", nullable: false),
                    Kind = table.Column<string>(type: "TEXT", maxLength: 12, nullable: false),
                    PostedAtMs = table.Column<long>(type: "INTEGER", nullable: false),
                    SettlementLineId = table.Column<long>(type: "INTEGER", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Ledger", x => x.Id);
                    table.CheckConstraint("CK_Ledger_NonZero", "AmountPence <> 0");
                    table.ForeignKey(
                        name: "FK_Ledger_SettlementLines_SettlementLineId",
                        column: x => x.SettlementLineId,
                        principalTable: "SettlementLines",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "IX_Jobs_Dead_DueAtMs",
                table: "Jobs",
                columns: new[] { "Dead", "DueAtMs" });

            migrationBuilder.CreateIndex(
                name: "IX_Ledger_CardToken_WeekStart",
                table: "Ledger",
                columns: new[] { "CardToken", "WeekStart" });

            migrationBuilder.CreateIndex(
                name: "IX_Ledger_SettlementLineId_ServiceDate",
                table: "Ledger",
                columns: new[] { "SettlementLineId", "ServiceDate" });

            migrationBuilder.CreateIndex(
                name: "IX_SettlementLines_SettlementDate_CardToken",
                table: "SettlementLines",
                columns: new[] { "SettlementDate", "CardToken" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_Taps_CardToken_OccurredAtMs",
                table: "Taps",
                columns: new[] { "CardToken", "OccurredAtMs" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "Jobs");

            migrationBuilder.DropTable(
                name: "Ledger");

            migrationBuilder.DropTable(
                name: "SettlementRuns");

            migrationBuilder.DropTable(
                name: "Taps");

            migrationBuilder.DropTable(
                name: "SettlementLines");
        }
    }
}
