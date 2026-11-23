using Microsoft.EntityFrameworkCore;
using StockReservation.Application.Persistence;
using StockReservation.Domain;

namespace StockReservation.Application.Seeding;

/// <summary>
/// Seeds a deterministic UK distribution network: four sites and a catalogue of SKUs, with skewed
/// stock levels (a few fast movers, a long tail, some lines already near their reorder point).
/// </summary>
public static class DataSeeder
{
    public static readonly IReadOnlyList<(string Code, string Site)> Warehouses =
    [
        ("DIR1", "Daventry DIRFT"),
        ("MAN1", "Manchester Trafford Park"),
        ("BRS1", "Bristol Avonmouth"),
        ("GLA1", "Glasgow Eurocentral"),
    ];

    private static readonly string[] Categories = ["KIT", "GDN", "DIY", "TOY", "ELC", "PET"];

    private static readonly string[] Nouns =
    [
        "Kettle", "Toaster", "Hose Reel", "Planter", "Drill Bit Set", "Paint Roller", "Board Game",
        "Building Blocks", "Desk Lamp", "Extension Lead", "Dog Bed", "Cat Scratcher", "Saucepan Set",
        "Garden Kneeler", "Spirit Level", "Jigsaw Puzzle", "LED Bulb Pack", "Bird Feeder",
    ];

    public static async Task<int> SeedAsync(StockDbContext db, int skusPerWarehouse, int seed, DateTimeOffset now, CancellationToken ct)
    {
        if (await db.StockItems.AnyAsync(ct))
        {
            return 0;
        }

        var random = new Random(seed);
        var count = 0;
        foreach (var (code, _) in Warehouses)
        {
            for (var i = 1; i <= skusPerWarehouse; i++)
            {
                var category = Categories[(i - 1) % Categories.Length];
                var sku = $"{category}-{i:D5}";
                var noun = Nouns[(i * 7) % Nouns.Length];
                // Pareto-ish skew: ~10% fast movers carry most of the stock.
                var fastMover = random.NextDouble() < 0.1;
                var onHand = fastMover ? random.Next(500, 5_000) : random.Next(0, 300);
                var reorder = fastMover ? random.Next(100, 400) : random.Next(5, 40);
                var costPence = random.Next(149, 8_999);
                db.StockItems.Add(new StockItem(code, sku, $"{noun} ({category})", onHand, reorder, costPence, now));
                count++;
            }
        }

        await db.SaveChangesAsync(ct);
        return count;
    }
}
